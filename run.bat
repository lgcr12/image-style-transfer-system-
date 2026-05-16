@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creating virtual environment...
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo [setup] Installing dependencies...
python -m pip install -r requirements.txt

echo [run] Starting AetherCanvas on http://127.0.0.1:8001
python -m uvicorn app:app --host 127.0.0.1 --port 8001
