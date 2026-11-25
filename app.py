from pathlib import Path
import json
import os
import re
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import services

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=True)
app = FastAPI(title='Wayfinder AI', version='2.1')
app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')

class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
class SearchBody(Location):
    category: str = 'restaurant'
    keyword: str = ''
    radius: int = Field(default=5000, ge=250, le=30000)
class RouteBody(BaseModel):
    start: Location
    end: Location
    mode: str = 'drive'
class TripBody(BaseModel):
    destination: str = Field(min_length=2, max_length=180)
    days: int = Field(default=3, ge=1, le=14)
    budget: float = Field(default=0, ge=0)
    travelers: int = Field(default=1, ge=1, le=20)
    interests: str = Field(default='', max_length=400)
class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=1200)
    origin: Location | None = None
    origin_label: str = ''
    history: list[dict] = Field(default_factory=list, max_length=12)

@app.exception_handler(services.ProviderError)
async def provider_error_handler(request, exc: services.ProviderError):
    from fastapi.responses import JSONResponse
    status = (503 if exc.provider == 'Configuration' else 404 if exc.status == 404
              else 422 if exc.status == 422 else 502)
    return JSONResponse(status_code=status, content={'error': exc.provider, 'detail': str(exc)})

@app.get('/')
async def index():
    return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/health')
async def health():
    return {'ok': True, 'gemini_configured': services.configured('GEMINI_API_KEY'),
            'geoapify_configured': services.configured('GEOAPIFY_API_KEY'),
            'model': os.getenv('GEMINI_MODEL', 'auto'),
            'active_model': services._active_model}

@app.get('/api/geocode')
async def geo(q: str, lat: float | None = None, lon: float | None = None):
    if not q.strip():
        raise HTTPException(400, 'Enter a location.')
    return {'results': await services.geocode(q[:200], bias_lat=lat, bias_lon=lon)}

@app.get('/api/reverse')
async def reverse(lat: float, lon: float):
    return {'label': await services.reverse_geocode(lat, lon)}

@app.post('/api/places')
async def places(body: SearchBody):
    return {'results': await services.places(body.lat, body.lon, body.category, body.radius, keyword=body.keyword)}

@app.post('/api/route')
async def route(body: RouteBody):
    return await services.route((body.start.lat,body.start.lon), (body.end.lat,body.end.lon), body.mode)

@app.post('/api/trip')
async def trip(body: TripBody):
    return await services.itinerary(body.destination, body.days, body.budget, body.travelers, body.interests)

@app.get('/api/models')
async def models():
    return {'models': await services.list_gemini_models()}

@app.get('/api/ai/status')
async def ai_connection(probe: bool = True):
    return await services.ai_status(probe=probe)

class DirectChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=2500)
    history: list[dict] = Field(default_factory=list, max_length=12)
    origin: Location | None = None
    origin_label: str = Field(default='', max_length=200)
    map_places: list[dict] = Field(default_factory=list, max_length=25)

def _compact_map_places(map_places: list[dict]) -> list[dict]:
    compact = []
    for idx, p in enumerate((map_places or [])[:15], 1):
        if not isinstance(p, dict):
            continue
        compact.append({
            'index': p.get('index', idx),
            'name': str(p.get('name') or 'Unnamed place')[:140],
            'address': str(p.get('address') or '')[:220],
            'category': str(p.get('category') or '')[:100],
            'distance_m': p.get('distance_m'),
            'lat': p.get('lat'),
            'lon': p.get('lon'),
        })
    return compact

async def _generate_grounded_assistant_reply(
    user_message: str,
    history_turns: list[dict],
    loc_context: str,
    map_places: list[dict],
    fallback_prompt: str,
) -> tuple[str, list[dict], str]:
    api_key = os.getenv('GEMINI_API_KEY', '').strip()
    preferred_model = os.getenv('GEMINI_MODEL', '').strip()
    model_name = preferred_model if (preferred_model and preferred_model != 'auto') else 'gemini-2.5-flash'

    if genai is None or types is None or not api_key:
        text = await services.gemini(fallback_prompt)
        return text, [], services._active_model

    system_instruction = (
        'You are Wayfinder AI, a helpful travel and local navigation assistant paired with an interactive Geoapify map. '
        'Always respect the user’s current location context when giving recommendations. '
        'Never suggest locations in another country unless the user explicitly asks for them. '
        'When the user asks about places currently on their map, specific spots, reviews, ratings, opening hours, menus, or practical info, '
        'match against PLACES_ON_MAP and use Google Search to retrieve up-to-date details.'
    )

    context_block = (
        f'User current location: {loc_context}\n'
        f'PLACES_ON_MAP: {json.dumps(_compact_map_places(map_places))}'
    )

    contents = []
    for turn in history_turns[-10:]:
        role = str(turn.get('role', ''))
        content = str(turn.get('content', ''))[:1200]
        if role in {'user', 'assistant'} and content:
            gemini_role = 'user' if role == 'user' else 'model'
            contents.append(types.Content(role=gemini_role, parts=[types.Part.from_text(text=content)]))

    contents.append(
        types.Content(
            role='user',
            parts=[types.Part.from_text(text=f'{context_block}\n\nQuestion: {user_message}')],
        )
    )

    def _call_sdk():
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(
            model=model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.4,
            ),
        )

    try:
        import asyncio
        response = await asyncio.to_thread(_call_sdk)
    except Exception as exc:
        raise services.ProviderError('Gemini', str(exc)) from exc

    sources: list[dict] = []
    seen_urls: set[str] = set()
    candidates = getattr(response, 'candidates', None) or []
    if candidates:
        grounding = getattr(candidates[0], 'grounding_metadata', None)
        chunks = getattr(grounding, 'grounding_chunks', None) or []
        for chunk in chunks:
            web = getattr(chunk, 'web', None)
            uri = getattr(web, 'uri', None) if web else None
            title = getattr(web, 'title', None) if web else None
            if uri and uri not in seen_urls:
                seen_urls.add(uri)
                sources.append({'title': title or uri, 'url': uri})

    return response.text or '', sources, model_name

async def _resolve_nearby_query(message: str, origin: Location | None, origin_label: str) -> tuple[dict, list[dict], Location | None, str]:
    """Shared intent + Geoapify resolver for both Discover chat and floating AI assistant."""
    try:
        plan = await services.classify(message, origin_label=origin_label)
        ai_ok = True
    except services.ProviderError:
        plan = services.heuristic(message)
        ai_ok = False

    if plan.get('intent') != 'nearby':
        return plan, [], origin, origin_label

    search_origin = origin
    search_label = origin_label
    requested_origin = str(plan.get('origin') or '').strip()

    if requested_origin and requested_origin.lower() not in {'me', 'my location', 'here', 'current location'}:
        matches = await services.geocode(
            requested_origin,
            bias_lat=origin.lat if origin else None,
            bias_lon=origin.lon if origin else None
        )
        if matches:
            search_origin = Location(lat=matches[0]['lat'], lon=matches[0]['lon'])
            search_label = matches[0]['name']
    elif search_origin is None:
        explicit = re.search(r'\b(?:near|in|around|at)\s+(?!me\b|my\b|here\b)(.+)$', message, flags=re.I)
        if explicit:
            matches = await services.geocode(explicit.group(1).strip(' ?.'))
            if matches:
                search_origin = Location(lat=matches[0]['lat'], lon=matches[0]['lon'])
                search_label = matches[0]['name']

    if search_origin is None:
        return plan, [], None, search_label

    cat = str(plan.get('category') or message)[:90]
    results = await services.places(search_origin.lat, search_origin.lon, cat, radius=8000, keyword=cat)
    plan['_ai_ok'] = ai_ok
    return plan, results, search_origin, search_label


@app.post('/api/assistant')
async def direct_assistant(body: DirectChatBody):
    # Check if the user is asking for nearby places right inside the floating chat bubble
    plan, results, resolved_origin, resolved_label = await _resolve_nearby_query(
        body.message, body.origin, body.origin_label
    )
    if plan.get('intent') == 'nearby':
        if resolved_origin is None:
            return {
                'text': 'Please click "Use my location" in the sidebar (or include a city/area name like "in Kolkata") so I can search nearby places for you.',
                'model': services._active_model
            }
        cat = plan.get('category') or body.message
        if not results:
            return {
                'text': f'I searched around {resolved_label} for "{cat}", but no mapped entries appeared within 15 km. Try a broader term or check the Nearby Places tab.',
                'model': services._active_model
            }
        lines = [f'Here are the closest mapped **{cat}** locations near **{resolved_label}**:\n']
        for i, p in enumerate(results[:6], 1):
            dist = f"{p['distance_m']/1000:.1f} km" if p['distance_m'] >= 1000 else f"{p['distance_m']} m"
            lines.append(f"{i}. {p['name']} ({dist}) — {p['address'] or 'Address listed on map'}")
        return {
            'text': '\n'.join(lines),
            'model': services._active_model,
            'places': results,
            'center': resolved_origin.model_dump()
        }

    history_lines = []
    for turn in body.history[-10:]:
        role = str(turn.get('role', ''))
        content = str(turn.get('content', ''))[:1200]
        if role in {'user', 'assistant'} and content:
            history_lines.append(f'{role.upper()}: {content}')
    loc_context = (f'{body.origin_label} ({body.origin.lat:.4f}, {body.origin.lon:.4f})'
                   if body.origin else (body.origin_label or 'not selected (assume India if regional context is needed)'))
    fallback_prompt = (
        'You are Wayfinder AI, a helpful travel and local navigation assistant. '
        'Always respect the user’s current location context when giving recommendations. '
        'Never suggest locations in another country unless the user explicitly asks for them.\n'
        f'User current location: {loc_context}.\n'
        + '\n'.join(history_lines) + f'\nUSER: {body.message}\nASSISTANT:'
    )
    reply_text, sources, used_model = await _generate_grounded_assistant_reply(
        user_message=body.message,
        history_turns=body.history,
        loc_context=loc_context,
        map_places=body.map_places,
        fallback_prompt=fallback_prompt,
    )
    return {'text': reply_text, 'sources': sources, 'model': used_model}


@app.post('/api/chat')
async def chat(body: ChatBody):
    message = body.message.strip()
    ai_error = ''
    try:
        plan = await services.classify(message, origin_label=body.origin_label)
        ai_available = True
    except services.ProviderError as exc:
        plan = services.heuristic(message)
        ai_available = False
        ai_error = str(exc)

    intent = plan.get('intent', 'chat')
    if intent == 'nearby':
        origin = body.origin
        origin_name = body.origin_label
        requested_origin = str(plan.get('origin') or '').strip()
        if requested_origin and requested_origin.lower() not in {'me', 'my location', 'here', 'current location'}:
            matches = await services.geocode(
                requested_origin,
                bias_lat=origin.lat if origin else None,
                bias_lon=origin.lon if origin else None
            )
            if matches:
                origin = Location(lat=matches[0]['lat'], lon=matches[0]['lon'])
                origin_name = matches[0]['name']
        if origin is None:
            explicit = re.search(r'\b(?:near|in|around|at)\s+(?!me\b|my\b|here\b)(.+)$', message, flags=re.I)
            if explicit:
                matches = await services.geocode(explicit.group(1).strip(' ?.'))
                if matches:
                    origin = Location(lat=matches[0]['lat'], lon=matches[0]['lon'])
                    origin_name = matches[0]['name']
        if origin is None:
            return {'kind': 'message', 'text': 'Set your starting point using "Use my location" in the sidebar (or mention a city like "in Kolkata"), then try again.', 'ai_available': ai_available}
        cat = str(plan.get('category') or message)[:90]
        results = await services.places(origin.lat, origin.lon, cat, radius=8000, keyword=cat)
        if not results:
            return {'kind': 'message', 'text': f'No mapped "{cat}" locations were found within 15 km of {origin_name or "your location"}. Try a slightly broader search term.', 'ai_available': ai_available}
        return {'kind': 'places', 'text': f'Found {len(results)} mapped {cat} locations near {origin_name or "your location"}. Click any card to view on the map or get directions.',
                'results': results, 'center': origin.model_dump(), 'ai_available': ai_available}

    if intent == 'route':
        dest = str(plan.get('destination') or '').strip()
        if not dest:
            match = re.search(r'(?:to|towards)\s+(.+)$', message, flags=re.I)
            dest = match.group(1).strip(' ?.') if match else ''
        if not dest:
            return {'kind': 'message', 'text': 'Enter a destination in the Directions tab so I can calculate a real route.', 'ai_available': ai_available}
        if body.origin is None:
            return {'kind': 'message', 'text': 'Select a starting location first, then I can calculate a route.', 'ai_available': ai_available}
        candidates = await services.geocode(dest, bias_lat=body.origin.lat, bias_lon=body.origin.lon)
        if not candidates:
            return {'kind': 'message', 'text': f'I could not find “{dest}” on the map. Try a more specific address.', 'ai_available': ai_available}
        endpoint = candidates[0]
        result = await services.route((body.origin.lat, body.origin.lon), (endpoint['lat'], endpoint['lon']))
        return {'kind': 'route', 'text': f'Here is a driving route to {endpoint["name"]}. Travel times are estimates without live traffic.',
                'route': result, 'destination': endpoint, 'ai_available': ai_available}

    if intent == 'trip':
        dest = str(plan.get('destination') or '').strip()
        if not dest:
            match = re.search(r'(?:to|in|for)\s+([A-Za-z][A-Za-z\s,]+?)(?:\s+for\s+\d+|\s+under\s+|$)', message, re.I)
            dest = match.group(1).strip() if match else ''
        if not dest:
            return {'kind': 'message', 'text': 'Use the Trip planner tab and enter a destination, number of days, and budget.', 'ai_available': ai_available}
        data = await services.itinerary(dest, max(1,min(14,int(plan.get('days') or 3))), float(plan.get('budget') or 0), max(1,int(plan.get('travelers') or 1)), '')
        is_ai = data.get('source') == 'gemini'
        return {'kind': 'trip', 'text': (f'Here is a draft AI itinerary for {dest}.' if is_ai
                else f'Gemini is unavailable; here is a map-based itinerary draft for {dest}.'),
                'trip': data, 'ai_available': is_ai, 'ai_error': ai_error if not is_ai else ''}

    if not ai_available:
        return {'kind': 'message', 'text': 'Gemini could not answer: ' + ai_error + '\nNearby searches, routes, and map-based trip drafts remain available.', 'ai_available': False, 'ai_error': ai_error}
    try:
        loc_hint = f'User current location: {body.origin_label} ({body.origin.lat:.4f}, {body.origin.lon:.4f}). ' if body.origin else ''
        history = '\n'.join(f'{x.get("role")}: {str(x.get("content",""))[:800]}' for x in body.history[-8:] if x.get('role') in ('user','assistant'))
        text = await services.gemini(f'You are Wayfinder AI, a helpful local navigation assistant. {loc_hint}Keep suggestions strictly relevant to the user’s region.\n' + history + '\nUser: ' + message)
        return {'kind': 'message', 'text': text, 'ai_available': True}
    except services.ProviderError as exc:
        return {'kind': 'message', 'text': 'Gemini error: ' + str(exc), 'ai_available': False, 'ai_error': str(exc)}