@echo off
REM MarketPulse launcher (Windows) — double-click to run.
cd /d "%~dp0"
echo Starting MarketPulse...
REM Tells licensing this is the buyer's own computer (it may keep a local signing secret).
set MP_LICENSE_LOCAL=1
start "" http://127.0.0.1:8000/app
python app.py
pause
