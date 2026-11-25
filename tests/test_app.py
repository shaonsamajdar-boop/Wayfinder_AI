import os
os.environ['GEOAPIFY_API_KEY']='mock-geo'
os.environ['GEMINI_API_KEY']='mock-gemini'
from fastapi.testclient import TestClient
import app
import services
import pytest

client=TestClient(app.app)

def test_frontpage():
    r=client.get('/')
    assert r.status_code==200 and 'wayfinder' in r.text.lower()

def test_health():
    assert client.get('/api/health').json()['ok'] is True

def test_geocode_empty():
    assert client.get('/api/geocode',params={'q':''}).status_code==400

def test_invalid_radius():
    assert client.post('/api/places',json={'lat':22.5,'lon':88.4,'radius':80000}).status_code==422

def test_category_mapping():
    assert services.category_for('ramen restaurant')=='catering.restaurant'
    assert services.category_for('flower shop')=='commercial.florist'

def test_heuristic():
    assert services.heuristic('cafes near me')['intent']=='nearby'
    assert services.heuristic('plan a 5-day trip to Goa')['days']==5


def test_chat_fallback(monkeypatch):
    async def bad(*args,**kwargs):raise services.ProviderError('Gemini','test failure')
    async def mapped(*args,**kwargs):return [{'name':'Cafe One','lat':22.5,'lon':88.4,'address':'Test Road','distance_m':120}]
    monkeypatch.setattr(services,'classify',bad)
    monkeypatch.setattr(services,'places',mapped)
    r=client.post('/api/chat',json={'message':'cafes nearby','origin':{'lat':22.5,'lon':88.4}})
    assert r.status_code==200
    assert r.json()['kind']=='places'
    assert r.json()['ai_available'] is False


def test_places_endpoint(monkeypatch):
    async def mapped(*a,**kw):return [{'name':'A'}]
    monkeypatch.setattr(services,'places',mapped)
    assert client.post('/api/places',json={'lat':22.5,'lon':88.4,'category':'cafe'}).json()['results'][0]['name']=='A'


def test_route_endpoint(monkeypatch):
    async def route(*a,**kw):return {'distance_m':1000,'duration_s':600,'geometry':None,'steps':[]}
    monkeypatch.setattr(services,'route',route)
    r=client.post('/api/route',json={'start':{'lat':22,'lon':88},'end':{'lat':23,'lon':88},'mode':'walk'})
    assert r.status_code==200 and r.json()['duration_s']==600


def test_trip_endpoint(monkeypatch):
    async def trip(*a,**kw):return {'title':'Goa','days':[{'day':1,'stops':[]}]}
    monkeypatch.setattr(services,'itinerary',trip)
    assert client.post('/api/trip',json={'destination':'Goa','days':1}).json()['title']=='Goa'


def test_route_waypoint_coordinate_order_and_mode(monkeypatch):
    observed = {}
    async def fake_fetch(url, params=None, **kwargs):
        observed.update(params)
        return {'features':[{'geometry': {'type':'MultiLineString','coordinates': [[[88.46,22.57],[88.47,22.58]]]}, 'properties':{'distance': 1250,'time': 400,'legs':[]}}]}
    monkeypatch.setattr(services, 'fetch_json', fake_fetch)
    route = __import__('asyncio').run(services.route((22.57,88.46), (22.58,88.47), 'drive'))
    assert observed['waypoints'] == '22.57,88.46|22.58,88.47'
    assert observed['format'] == 'geojson'
    assert route['distance_m'] == 1250


def test_unreachable_point_shows_actionable_error(monkeypatch):
    async def fake_fetch(url, params=None, **kwargs):
        raise services.ProviderError('Geoapify', 'No suitable edges near location. Please check waypoint coordinate order (lat/lon).', 400)
    monkeypatch.setattr(services, 'fetch_json', fake_fetch)
    r = client.post('/api/route', json={'start':{'lat':22.57,'lon':88.46}, 'end':{'lat':22.60,'lon':88.48}, 'mode':'drive'})
    assert r.status_code == 422
    assert 'street address' in r.json()['detail']
    assert 'No suitable edges' not in r.text


def test_geocoder_returns_multiple_distinct_matches(monkeypatch):
    async def fake_fetch(url, params=None, **kwargs):
        return {'results': [{'formatted':'Campus A','lat':22.6,'lon':88.46,'result_type':'amenity'},
                            {'formatted':'Campus A repeated','lat':22.6,'lon':88.46},
                            {'formatted':'Campus B','lat':22.605,'lon':88.48,'result_type':'street'}]}
    monkeypatch.setattr(services, 'fetch_json', fake_fetch)
    r = client.get('/api/geocode',params={'q':'UEM Kolkata'})
    assert r.status_code == 200
    assert len(r.json()['results']) == 2
    assert r.json()['results'][1]['result_type'] == 'street'


def test_dedicated_chat_ui():
    page = client.get('/').text
    assert 'assistant-fab' in page
    assert 'assistant-drawer' in page
    assert 'assistant-form' in page


def test_ai_status_missing_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY')
    response = client.get('/api/ai/status?probe=true')
    assert response.status_code == 200
    assert response.json()['available'] is False
    assert 'missing' in response.json()['detail'].lower()


def test_ai_status_success(monkeypatch):
    async def fake_gemini(prompt, structured=False):
        services._active_model = 'gemini-3.8-flash'
        return 'READY'
    monkeypatch.setattr(services, 'gemini', fake_gemini)
    response = client.get('/api/ai/status?probe=true')
    assert response.status_code == 200
    assert response.json()['available'] is True
    assert response.json()['model'] == 'gemini-3.8-flash'


def test_direct_assistant_with_history(monkeypatch):
    got = {}
    async def fake_gemini(prompt, structured=False):
        got['prompt'] = prompt
        return 'Try Victoria Memorial on a clear day.'
    monkeypatch.setattr(services, 'gemini', fake_gemini)
    r = client.post('/api/assistant', json={'message':'What about museums?',
       'history':[{'role':'user','content':'Suggest places in Kolkata'}, {'role':'assistant','content':'Try Park Street'}],
       'origin_label':'Kolkata'})
    assert r.status_code == 200
    assert 'Victoria' in r.json()['text']
    assert 'Park Street' in got['prompt']


def test_auto_model_tries_another_model_if_first_rejected(monkeypatch):
    import asyncio
    monkeypatch.setenv('GEMINI_MODEL', 'auto')
    services._active_model = None
    attempted = []
    async def models():
        return ['gemini-3.8-flash', 'gemini-3.6-flash']
    async def generate(model, prompt, structured):
        attempted.append(model)
        if model == 'gemini-3.8-flash':
            raise services.ProviderError('Gemini', 'not available', 404)
        return 'Hello!'
    monkeypatch.setattr(services, 'list_gemini_models', models)
    monkeypatch.setattr(services, '_generate', generate)
    assert asyncio.run(services.gemini('Hi')) == 'Hello!'
    assert attempted == ['gemini-3.8-flash', 'gemini-3.6-flash']
    services._active_model = None


def test_trip_planner_has_map_fallback_when_ai_fails(monkeypatch):
    async def blocked(*a, **kw):
        raise services.ProviderError('Gemini', 'free tier quota reached', 429)
    async def geocode(*a):
        return [{'name':'Kolkata, India','city':'Kolkata','lat':22.57,'lon':88.36}]
    async def places(*a, **kw):
        return [{'id':'heritage-1', 'name':'Museum One','address':'Central Kolkata',
                 'lat':22.57,'lon':88.37, 'distance_m':900}]
    monkeypatch.setattr(services, 'gemini', blocked)
    monkeypatch.setattr(services, 'geocode', geocode)
    monkeypatch.setattr(services, 'places', places)
    r = client.post('/api/trip', json={'destination':'Kolkata', 'days':2, 'budget':5000})
    assert r.status_code == 200
    data = r.json()
    assert data['source'] == 'mapped'
    assert data['ai_available'] is False
    assert len(data['days']) == 2
    assert data['days'][0]['stops'][0]['name'] == 'Museum One'
    assert 'Gemini' in data['notice']


def test_chat_trip_intent_works_without_ai(monkeypatch):
    async def blocked(*a, **kw):
        raise services.ProviderError('Gemini', 'invalid free tier', 403)
    async def trip(*a, **kw):
        return {'source':'mapped', 'days':[{'day':1,'stops':[]}]}
    monkeypatch.setattr(services, 'classify', blocked)
    monkeypatch.setattr(services, 'itinerary', trip)
    r = client.post('/api/chat', json={'message':'Plan a 1-day trip to Kolkata'})
    assert r.status_code == 200
    assert r.json()['kind']=='trip'
    assert r.json()['trip']['source']=='mapped'


def test_overloaded_cached_model_retries_then_fails_over(monkeypatch):
    import asyncio
    async def models():
        return ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    attempts=[]
    async def generate(model, prompt, structured):
        attempts.append(model)
        if model=='gemini-3.8-flash':
            raise services.ProviderError('Gemini', 'This model is currently experiencing high demand',503)
        return 'Hello from Flash-Lite'
    monkeypatch.setenv('GEMINI_MODEL','auto')
    monkeypatch.setattr(services,'list_gemini_models',models)
    monkeypatch.setattr(services,'_generate',generate)
    monkeypatch.setattr(services,'RETRY_DELAY_SECONDS',0)
    services._model_cooldowns.clear()
    services._active_model='gemini-3.8-flash'
    try:
        text=asyncio.run(services.gemini('hello'))
        assert text=='Hello from Flash-Lite'
        assert attempts==['gemini-3.8-flash','gemini-3.8-flash','gemini-3.5-flash-lite']
        assert services._active_model=='gemini-3.5-flash-lite'
    finally:
        services._active_model=None
        services._model_cooldowns.clear()


def test_persistent_overload_is_honest_and_uses_cooldown(monkeypatch):
    import asyncio
    async def models():return ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    attempts=[]
    async def generate(model, prompt, structured):
        attempts.append(model)
        raise services.ProviderError('Gemini', 'This model is currently experiencing high demand',503)
    monkeypatch.setenv('GEMINI_MODEL','auto')
    monkeypatch.setattr(services,'list_gemini_models',models)
    monkeypatch.setattr(services,'_generate',generate)
    monkeypatch.setattr(services,'RETRY_DELAY_SECONDS',0)
    services._active_model=None
    services._model_cooldowns.clear()
    try:
        with pytest.raises(services.ProviderError) as error:
            asyncio.run(services.gemini('hello'))
        assert error.value.status==503
        assert 'overloaded' in str(error.value)
        assert attempts==['gemini-3.5-flash-lite']*2+['gemini-3.8-flash']*2
        with pytest.raises(services.ProviderError) as cached:
            asyncio.run(services.gemini('hello again'))
        assert 'cooldown' in str(cached.value).lower()
        assert len(attempts)==4
    finally:
        services._active_model=None
        services._model_cooldowns.clear()


def test_bad_key_does_not_trigger_model_sweep(monkeypatch):
    import asyncio
    async def models():return ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    attempts=[]
    async def generate(model, prompt, structured):
        attempts.append(model)
        raise services.ProviderError('Gemini','Invalid API key',401)
    monkeypatch.setenv('GEMINI_MODEL','auto')
    monkeypatch.setattr(services,'list_gemini_models',models)
    monkeypatch.setattr(services,'_generate',generate)
    services._active_model=None
    services._model_cooldowns.clear()
    with pytest.raises(services.ProviderError) as error:
        asyncio.run(services.gemini('hi'))
    assert error.value.status==401
    assert attempts==['gemini-3.5-flash-lite']
