"""Edition / tier configuration for MarketPulse.

Sell two builds from one codebase:
  - Ship the FREE build with TIER = "free"  (lead magnet: live screener only)
  - Ship the PRO build  with TIER = "pro"   (Proof Mode + alerts + unlimited symbols)

This is honest tier-gating for a downloadable tool, not hard DRM (a local app's
source is always visible). Real enforcement = host it as a SaaS later.
"""

import os

TIER = "pro"                # "free" or "pro"  — rewritten per edition at build time

# A hosted deployment serves ONE build to everybody, so the shipped tier has to
# be overridable at boot: the public demo runs with MP_TIER=free so it cannot
# hand out Pro to anyone holding the link. Downloadable zips never set this var,
# so they keep whatever tier they were built with.
#
# Kept as a separate statement on purpose — tools/build_buyer_pack.py rewrites
# the literal assignment above by regex, and folding the two together would
# break that match and abort the build.
_explicit_tier = os.environ.get("MP_TIER", "").strip().lower()

# A publicly reachable instance defaults to FREE even if nobody remembered to
# set MP_TIER. The demo shipped as Pro precisely because the tier depended on
# someone configuring a dashboard correctly; the safe default should not.
# Local runs (the downloaded zip binds 127.0.0.1) keep the tier they were
# built with. A buyer self-hosting their own Pro copy sets MP_TIER=pro.
_host = os.environ.get("HOST", "127.0.0.1").strip().lower()
_is_public = _host not in ("127.0.0.1", "localhost", "::1", "") or bool(
    os.environ.get("RENDER")
)

if _explicit_tier:
    TIER = _explicit_tier   # an explicit setting always wins
elif _is_public:
    TIER = "free"

if TIER not in ("free", "pro"):
    TIER = "free"           # unrecognised value fails closed, never open

FREE_SYMBOL_CAP = 6         # assets shown per market in the free build
# The Pro product page itself, not the storefront root — this is the single
# most important click in the free edition, and dropping someone on the store
# to go hunting for the right product loses them.
UPGRADE_URL = "https://quantummelaninmedia.gumroad.com/l/yvsyyg"

PRO = {"proof": True, "alerts": True, "unlimited_symbols": True,
       "dca": True, "options": True}
FREE = {"proof": False, "alerts": False, "unlimited_symbols": False,
        "dca": False, "options": False}


def features() -> dict:
    return PRO if TIER == "pro" else FREE


def is_pro() -> bool:
    return TIER == "pro"
