"""Build the Gumroad buyer packs (FREE and PRO) from current source.

Uses explicit ALLOWLISTS — only the files named here go in. This is a
denylist's safer cousin: secrets (.env), runtime state (agent/data/, HALT),
caches (__pycache__), and marketing media can never accidentally leak into a
customer download, because they are simply never added.

Two editions from one tree:
  FREE — the live screener. Pro modules are physically absent from the zip, so
         the paid capability cannot be unlocked by editing a flag. app.py
         imports them defensively and every Pro route answers HTTP 402.
  PRO  — everything, with TIER = "pro".

config.py is rewritten in-flight so each pack ships the correct TIER; the file
on disk is never modified.

Run:  python tools/build_buyer_pack.py            # builds both
      python tools/build_buyer_pack.py free       # builds one
Out:  MarketPulse_Free_v2.zip / MarketPulse_Pro_v2.zip
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACK_ROOT = "MarketPulse"  # the folder name a buyer sees after unzipping

# Shipped in BOTH editions — the free screener and everything it needs.
BASE = [
    # --- the dashboard (what run.bat / run.sh launches) ---
    "app.py",
    "indicators.py",
    "config.py",
    "daily_plays.py",
    "run.bat",
    "run.sh",
    "README.md",
    "DISCLAIMER.md",      # risk disclosures — ships in BOTH editions, never optional
    "static/index.html",
    "static/styles.css",
    "static/app.js",
    # --- test suite (trust signal; not required to run the app) ---
    "pytest.ini",
    "tests/conftest.py",
    "tests/test_indicators.py",
]

# FREE ONLY. The free edition ships under PolyForm Noncommercial 1.0.0; the Pro
# edition must NOT carry a noncommercial license, so this file is not shared.
FREE_ONLY = [
    "LICENSE.md",
]

# PRO ONLY. These files are absent from the free zip entirely — that absence,
# not the TIER flag, is what makes the free edition genuinely limited.
PRO_ONLY = [
    "EULA.md",            # commercial terms for the paid edition
    "options.py",
    "backtest.py",
    "dca.py",
    # tests that exercise the Pro modules (they would fail to import in FREE)
    "tests/test_options.py",
    "tests/test_dca.py",
    # --- optional advanced: paper-first propose-and-approve agent (NO secrets/state) ---
    # Product call: the trading agent ships PRO-only. Move these into BASE if
    # you decide the free edition should include it.
    "agent/README.md",
    "agent/.env.example",
    "agent/config.py",
    "agent/store.py",
    "agent/guardrails.py",
    "agent/broker.py",
    "agent/proposer.py",
    "agent/cli.py",
    "tests/test_guardrails.py",   # needs agent/
]

EDITIONS = {
    "free": {"files": BASE + FREE_ONLY, "tier": "free",
             "out": "MarketPulse_Free_v2.zip"},
    "pro": {"files": BASE + PRO_ONLY, "tier": "pro",
            "out": "MarketPulse_Pro_v2.zip"},
}

# Belt-and-suspenders: refuse to ship anything that smells like a secret/state.
FORBIDDEN_SUBSTRINGS = (".env", "/data/", "__pycache__", "HALT", ".pyc")


def _safe(rel: str) -> bool:
    if rel == "agent/.env.example":      # the only .env-ish file that's allowed
        return True
    return not any(bad in rel for bad in FORBIDDEN_SUBSTRINGS)


def _config_source(tier: str) -> str:
    """Return config.py source with TIER set to `tier`. Never writes to disk."""
    src = open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
    out, n = re.subn(r'^TIER\s*=\s*"[^"]*"', f'TIER = "{tier}"', src, count=1,
                     flags=re.M)
    if n != 1:
        raise SystemExit("ABORT — could not rewrite TIER in config.py "
                         "(pattern not found); refusing to ship a wrong tier.")
    return out


def build(edition: str) -> str:
    spec = EDITIONS[edition]
    files, tier, out = spec["files"], spec["tier"], os.path.join(ROOT, spec["out"])

    missing = [f for f in files if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        raise SystemExit(f"ABORT — allowlisted files not found: {missing}")

    unsafe = [f for f in files if not _safe(f)]
    if unsafe:
        raise SystemExit(f"ABORT — allowlist contains forbidden paths: {unsafe}")

    # A free pack that contains a Pro module would defeat the whole split.
    if edition == "free":
        leaked = [f for f in files if f in PRO_ONLY]
        if leaked:
            raise SystemExit(f"ABORT — Pro files present in FREE pack: {leaked}")

    if os.path.exists(out):
        os.remove(out)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            arc = f"{PACK_ROOT}/{rel}"
            if rel == "config.py":          # tier stamped in-flight
                z.writestr(arc, _config_source(tier))
            else:
                z.write(os.path.join(ROOT, rel), arcname=arc)

    return out


if __name__ == "__main__":
    which = sys.argv[1:] or list(EDITIONS)
    for edition in which:
        if edition not in EDITIONS:
            raise SystemExit(f"unknown edition {edition!r}; choose from {list(EDITIONS)}")
        path = build(edition)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            tier_line = next(
                (ln for ln in z.read(f"{PACK_ROOT}/config.py").decode().splitlines()
                 if ln.startswith("TIER")), "?")
        print(f"\n{edition.upper()}: {os.path.basename(path)} "
              f"({os.path.getsize(path):,} bytes, {len(names)} files)")
        print(f"  stamped: {tier_line}")
        for n in names:
            print("   ", n)
