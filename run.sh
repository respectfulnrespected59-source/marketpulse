#!/usr/bin/env bash
# MarketPulse launcher (macOS / Linux) — run:  bash run.sh
cd "$(dirname "$0")"
echo "Starting MarketPulse..."
# Tells licensing this is the buyer's own computer (it may keep a local signing secret).
export MP_LICENSE_LOCAL=1
( sleep 1; python3 -m webbrowser "http://127.0.0.1:8000/app" >/dev/null 2>&1 ) &
python3 app.py
