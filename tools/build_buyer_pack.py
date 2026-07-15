"""Build the Gumroad buyer pack (MarketPulse_v2.zip) from current source.

Uses an explicit ALLOWLIST — only the files named here go in. This is a
denylist's safer cousin: secrets (.env), runtime state (agent/data/, HALT),
caches (__pycache__), and marketing media can never accidentally leak into a
customer download, because they are simply never added.

Run:  python tools/build_buyer_pack.py
Out:  MarketPulse_v2.zip   (top-level folder inside: MarketPulse/)
"""
from __future__ import annotations

import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "MarketPulse_v2.zip")
PACK_ROOT = "MarketPulse"  # the folder name a buyer sees after unzipping

# Every file shipped to the buyer, relative to the repo root. Nothing else.
ALLOWLIST = [
    # --- the dashboard (what run.bat / run.sh launches) ---
    "app.py",
    "indicators.py",
    "options.py",
    "backtest.py",
    "dca.py",
    "config.py",
    "daily_plays.py",
    "run.bat",
    "run.sh",
    "README.md",
    "static/index.html",
    "static/styles.css",
    "static/app.js",
    # --- optional advanced: paper-first propose-and-approve agent (NO secrets/state) ---
    "agent/README.md",
    "agent/.env.example",
    "agent/config.py",
    "agent/store.py",
    "agent/guardrails.py",
    "agent/broker.py",
    "agent/proposer.py",
    "agent/cli.py",
    # --- test suite (trust signal; not required to run the app) ---
    "pytest.ini",
    "tests/conftest.py",
    "tests/test_indicators.py",
    "tests/test_options.py",
    "tests/test_guardrails.py",
    "tests/test_dca.py",
]

# Belt-and-suspenders: refuse to ship anything that smells like a secret/state.
FORBIDDEN_SUBSTRINGS = (".env", "/data/", "__pycache__", "HALT", ".pyc")


def _safe(rel: str) -> bool:
    if rel == "agent/.env.example":      # the only .env-ish file that's allowed
        return True
    return not any(bad in rel for bad in FORBIDDEN_SUBSTRINGS)


def build() -> str:
    missing = [f for f in ALLOWLIST if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        raise SystemExit(f"ABORT — allowlisted files not found: {missing}")

    unsafe = [f for f in ALLOWLIST if not _safe(f)]
    if unsafe:
        raise SystemExit(f"ABORT — allowlist contains forbidden paths: {unsafe}")

    if os.path.exists(OUT):
        os.remove(OUT)

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in ALLOWLIST:
            z.write(os.path.join(ROOT, rel), arcname=f"{PACK_ROOT}/{rel}")

    return OUT


if __name__ == "__main__":
    path = build()
    size = os.path.getsize(path)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    print(f"wrote {path} ({size} bytes, {len(names)} files)")
    for n in names:
        print("  ", n)
