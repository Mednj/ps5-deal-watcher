#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  umask 077
  cp .env.example .env
fi
docker compose build
docker compose run --rm --no-deps web python -m scripts.migrate
docker compose up -d
docker compose ps
