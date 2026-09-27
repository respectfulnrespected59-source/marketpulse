#!/usr/bin/env bash
# MarketPulse launcher (macOS / Linux) — run:  bash run.sh
cd "$(dirname "$0")"
echo "Starting MarketPulse..."
# Tells licensing this is the buyer's own computer (it may keep a local signing secret).
export MP_LICENSE_LOCAL=1
# app.py opens the browser itself once it is listening (with the Trade desk unlocked).
export MP_OPEN_BROWSER=1
python3 app.py
