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

Quick run (local)

```bash
# install deps (pipenv / pip / poetry as you prefer)
pip install fastapi uvicorn requests python-dotenv
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Quick run (Docker)

```bash
docker build -t strava-api .
# use an env file or pass envs directly
docker run --env-file .env -p 8000:8000 strava-api
```

Open the app: http://localhost:8000/index.html

Tests

```bash
pip install pytest
pytest
```

Notes
- The app logs a warning at startup if required STRAVA env vars are missing.
- Static files are served from the `frontend/` directory; API routes are available on the same host/port.
