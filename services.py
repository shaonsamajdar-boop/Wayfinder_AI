"""Provider boundary: all secrets and third-party calls happen server-side."""
import asyncio
import json
import math
import random
import os
import re
import time
from typing import Any
import httpx

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEO_BASE = "https://api.geoapify.com"

class ProviderError(Exception):
    def __init__(self, provider: str, message: str, status: int = 502):
        super().__init__(message)
        self.provider = provider
        self.status = status


def _error_detail(response: httpx.Response) -> str:
    try:
        obj = response.json()
        message = obj.get('error', {}).get('message') or obj.get('message')
        if message:
            return str(message)[:450]
    except (ValueError, AttributeError):
        pass
    return response.text[:250] or f'HTTP {response.status_code}'


async def fetch_json(url: str, params: dict | None = None, headers: dict | None = None, payload: dict | None = None, provider: str = 'Service') -> dict:
    try:
        async with httpx.AsyncClient(timeout=24.0) as client:
            if payload is None:
                result = await client.get(url, params=params, headers=headers)
            else:
                result = await client.post(url, params=params, headers=headers, json=payload)
        if result.status_code >= 400:
            raise ProviderError(provider, _error_detail(result), result.status_code)
        return result.json()
    except httpx.RequestError as exc:
        raise ProviderError(provider, f'Network error: {type(exc).__name__}') from exc
    except ValueError as exc:
        raise ProviderError(provider, 'Provider returned invalid JSON') from exc


def key(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value or value.lower().startswith(('your_', 'paste_', 'replace_', 'example_', '<')):
        raise ProviderError('Configuration', f'Missing {name}. Add your actual key to .env and restart the server.', 503)
    return value


async def reverse_geocode(lat: float, lon: float) -> str:
    """Convert GPS coordinates into a human-readable neighborhood/city label."""
    try:
        obj = await fetch_json(f'{GEO_BASE}/v1/geocode/reverse', {
            'lat': lat, 'lon': lon, 'format': 'json', 'apiKey': key('GEOAPIFY_API_KEY')
        }, provider='Geoapify')
        results = obj.get('results', [])
        if results:
            r = results[0]
            parts = [r.get('suburb') or r.get('neighbourhood') or r.get('district'),
                     r.get('city') or r.get('town') or r.get('state_district'),
                     r.get('state'), r.get('country')]
            clean = ', '.join(dict.fromkeys(p for p in parts if p))
            return clean or r.get('formatted') or f'{lat:.4f}, {lon:.4f}'
    except ProviderError:
        pass
    return f'{lat:.4f}, {lon:.4f}'


async def geocode(query: str, bias_lat: float | None = None, bias_lon: float | None = None) -> list[dict]:
    params: dict[str, Any] = {
        'text': query, 'limit': 6, 'format': 'json', 'apiKey': key('GEOAPIFY_API_KEY')
    }
    if bias_lat is not None and bias_lon is not None:
        params['bias'] = f'proximity:{bias_lon},{bias_lat}'
    obj = await fetch_json(f'{GEO_BASE}/v1/geocode/search', params, provider='Geoapify')
    results, seen = [], set()
    for x in obj.get('results', []):
        if 'lat' not in x or 'lon' not in x:
            continue
        identity = (round(float(x['lat']), 5), round(float(x['lon']), 5))
        if identity in seen:
            continue
        seen.add(identity)
        results.append({'name': x.get('formatted') or x.get('address_line1') or query,
                        'lat': float(x['lat']), 'lon': float(x['lon']),
                        'city': x.get('city', ''),
                        'result_type': x.get('result_type', '')})
    return results


CATEGORIES = {
    'police station': 'service.police',
    'police': 'service.police',
    'thana': 'service.police',
    'fire station': 'service.fire_station',
    'post office': 'service.post.office',
    'courier': 'service.post',
    'hospital': 'healthcare.hospital,healthcare.clinic_or_praxis',
    'hospitals': 'healthcare.hospital,healthcare.clinic_or_praxis',
    'clinic': 'healthcare.clinic_or_praxis,healthcare.hospital',
    'doctor': 'healthcare.clinic_or_praxis,healthcare.hospital',
    'dentist': 'healthcare.dentist',
    'pharmacy': 'healthcare.pharmacy',
    'medical': 'healthcare.pharmacy,healthcare.hospital',
    'chemist': 'healthcare.pharmacy',
    'laptop repair': 'commercial.elektronics,service,commercial',
    'computer repair': 'commercial.elektronics,service,commercial',
    'mobile repair': 'commercial.elektronics,service,commercial',
    'phone repair': 'commercial.elektronics,service,commercial',
    'electronics repair': 'commercial.elektronics,service,commercial',
    'repair': 'service.vehicle.repair,commercial.elektronics,service,commercial',
    'laptop': 'commercial.elektronics',
    'computer': 'commercial.elektronics',
    'electronics': 'commercial.elektronics',
    'mobile': 'commercial.elektronics',
    'car repair': 'service.vehicle.repair',
    'garage': 'service.vehicle.repair',
    'mechanic': 'service.vehicle.repair',
    'salon': 'service.beauty.hairdresser,service.beauty',
    'barber': 'service.beauty.hairdresser',
    'spa': 'service.beauty.spa',
    'laundry': 'service.cleaning.laundry',
    'restaurant': 'catering.restaurant',
    'restaurants': 'catering.restaurant',
    'food': 'catering.restaurant,catering.fast_food',
    'ramen': 'catering.restaurant',
    'biryani': 'catering.restaurant',
    'fast food': 'catering.fast_food',
    'cafe': 'catering.cafe',
    'coffee': 'catering.cafe',
    'tea': 'catering.cafe',
    'bakery': 'commercial.food_and_drink.bakery',
    'hotel': 'accommodation.hotel,accommodation.guest_house',
    'hotels': 'accommodation.hotel,accommodation.guest_house',
    'museum': 'entertainment.museum',
    'attraction': 'tourism.attraction,tourism.sights',
    'tourist': 'tourism.attraction,tourism.sights',
    'sightseeing': 'tourism.attraction,tourism.sights',
    'park': 'leisure.park',
    'gym': 'sport.fitness.fitness_centre',
    'atm': 'service.financial.atm',
    'bank': 'service.financial.bank',
    'fuel': 'service.vehicle.fuel',
    'petrol': 'service.vehicle.fuel',
    'petrol pump': 'service.vehicle.fuel',
    'shopping': 'commercial.shopping_mall,commercial.department_store',
    'mall': 'commercial.shopping_mall',
    'supermarket': 'commercial.supermarket',
    'grocery': 'commercial.supermarket,commercial.convenience',
    'flower': 'commercial.florist',
    'florist': 'commercial.florist',
    'game': 'commercial.elektronics,entertainment.video_arcade,commercial',
    'gaming': 'commercial.elektronics,entertainment.video_arcade,commercial',
    'video game': 'commercial.elektronics,entertainment.video_arcade,commercial',
    'book': 'commercial.books',
    'library': 'education.library',
    'school': 'education.school',
    'college': 'education.university,education.college',
    'university': 'education.university',
    'bus': 'public_transport.bus',
    'metro': 'public_transport.subway',
    'subway': 'public_transport.subway',
    'train': 'public_transport.train',
    'railway': 'public_transport.train',
    'airport': 'airport',
}

_STOPWORDS = {
    'near', 'me', 'nearby', 'closest', 'nearest', 'find', 'show', 'locate',
    'where', 'is', 'are', 'the', 'a', 'an', 'in', 'around', 'for', 'best',
    'good', 'some', 'any', 'places', 'place', 'shops', 'shop', 'store', 'stores',
    'center', 'centre', 'station', 'stations', 'please', 'can', 'you', 'get'
}


def category_for(text: str) -> str:
    lowered = text.lower().strip()
    for term, category in sorted(CATEGORIES.items(), key=lambda pair: -len(pair[0])):
        if term in lowered:
            return category
    return 'commercial,service,amenity'


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'[a-z0-9]+', text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


async def _query_geoapify_places(lat: float, lon: float, categories: str, radius: int, limit: int, name_filter: str = '') -> list[dict]:
    params: dict[str, Any] = {
        'categories': categories,
        'filter': f'circle:{lon},{lat},{radius}',
        'bias': f'proximity:{lon},{lat}',
        'limit': min(limit, 50),
        'apiKey': key('GEOAPIFY_API_KEY')
    }
    if name_filter:
        params['name'] = name_filter
    obj = await fetch_json(f'{GEO_BASE}/v2/places', params, provider='Geoapify')
    entries = []
    for feature in obj.get('features', []):
        p = feature.get('properties', {})
        coords = feature.get('geometry', {}).get('coordinates', [])
        if len(coords) < 2:
            continue
        name = p.get('name') or p.get('address_line1') or 'Unnamed location'
        distance = haversine(lat, lon, coords[1], coords[0])
        entries.append({
            'id': p.get('place_id') or f"{coords[1]:.5f},{coords[0]:.5f}",
            'name': name,
            'lat': coords[1],
            'lon': coords[0],
            'address': p.get('formatted') or p.get('address_line2') or '',
            'distance_m': round(distance),
            'category': categories,
            'website': p.get('website') if isinstance(p.get('website'), str) else ''
        })
    return entries


async def places(lat: float, lon: float, category: str, radius: int = 5000, limit: int = 15, keyword: str = '') -> list[dict]:
    resolved = category_for(category or keyword)
    search_text = f"{category} {keyword}".strip()
    words = _extract_keywords(search_text)

    # 1. Primary category search within radius
    entries = await _query_geoapify_places(lat, lon, resolved, radius, limit=30)

    # 2. Secondary name-based search for specific queries (e.g. "laptop", "repair", "thana", "ramen")
    specific_terms = [w for w in words if w not in {'hospital', 'police', 'restaurant', 'cafe', 'hotel', 'park', 'bank', 'atm', 'pharmacy', 'mall'}]
    if specific_terms:
        for term in specific_terms[:2]:
            try:
                named = await _query_geoapify_places(
                    lat, lon, 'commercial,service,healthcare,catering,amenity',
                    max(radius, 8000), limit=20, name_filter=term
                )
                seen_ids = {e['id'] for e in entries}
                for item in named:
                    if item['id'] not in seen_ids:
                        entries.append(item)
                        seen_ids.add(item['id'])
            except ProviderError:
                pass

    # 3. Auto-expand radius up to 15 km if fewer than 3 results were found locally
    if len(entries) < 3 and radius < 15000:
        try:
            wider = await _query_geoapify_places(lat, lon, resolved, 15000, limit=25)
            seen_ids = {e['id'] for e in entries}
            for item in wider:
                if item['id'] not in seen_ids:
                    entries.append(item)
                    seen_ids.add(item['id'])
        except ProviderError:
            pass

    if words:
        entries.sort(key=lambda p: (
            not any(w in (p['name'] + ' ' + p['address']).lower() for w in words),
            p['distance_m']
        ))
    else:
        entries.sort(key=lambda p: p['distance_m'])

    return entries[:limit]


def haversine(lat1, lon1, lat2, lon2):
    rad = math.pi / 180
    a = math.sin((lat2-lat1)*rad/2)**2 + math.cos(lat1*rad)*math.cos(lat2*rad)*math.sin((lon2-lon1)*rad/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(a)))


async def route(start: tuple[float,float], end: tuple[float,float], mode: str = 'drive') -> dict:
    mode = mode if mode in {'drive', 'walk', 'bicycle'} else 'drive'
    if haversine(*start, *end) < 15:
        raise ProviderError('Routing', 'Your starting point and destination are almost identical. Choose two different locations.', 422)
    try:
        obj = await fetch_json(f'{GEO_BASE}/v1/routing', {
            'waypoints': f'{start[0]},{start[1]}|{end[0]},{end[1]}',
            'mode': mode, 'format': 'geojson', 'details': 'instruction_details',
            'apiKey': key('GEOAPIFY_API_KEY')
        }, provider='Geoapify')
    except ProviderError as exc:
        if exc.status == 400 and ('no suitable edges' in str(exc).lower() or 'no path could be found' in str(exc).lower()):
            raise ProviderError('Routing',
                'A starting point or destination is not connected to a usable road for this travel mode. '
                'Choose a more precise street address or place a starting pin on a nearby road. '
                'Try walking if driving access is restricted.', 422) from exc
        raise
    features = obj.get('features', [])
    if not features:
        raise ProviderError('Geoapify', 'No route found for these locations.', 404)
    feature = features[0]
    p = feature.get('properties', {})
    legs = p.get('legs', [])
    steps = []
    for leg in legs:
        for step in leg.get('steps', []):
            instruction = step.get('instruction', {})
            if isinstance(instruction, dict):
                instruction = instruction.get('text', '')
            if instruction:
                steps.append(str(instruction))
    return {'distance_m': round(p.get('distance', sum(x.get('distance',0) for x in legs))),
            'duration_s': round(p.get('time', sum(x.get('time',0) for x in legs))),
            'mode': mode, 'geometry': feature.get('geometry'), 'steps': steps[:25]}


MODEL_PREFERENCES = (
    'gemini-3.5-flash-lite',
    'gemini-4-hydrogen',
    'gemini-3.8-flash',
    'gemini-3.6-flash',
    'gemini-2.5-flash-lite',
    'gemini-2.5-flash',
)
_active_model: str | None = None
_models_cache: tuple[float, list[str]] | None = None
_model_cooldowns: dict[str, float] = {}
RETRY_DELAY_SECONDS = 0.7


def configured(name: str) -> bool:
    val = os.getenv(name, '').strip()
    return bool(val and not val.lower().startswith(('your_', 'paste_', 'replace_', 'example_', '<')))


async def list_gemini_models() -> list[str]:
    global _models_cache
    if _models_cache and time.monotonic() - _models_cache[0] < 600:
        return list(_models_cache[1])
    models = []
    page_token = None
    for _ in range(4):
        params: dict[str, Any] = {'pageSize': 100}
        if page_token:
            params['pageToken'] = page_token
        data = await fetch_json(f'{GEMINI_BASE}/models',
            params=params, headers={'x-goog-api-key': key('GEMINI_API_KEY')}, provider='Gemini')
        models.extend(m['name'].removeprefix('models/') for m in data.get('models', [])
                      if 'generateContent' in m.get('supportedGenerationMethods', []))
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    _models_cache = (time.monotonic(), models)
    return list(models)


def _candidate_models(available: list[str]) -> list[str]:
    requested = os.getenv('GEMINI_MODEL', 'auto').strip().removeprefix('models/')
    preferred = [requested] if requested and requested.lower() != 'auto' else []
    preferred += list(MODEL_PREFERENCES)
    suitable = [m for m in available if ('flash' in m or 'hydrogen' in m)
                and not any(x in m for x in ('image','audio','live','tts','embedding','computer'))]
    preferred += sorted(suitable)
    return list(dict.fromkeys(m for m in preferred if m in available or m == requested))


async def _generate(model: str, prompt: str, structured: bool) -> str:
    config: dict[str, Any] = {'maxOutputTokens': 8192}
    if structured:
        config['responseMimeType'] = 'application/json'
    obj = await fetch_json(f'{GEMINI_BASE}/models/{model}:generateContent',
        headers={'x-goog-api-key': key('GEMINI_API_KEY')}, provider='Gemini', payload={
            'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': config})
    candidates = obj.get('candidates', [])
    if not candidates:
        reason = obj.get('promptFeedback', {}).get('blockReason')
        raise ProviderError('Gemini', f'No response generated ({reason or "empty response"}).', 422)
    chunks = candidates[0].get('content', {}).get('parts', [])
    output = '\n'.join(x.get('text', '') for x in chunks if x.get('text')).strip()
    if not output:
        reason = candidates[0].get('finishReason') or 'empty response'
        raise ProviderError('Gemini', f'No readable text returned ({reason}).', 422)
    return output


async def _generate_with_short_retry(model: str, prompt: str, structured: bool) -> str:
    try:
        return await _generate(model, prompt, structured)
    except ProviderError as exc:
        if exc.status not in (408, 500, 502, 503, 504):
            raise
        await asyncio.sleep(RETRY_DELAY_SECONDS * random.uniform(0.8, 1.2))
        return await _generate(model, prompt, structured)


async def gemini(prompt: str, structured: bool = False) -> str:
    global _active_model
    key('GEMINI_API_KEY')
    available = await list_gemini_models()
    if not available:
        raise ProviderError('Gemini', 'No generateContent models were listed for this API key.', 404)

    models = _candidate_models(available)
    if _active_model in models:
        models = [_active_model] + [m for m in models if m != _active_model]
    attempted = []
    failures: list[ProviderError] = []
    skipped = 0

    for model in models[:7]:
        if time.monotonic() < _model_cooldowns.get(model, 0):
            skipped += 1
            continue
        try:
            result = await _generate_with_short_retry(model, prompt, structured)
            _active_model = model
            _model_cooldowns.pop(model, None)
            return result
        except ProviderError as exc:
            failures.append(exc)
            attempted.append(f'{model}: HTTP {exc.status}')
            if exc.status == 401:
                raise
            if exc.status in (408, 500, 502, 503, 504):
                _model_cooldowns[model] = time.monotonic() + 45
            elif exc.status == 429:
                _model_cooldowns[model] = time.monotonic() + 120
            elif exc.status in (400, 403, 404, 422):
                _model_cooldowns[model] = time.monotonic() + 90
            else:
                raise
            if _active_model == model:
                _active_model = None

    if failures:
        last = failures[-1]
        if all(x.status in (408, 429, 500, 502, 503, 504) for x in failures):
            reason = ('Gemini is temporarily overloaded or rate-limited. '
                      'Tried alternative Flash models (' + ', '.join(attempted) + '). '
                      'Try again later; nearby places and map-based itineraries remain available.')
        else:
            reason = ('No Gemini model accepted the request. Checked '
                      + ', '.join(attempted[:5]) + '. Last error: ' + str(last)[:240])
        raise ProviderError('Gemini', reason, last.status)
    if skipped:
        raise ProviderError('Gemini',
            'Gemini models were recently overloaded or rate-limited. They are in a short '
            'cooldown to avoid repeated failed requests. Try again shortly.', 503)
    raise ProviderError('Gemini',
        'No accessible Flash text model is available. Check Google AI Studio project access.', 503)


async def ai_status(probe: bool = False) -> dict:
    if not configured('GEMINI_API_KEY'):
        return {'available': False, 'configured': False, 'model': None,
                'detail': 'GEMINI_API_KEY is missing or still a placeholder in .env.'}
    if not probe:
        return {'available': bool(_active_model), 'configured': True, 'model': _active_model,
                'detail': 'AI has not been tested yet.' if not _active_model else 'Gemini connection verified.'}
    try:
        await gemini('Reply with the word READY.')
        return {'available': True, 'configured': True, 'model': _active_model,
                'detail': 'Gemini generated a successful test response.'}
    except ProviderError as exc:
        return {'available': False, 'configured': True, 'model': None,
                'status_code': exc.status, 'detail': str(exc)}


async def classify(message: str, origin_label: str = '') -> dict[str, Any]:
    loc_hint = f'User current location: {origin_label}. ' if origin_label else ''
    prompt = (
        'Identify the intent of this location/travel request. Return ONLY a JSON object with keys:\n'
        '"intent": one of ["nearby", "route", "trip", "chat"],\n'
        '"category": short noun describing desired type of place (e.g. hospital, police station, laptop repair, ramen restaurant, flower shop),\n'
        '"origin": explicit city/area/landmark mentioned in the message as the search center (e.g. "Kolkata", "New Town", "Salt Lake"), otherwise empty string "". Do NOT put "me" or "my location" here,\n'
        '"destination": place/address mentioned as route or trip destination, otherwise empty string,\n'
        '"days": integer 1-14 (default 3), "budget": number in INR or 0, "travelers": integer 1-20 (default 1).\n'
        f'{loc_hint}If the user asks for any place/service (like "hospitals", "police station", "laptop repair shop", "cafes") without a specific city, set intent to "nearby" and leave "origin" as "". '
        'Text: ' + json.dumps(message)
    )
    raw = await gemini(prompt, structured=True)
    try:
        data = json.loads(raw)
        if data.get('intent') not in {'nearby','route','trip','chat'}:
            raise ValueError('unknown intent')
        return data
    except (ValueError, TypeError):
        raise ProviderError('Gemini', 'Gemini produced an unrecognized intent response.')


def heuristic(message: str) -> dict:
    msg = message.lower().strip()
    if any(x in msg for x in ['itinerary', 'trip to ', 'travel plan', 'day tour', 'days in ', 'tour for']):
        m = re.search(r'(\d+)\s*[- ]?day', msg)
        return {'intent': 'trip', 'days': int(m.group(1)) if m else 3, 'destination': '', 'category': '', 'origin': ''}
    if any(x in msg for x in ['route to', 'directions to', 'how do i get', 'navigate to', 'get to ']):
        return {'intent': 'route', 'destination': '', 'category': '', 'origin': ''}

    explicit_origin = ''
    m_loc = re.search(r'\b(?:near|in|around|at)\s+(?!me\b|my\b|here\b)([a-zA-Z0-9\s,.-]{2,60})$', message, flags=re.I)
    if m_loc:
        explicit_origin = m_loc.group(1).strip(' ?.')

    cleaned = re.sub(r'\b(?:near|in|around|at)\s+.+$', '', msg, flags=re.I).strip(' ?.')
    for term in sorted(CATEGORIES.keys(), key=len, reverse=True):
        if term in cleaned:
            return {'intent': 'nearby', 'category': cleaned, 'origin': explicit_origin, 'destination': ''}

    if any(x in msg for x in ['near', 'closest', 'nearest', 'nearby', 'find ', 'where is', 'search for', 'locate ']):
        category = re.sub(r'\b(find|search for|locate|nearby|near me|nearest|closest|best|some|places|around|in|my location)\b', ' ', cleaned).strip()
        return {'intent': 'nearby', 'category': category or 'restaurant', 'origin': explicit_origin, 'destination': ''}

    return {'intent': 'chat'}


async def mapped_itinerary(destination: str, days: int, budget: float, travelers: int, interests: str,
                           ai_error: str = '') -> dict:
    matches = await geocode(destination)
    if not matches:
        raise ProviderError('Geoapify', f'Could not locate {destination}. Try a more specific city.', 404)
    center = matches[0]
    suggestions: list[dict] = []
    seen = set()
    for category in ('attraction', 'museum', 'park'):
        try:
            batch = await places(center['lat'], center['lon'], category, radius=30000, limit=30)
        except ProviderError:
            continue
        for place in batch:
            if place['id'] in seen or place['name'] == 'Unnamed location':
                continue
            seen.add(place['id'])
            suggestions.append(place)
    suggestions.sort(key=lambda p: p.get('distance_m', 0))
    plan = []
    chunk = max(1, min(4, math.ceil(len(suggestions) / max(1, days))))
    for day in range(1, days + 1):
        current = suggestions[(day-1)*chunk:day*chunk]
        stops = [{'name': p['name'], 'description': (p.get('address') or 'Mapped point of interest')
                  + ' · listed on Geoapify (hours not verified)',
                  'lat': p['lat'], 'lon': p['lon']} for p in current]
        plan.append({'day': day, 'title': f'Explore {center.get("city") or destination} · Day {day}',
                     'stops': stops})
    warning = ('Gemini is unavailable, so this is a basic, map-sourced outline, not an AI-optimized tour. '
               'Attractions were searched within 30 km of one geocoded location. '
               'For large states such as Maharashtra, search a specific city for better results.')
    if not suggestions:
        warning += ' No mapped attractions were found around the geocoded center.'
    if ai_error:
        warning += ' Gemini issue: ' + ai_error[:220]
    return {'title': f'{days}-day {destination} plan',
            'overview': f'Mapped attractions around {center["name"]}. {warning}',
            'budget_note': f'Budget target: ₹{budget:,.0f} for {travelers} traveler(s). No prices or bookings verified.'
                           if budget else 'No prices or bookings have been verified.',
            'days': plan, 'source': 'mapped', 'ai_available': False, 'center': center,
            'notice': warning, 'places': suggestions}

def _repair_truncated_json(raw: str) -> dict[str, Any] | None:
    text = _strip_json_fences(raw).strip()
    if not text:
        return None
    # Close an unclosed string literal at the end if needed
    quote_count = 0
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == '\\':
            escaped = True
        elif ch == '"':
            quote_count += 1
    if quote_count % 2 == 1:
        text += '"'
    # Trim any trailing dangling comma or colon before closing brackets/braces
    text = re.sub(r'[,:]\s*$', '', text)
    open_brackets = text.count('[') - text.count(']')
    open_braces = text.count('{') - text.count('}')
    text += (']' * max(0, open_brackets)) + ('}' * max(0, open_braces))
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) and isinstance(parsed.get('days'), list) else None
    except ValueError:
        return None


async def itinerary(destination: str, days: int, budget: float, travelers: int, interests: str) -> dict:
    prompt = f"""You are Wayfinder AI. Create a plausible {days}-day travel plan for {destination}.
Travelers: {travelers}; total budget INR {budget if budget else 'unspecified'}; interests: {interests or 'general sightseeing'}.
Return ONLY a JSON object with keys "title", "overview", "budget_note", "days".
"days" must contain exactly {days} objects: {{"day": integer, "title": string,
"stops": [{{"name": string, "description": string}}]}}.
Be realistic about journey times. Places are suggestions, not verified business listings.
Don't claim verified hours, prices, or transport availability."""
    try:
        raw = await gemini(prompt, structured=True)
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = _repair_truncated_json(raw)
        if not isinstance(obj, dict) or not isinstance(obj.get('days'), list):
            raise ValueError('not an itinerary object')
        obj['source'] = 'gemini'
        obj['ai_available'] = True
        return obj
    except (ProviderError, ValueError, TypeError) as exc:
        return await mapped_itinerary(destination, days, budget, travelers, interests, str(exc))