#!/usr/bin/env bash
# MarketPulse launcher (macOS / Linux) — run:  bash run.sh
cd "$(dirname "$0")"
echo "Starting MarketPulse..."
( sleep 1; python3 -m webbrowser "http://127.0.0.1:8000" >/dev/null 2>&1 ) &
python3 app.py
