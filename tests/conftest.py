"""Shared test setup for MarketPulse / MAPLE58.

Two import roots are in play:
  * the repo root holds the pure-math modules (options.py, indicators.py)
  * agent/ holds the trading layer (config.py, store.py, guardrails.py)

The agent's settings module is agent_config.py (it used to be agent/config.py,
which shadowed the app's config.py and stopped the app from importing the
agent's safety code). Both directories stay on sys.path so one pytest run
covers both layers; `import config` is always the app's.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = os.path.join(ROOT, "agent")

for _p in (ROOT, AGENT):          # drop any stale entries first...
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, ROOT)
sys.path.insert(0, AGENT)         # ...so AGENT ends up at index 0 and wins for `config`
