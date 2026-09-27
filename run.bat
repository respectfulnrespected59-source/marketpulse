@echo off
REM MarketPulse launcher (Windows) — double-click to run.
cd /d "%~dp0"
echo Starting MarketPulse...
start "" http://127.0.0.1:8000/app
python app.py
pause
