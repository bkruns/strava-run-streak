# Strava Runs Streak Dashboard

Small FastAPI + static frontend app that fetches Strava activities and computes run-streak and weekly stats. The frontend (simple HTML/JS) is served from the `frontend/` folder.

Features
- OAuth flow to authenticate with Strava (`/login` and `/callback`).
- Endpoints to fetch activities and compute stats such as run streak, weekly summaries, and outdoor temperatures.
- Static frontend at `/index.html` that shows a dashboard.

Requirements
- Python 3.11+ (dev uses 3.13 in the Pipfile)
- Docker (optional)

Environment
Set the following environment variables (do not store secrets in repo):
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REDIRECT_URI` (e.g. `http://localhost:8000/callback`)
- `STRAVA_CACHE_PATH` (optional; defaults to `strava_cache.json`)

Activity and weather responses are cached locally in JSON. The current day and
previous four calendar days are refreshed on every request; older dates are read
from the cache once that date (including an empty date) has been stored. Each
activity scan also fetches and stores weather for outdoor activities that include
location coordinates. Each scan writes an INFO log entry listing cached dates,
dates that need to be pulled, missing dates, and recent dates being refreshed.
Newly downloaded runs are also enriched with a `pace_data` object containing
average pace/speed values and timestamped pace-stream samples. Pace enrichment
errors are logged without preventing the activity summary from being cached.

Quick run (local)

```bash
# install deps (pipenv / pip / poetry as you prefer)
pip install fastapi uvicorn requests python-dotenv
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Quick run (Docker)

```bash
docker build -t strava-api .
mkdir -p data
docker run --env-file .env \
  -p 8000:8000 \
  --mount type=bind,source="$(pwd)/data",target=/data \
  strava-api
```

Inside Docker, the cache defaults to `/data/strava_cache.json`. The bind mount
maps `/data` to the local `data/` directory, so the cache survives container
replacement and remains directly readable from the host at
`data/strava_cache.json`. Mount the directory rather than the individual file,
because cache updates use an atomic temporary-file replacement.

Open the app: http://localhost:8000/index.html

Tests

```bash
pip install pytest
pytest
```

Notes
- The app logs a warning at startup if required STRAVA env vars are missing.
- Static files are served from the `frontend/` directory; API routes are available on the same host/port.
