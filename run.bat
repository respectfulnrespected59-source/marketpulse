@echo off
REM MarketPulse launcher (Windows) — double-click to run.
cd /d "%~dp0"
echo Starting MarketPulse...
REM Tells licensing this is the buyer's own computer (it may keep a local signing secret).
set MP_LICENSE_LOCAL=1
REM app.py opens the browser itself once it is listening (with the Trade desk unlocked).
set MP_OPEN_BROWSER=1
python app.py
pause
