#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[setup] Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "[setup] Installing dependencies..."
python -m pip install -r requirements.txt

echo "[run] Starting AetherCanvas on http://127.0.0.1:8001"
python -m uvicorn app:app --host 127.0.0.1 --port 8001
