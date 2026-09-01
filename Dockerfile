FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn aiofiles requests python-dotenv

COPY main.py ./
COPY frontend ./frontend

ENV STRAVA_CACHE_PATH=/data/strava_cache.json
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
