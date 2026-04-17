#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  echo "[ERROR] .venv not found. Run WSL setup first."
  exit 1
fi

source .venv/bin/activate
exec celery -A services.orchestrator.tasks.celery_app worker --loglevel=info
