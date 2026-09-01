#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly IMAGE_NAME="strava-api"
readonly CONTAINER_NAME="strava-api"

cd "$SCRIPT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing $SCRIPT_DIR/.env" >&2
  exit 1
fi

mkdir -p data

if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "Removing existing $CONTAINER_NAME container..."
  docker rm --force "$CONTAINER_NAME"
fi

echo "Rebuilding $IMAGE_NAME with the latest base image..."
docker build --pull --no-cache --tag "$IMAGE_NAME" .

echo "Starting $CONTAINER_NAME on http://localhost:8000..."
docker run \
  --detach \
  --name "$CONTAINER_NAME" \
  --env-file .env \
  --publish 8000:8000 \
  --mount "type=bind,source=$SCRIPT_DIR/data,target=/data" \
  "$IMAGE_NAME"

echo "Container status:"
docker ps --filter "name=^/${CONTAINER_NAME}$"
