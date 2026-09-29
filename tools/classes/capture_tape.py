"""Freeze a chart into a lesson tape: the app's own /api/intraday payload.

A lesson's narration describes specific price action, and the live window
rolls forward every day, so each lesson plays against a tape captured ONCE and
kept in the private lessons repo. Same shape the chart already renders.

Run:  python tools/classes/capture_tape.py <symbol> <crypto|stock> <tf> [tape_id]
      e.g. python tools/classes/capture_tape.py btc crypto 1D
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TAPES = ROOT / "classes" / "tapes"
KEEP = ("symbol", "kind", "tf", "ts", "ohlc", "volume", "gmtoffset", "regular")
MIN_BARS = 30
TAPE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")


def capture(symbol: str, kind: str, tf: str) -> dict:
    import app
    data = app.fetch_intraday(kind, symbol, tf)
    if len(data.get("ts") or []) < MIN_BARS:
        raise SystemExit(f"only {len(data.get('ts') or [])} bars came back for {symbol} {tf}; not freezing that")
    tape = {k: data[k] for k in KEEP if k in data}
    tape["source"] = "Coinbase candles" if kind == "crypto" else "Yahoo Finance chart"
    tape["captured_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return tape


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    symbol, kind, tf = argv[0].lower(), argv[1].lower(), argv[2]
    tape = capture(symbol, kind, tf)
    tape_id = argv[3] if len(argv) > 3 else f"{symbol}-{tf.lower()}-{tape['captured_at'][:10]}"
    if not TAPE_ID_RE.fullmatch(tape_id):
        raise SystemExit(f"tape id {tape_id!r} must be letters, digits, dot, dash or underscore")
    TAPES.mkdir(parents=True, exist_ok=True)
    out = TAPES / f"{tape_id}.json"
    out.write_text(json.dumps(tape), encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {len(tape['ts'])} bars, last close {tape['ohlc'][-1][3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
