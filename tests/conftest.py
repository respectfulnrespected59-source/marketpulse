"""Shared test setup for MarketPulse / MAPLE58.

Two import roots are in play:
  * the repo root holds the pure-math modules (options.py, indicators.py)
  * agent/ holds the trading layer (config.py, store.py, guardrails.py)

agent/config.py and the repo-root config.py share a name. The root math
modules never import `config`, so we put agent/ FIRST on sys.path: any
`import config` resolves to the agent's, while `import options` / `import
indicators` still resolve from the root. Keeping both on the path lets one
pytest run cover both layers.
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
