#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  echo "[ERROR] .venv not found. Run WSL setup first."
  exit 1
fi

source .venv/bin/activate
exec uvicorn main:app --app-dir apps/slack-bot --host 0.0.0.0 --port 8000 --reload
