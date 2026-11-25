# Wayfinder AI — Gemini overload recovery (v4)

**New in v4:** HTTP 503 (model overloaded) no longer leaves the selected model stuck. The backend retries once after a short pause, fails over to another advertised Flash model, and temporarily avoids models that just failed. The default selection starts with Gemini 3.5 Flash-Lite for a responsive student-project experience. Model choice remains `GEMINI_MODEL=auto`. No extra API key is needed.

**Important:** A Gemini 503 is a Google-side capacity error, not necessarily a bad API key. No retry/fallback logic can guarantee success during sustained outages or after exhausting all account quotas. Map search, routes, and Geoapify-based trip outlines still work independently of Gemini.

**To upgrade:** Extract into a **new folder**. Copy your original `.env` (if you still have it) or let `run_windows.bat` create one and enter the Gemini and Geoapify keys. Stop the old server using Ctrl+C first. Double-click `run_windows.bat`, and visit http://127.0.0.1:8000 .

**How to verify:** Open the Ask AI chat bubble and select Retest. If that fails, run `diagnose_windows.bat`. Do not share your keys.

---

# Wayfinder AI — Premium Edition v4

A locally runnable, minimalist travel assistant with **Gemini + Geoapify**, a persistent **Ask AI** chat bubble, map-based nearby discovery, directions, and multi-day trip planning. The route error handling from the previous fix is retained. This is a college-project prototype, not a full navigation or booking system.

## 1. What is fixed

- **AI connection diagnosis:** the application now makes a short, real Gemini generation request on page load. The status area and floating AI chat show whether the model actually responds, instead of blindly displaying “AI offline.” The **Retest** button repeats the check.
- **Automatic Gemini model fallback:** set `GEMINI_MODEL=auto` and the backend discovers available text-generation models, tries supported Flash candidates and uses the first model that really generates a response. A model appearing in the list does **not** guarantee account access; Gemini free-tier limits and project restrictions still apply.
- **Chat bubble:** the persistent floating `Ask AI` button opens a conversational panel from any page. It calls `/api/assistant` and keeps recent messages in the current browser session. It is a *direct Gemini conversation*: it does not itself execute location queries. Use Discover/Nearby/Directions/Trips for mapped results.
- **Trip planner without Gemini:** `/api/trip` first attempts a Gemini itinerary. If Gemini fails, it geocodes the destination and creates a simple outline using actual mapped attractions/museums/parks from Geoapify (if that key works). A label clearly distinguishes this basic fallback from AI planning. Fallback searches are centered on one geocoded location within 30 km; they are **not** optimized regional itineraries.
- **Routing:** correct latitude/longitude order, choose ambiguous geocoding matches, set your starting point from the map, and get understandable route-connection errors.

## 2. Two API keys

- Get a **Gemini API key** from: https://aistudio.google.com/api-keys
- Get a **Geoapify API key** from: https://myprojects.geoapify.com/

Both have free-tier limitations and may require account/project configuration. Never paste the actual keys into a chat or commit them to Git.

## 3. Windows setup (Miniconda Python 3.13 supported)

1. Extract the ZIP into a new folder and **close any older Wayfinder AI server** running on port `8000` (press `Ctrl+C` in its Command Prompt).
2. Open the extracted `wayfinder_ai_gemini_premium_v4` project folder. Double-click **`run_windows.bat`**.
3. First run creates a new `.env` file (you don't need to bring back the deleted one) and opens Notepad. Paste the **actual** keys:

   ```dotenv
   GEMINI_API_KEY=your_actual_google_ai_studio_key
   GEOAPIFY_API_KEY=your_actual_geoapify_key
   GEMINI_MODEL=auto
   ```

   Remove the example phrases `your_actual_...` and use your own real keys. No quotation marks are required.
4. Save `.env`, close the launcher, then run **`run_windows.bat` again**.
5. Open **http://127.0.0.1:8000** if it does not open automatically. The **AI connected** indicator is shown only after a successful Gemini request.
6. If Gemini does not connect, double-click **`diagnose_windows.bat`**. It tests both providers and shows the real API error without printing the keys. The website may still work with Geoapify alone.

The launcher deliberately bypasses the broken Windows `py` launcher. It uses `C:\Users\ayush\miniconda3\python.exe` if installed, or `python` as a fallback. It recreates `.venv` if needed.

## 4. Manual setup (Windows CMD)

Run these commands inside the project folder:

```cmd
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe diagnose.py
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## 5. Features

| Feature | Data source | Can work without Gemini? |
|---|---|---|
| Floating direct AI conversation | Gemini | No |
| Discover chat (intent + map data) | Gemini + Geoapify | Basic nearby/route/trip requests |
| Nearby restaurants, florists, attractions | Geoapify Places | Yes |
| Driving, walking, cycling directions | Geoapify Routing | Yes |
| AI multi-day trip plan | Gemini | Falls back to Geoapify mapped attractions |
| Manual location / GPS (with permission) | Browser Geolocation, Geoapify | Yes |
| Interactive map | MapLibre + OpenFreeMap | Yes, internet required |

Geoapify does not guarantee verified restaurant menus, Google reviews, live traffic, booking fares or transit schedules. AI itineraries do not verify current operating hours or actual prices.

## 6. Common problems

**AI unavailable / no model works:** Click the connection indicator or **Ask AI → Retest**. It performs a real response test and reports the provider's reason. Then run `diagnose_windows.bat` for more detail. Check the actual Gemini key and project eligibility in Google AI Studio; Gemini free access varies by project, geography and quotas. `GEMINI_MODEL=auto` is recommended. A list of models alone cannot prove actual access.

**Map features broken:** Check Geoapify key, credit allowance and your internet connection. Open `http://127.0.0.1:8000/api/health` to see whether each key is configured (keys are not shown).

**Trip fallback only shows a few places:** Specify a city (such as `Pune, Maharashtra`) rather than a huge state. Offline/map-only planning searches nearby mapped attractions, not the entire state.

**Geoapify: no suitable edges near location:** The start or end is not connected to a road network for the selected travel mode. In Directions, choose a more precise location, select the correct geocoding match, place a starting pin along a road, or switch to walking.

**App does not load / wrong version loads:** Stop all old Command Prompt windows running Wayfinder, close and reopen `run_windows.bat`, and hard-refresh the browser with `Ctrl+Shift+R`. Only one app should occupy port `8000`.

## 7. API endpoints

- `GET /api/health` — reports configured services (never keys)
- `GET /api/ai/status?probe=true` — tests Gemini generation, reports working model or error
- `GET /api/models` — lists advertised text-generation models (does not prove generation access)
- `POST /api/assistant` — direct conversational AI
- `POST /api/chat` — discover chat, routing and trip intents
- `GET /api/geocode?q=...` — Geoapify geocoding
- `POST /api/places` — Geoapify nearby locations
- `POST /api/route` — Geoapify directions
- `POST /api/trip` — Gemini itinerary or mapped fallback

## 8. Tests

```cmd
.venv\Scripts\python.exe -m pytest -q
```

**20 automated backend tests passed** with mocked providers, plus a desktop/mobile static browser rendering check for the floating AI panel. Live Gemini and Geoapify requests **cannot be verified without your own API keys**; this package contains no user credentials.

## Privacy and terms

This is a student prototype. API keys remain server-side in `.env` and location permission is requested by the browser. The mapping and AI providers process the queries sent to them, subject to their privacy and service terms. Do not deploy open, unauthenticated endpoints at scale without adding abuse protections.

Official documentation: https://ai.google.dev/gemini-api/docs | https://www.geoapify.com/ | https://openfreemap.org/
