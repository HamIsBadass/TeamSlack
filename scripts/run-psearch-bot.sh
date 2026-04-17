#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Prefer home-based venv (WSL-safe), fallback to repo .venv.
if [ -f "$HOME/teamslack-venv/bin/activate" ]; then
  source "$HOME/teamslack-venv/bin/activate"
elif [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
else
  echo "[ERROR] No virtual environment found."
  echo "Create one first (e.g., ~/teamslack-venv)."
  exit 1
fi

exec python apps/slack-bot/socket_mode_runner.py
