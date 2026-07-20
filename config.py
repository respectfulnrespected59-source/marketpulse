"""Edition / tier configuration for MarketPulse.

Sell two builds from one codebase:
  - Ship the FREE build with TIER = "free"  (lead magnet: live screener only)
  - Ship the PRO build  with TIER = "pro"   (Proof Mode + alerts + unlimited symbols)

This is honest tier-gating for a downloadable tool, not hard DRM (a local app's
source is always visible). Real enforcement = host it as a SaaS later.
"""

TIER = "pro"                # "free" or "pro"
FREE_SYMBOL_CAP = 6         # assets shown per market in the free build
UPGRADE_URL = "https://quantummelaninmedia.gumroad.com"  # set to the Pro product link

PRO = {"proof": True, "alerts": True, "unlimited_symbols": True,
       "dca": True, "options": True}
FREE = {"proof": False, "alerts": False, "unlimited_symbols": False,
        "dca": False, "options": False}


def features() -> dict:
    return PRO if TIER == "pro" else FREE


def is_pro() -> bool:
    return TIER == "pro"
