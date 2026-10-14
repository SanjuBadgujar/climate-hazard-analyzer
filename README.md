# Climate Hazard Trend Analyzer (Heatwave)

React + FastAPI + MongoDB app that analyses historical daily maximum temperature for a region
and reports heatwave frequency, duration and trend, with an honest statistical summary.

**Live app:** `<add Vercel URL>` | **API:** `<add Render URL>/docs`

## Architecture

```
React (Vite, Chart.js, Leaflet)  --GET-->  FastAPI  --reads/writes-->  MongoDB
                                              |  (only on cache miss)
                                              +--> Open-Meteo Archive API (ERA5)
```

| Layer | File | Responsibility |
|---|---|---|
| API | `backend/app/main.py` | routes, CORS, rate limiting, error mapping |
| Validation | `backend/app/schemas.py` | bounds on lat/lon/box/years/percentile |
| Ingestion | `backend/app/ingest.py` | fetch from Open-Meteo, retry, snap to grid, store per (cell, year) |
| Logic | `backend/app/processing.py` | cleaning, percentile thresholds, event detection, trends, insights (pure functions) |
| Orchestration | `backend/app/service.py` | analysis-cache lookup -> ingest -> read from DB -> analyse -> cache |
| Storage | `backend/app/db.py` | MongoDB (`raw_daily`, `analysis` collections) |

**MongoDB collections**
- `raw_daily`: one doc per `(region_key, year)` with `dates[]`, `tmax[]` (null = gap), source, fetched_at.
- `analysis`: computed result keyed by SHA-256 of region + period + params + algorithm version; TTL index expires it.

**Flow:** `GET /api/heatwave` -> cached analysis? return (`X-Cache: HIT`). Otherwise fetch only missing years,
store them, read the series back **from MongoDB**, analyse, store the result, return JSON.

## API

| Endpoint | Description |
|---|---|
| `GET /api/heatwave?lat&lon&start_year&end_year[&percentile=95&min_days=3&min_tmax_c=40]` | analysis JSON (`min_tmax_c` = optional absolute floor) |
| `GET /api/heatwave?min_lat&max_lat&min_lon&max_lon&...` | same, for a box (max 5 deg per side; centre cell analysed) |
| `GET /api/heatwave/export.csv?...` | yearly table as CSV |
| `GET /api/geocode?q=Pune` | city/state search (Open-Meteo geocoding) |
| `GET /api/health` | liveness |

## Setup

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # set MONGO_URI (Atlas free tier); empty = in-memory dev DB
export $(grep -v '^#' .env | xargs)                   # or set vars your own way
uvicorn app.main:app --reload                         # http://localhost:8000/docs
pytest                                                # 10 tests, no network needed

# frontend
cd ../frontend
cp .env.example .env        # VITE_API_URL=http://localhost:8000
npm install
npm run dev                 # http://localhost:5173
```

**Deploy:** backend -> Render (Docker, root dir `backend`; env: `MONGO_URI`, `CORS_ORIGINS=<frontend url>`);
frontend -> Vercel (root dir `frontend`; env: `VITE_API_URL=<backend url>`).

## Data source
Open-Meteo Historical Weather API, `models=era5` (ECMWF ERA5 reanalysis, ~25 km, 1950+), variable
`temperature_2m_max`, `temperature_unit=celsius`. Free, no key. A single reanalysis model is requested on purpose
so the series is homogeneous (no blending of different models over time).

## Hazard logic
1. Clean: reindex to a full daily calendar; remove physically impossible values (<-60 or >60 C);
   linearly interpolate gaps of <=2 days only; longer gaps stay missing and break heatwave runs.
2. Threshold: for each calendar day, the 95th percentile of Tmax pooled over +-7 days across all years
   (15 x N samples) - a day-specific threshold, so winter days are not compared with summer ones.
3. Event: >= 3 consecutive days with Tmax strictly above that day's threshold.
4. Per year: number of events, heatwave days, longest event, mean excess over threshold.
5. Trend: OLS slope (per decade), **Mann-Kendall** test with tie correction, **Theil-Sen** slope,
   5-year centred rolling mean.
6. Insight text compares first vs last 10 years, quotes the % change only when the baseline is non-zero,
   and states plainly when the trend is **not** statistically significant.

## Security and performance
- Pydantic validation on every parameter (ranges, max 40-year span, min 10 years, box <= 5 deg).
- No user input in URLs/paths of upstream calls; fixed upstream hosts; timeouts + retries with backoff.
- Rate limiting (slowapi): 10/min on analysis endpoints, 30/min geocode, 60/min default.
- CORS restricted to configured origins, GET only.
- Coordinates snapped to the 0.25 deg grid -> bounded cache keys, higher hit rate.
- Per-cell lock prevents duplicate upstream fetches under concurrency; only missing years are fetched.
- Analysis cache with TTL; geocode results in an LRU cache.

## Assumptions
- Threshold baseline = the selected period (the brief says "95th percentile for that region"). Consequence:
  ~5% of days exceed by construction, so trends measure change *within* the window.
- The brief's definition is relative (95th percentile per calendar day), so it also flags unusually warm days in cooler
  seasons (e.g. a 29 C August day in Pune). An optional absolute minimum Tmax filter (35/40 C) is provided; the default
  follows the brief. Trends describe change in *relatively* extreme heat, not officially declared heatwaves.
- A bounding box is represented by its centre grid cell (no area averaging).
- Reanalysis is not station data; urban heat islands and local effects are smoothed out.
- Events are assigned to the calendar year in which they start.
- The end year is capped at the last complete calendar year.

## What I would improve with more time
- Fixed WMO-style baseline (e.g. 1991-2020) as an option, and an excess-heat-factor definition.
- Area-average over several grid cells for boxes; humidity-aware (heat index) heatwaves.
- Precompute popular cities in a background job; Redis for rate-limit state across instances.
- Drought (SPI) and heavy-rain (R95p) hazards on the same pipeline; PDF export; map choropleth.
- Frontend tests and an e2e smoke test.

## AI tools used and how

> - Claude: drafted the architecture, the detection/trend functions and the tests; I reviewed every function,
>   ran the tests, and can explain and modify each part.
