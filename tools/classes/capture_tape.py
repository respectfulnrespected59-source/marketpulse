"""Freeze a chart into a lesson tape: the app's own /api/intraday payload.

A lesson's narration describes specific price action, and the live window
rolls forward every day, so each lesson plays against a tape captured ONCE and
kept in the private lessons repo. Same shape the chart already renders.

A full-length lesson starts the same plan in several different years, and the
chart's own 1D window is one year. --years freezes that many years of daily
bars instead, from the same two sources the app uses.

Run:  python tools/classes/capture_tape.py <symbol> <crypto|stock> <tf> [tape_id] [--years N]
      e.g. python tools/classes/capture_tape.py btc crypto 1D
           python tools/classes/capture_tape.py spy stock 1D --years 5
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TAPES = ROOT / "classes" / "tapes"
KEEP = ("symbol", "kind", "tf", "ts", "ohlc", "volume", "gmtoffset", "regular")
MIN_BARS = 30
TAPE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")
DAY = 86_400
MAX_YEARS = 10
YAHOO_YEARS = (1, 2, 5, 10)      # the only multi-year ranges Yahoo's chart API answers
COINBASE_PAGE = 300              # candles one request may return
PAGE_PAUSE_S = 0.4               # between pages: a public API, asked politely
ISO = "%Y-%m-%dT%H:%M:%SZ"


def _iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime(ISO)


def _from_iso(text: str) -> int:
    return int(dt.datetime.strptime(text, ISO).replace(tzinfo=dt.timezone.utc).timestamp())


def _stamp(tape: dict, kind: str) -> dict:
    return {**tape, "source": "Coinbase candles" if kind == "crypto" else "Yahoo Finance chart",
            "captured_at": _iso(int(time.time()))}


def capture(symbol: str, kind: str, tf: str) -> dict:
    import app
    data = app.fetch_intraday(kind, symbol, tf)
    if len(data.get("ts") or []) < MIN_BARS:
        raise SystemExit(f"only {len(data.get('ts') or [])} bars came back for {symbol} {tf}; not freezing that")
    return _stamp({k: data[k] for k in KEEP if k in data}, kind)


def _crypto_days(app, symbol: str, years: int, now: int, pause: float) -> list[tuple]:
    """(ts, [o, h, l, c], volume) for every finished day, oldest first, a page at a time."""
    prod = app.coinbase_product(symbol)
    if not prod:
        raise SystemExit(f"{symbol} is not a Coinbase product")
    today = now // DAY * DAY                 # today's candle is still forming: stop at yesterday
    first, end = today - years * 365 * DAY, today - DAY
    rows: dict[int, tuple] = {}
    while end >= first:
        start = max(first, end - (COINBASE_PAGE - 1) * DAY)
        url = (f"{app.COINBASE_API}/products/{prod}/candles?granularity={DAY}"
               f"&start={_iso(start)}&end={_iso(end)}")
        for r in app._get_json(url) or []:
            # Coinbase row: [time, low, high, open, close, volume]
            if r and None not in r[1:5] and first <= r[0] < today:
                rows[int(r[0])] = ([app._px(r[3]), app._px(r[2]), app._px(r[1]), app._px(r[4])],
                                   round(float(r[5] or 0), 2))
        end = start - DAY
        time.sleep(pause)
    days = sorted(rows)
    for a, b in zip(days, days[1:]):
        if b - a != DAY:                     # a missing day would shift every scheduled buy after it
            raise SystemExit(f"gap in {symbol} history between {_iso(a)} and {_iso(b)}; not freezing that")
    # The gap check only sees holes BETWEEN days: an empty page at either end is
    # a shorter tape than was asked for, and must be a decision, not an accident.
    if days and days[-1] != today - DAY:
        raise SystemExit(f"{symbol} history ends {_iso(days[-1])[:10]}, not yesterday; not freezing that")
    if days and days[0] - first > 2 * DAY:
        raise SystemExit(f"{symbol} history starts {_iso(days[0])[:10]}: less than {years} years exist; ask for fewer")
    return [(t, *rows[t]) for t in days]


def _stock_days(app, symbol: str, years: int, now: int) -> tuple[list[tuple], int | None]:
    if years not in YAHOO_YEARS:
        raise SystemExit(f"years must be one of {YAHOO_YEARS} for a stock")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={years}y&interval=1d"
    result = app._get_json(url)["chart"]["result"][0]
    q = result["indicators"]["quote"][0]
    times, vols = result.get("timestamp") or [], q.get("volume") or []
    off = (result.get("meta") or {}).get("gmtoffset")
    rows = [(int(times[i]), [app._px(o), app._px(h), app._px(l), app._px(c)],
             float(vols[i]) if i < len(vols) and vols[i] is not None else 0.0)
            for i, (o, h, l, c) in enumerate(zip(q["open"], q["high"], q["low"], q["close"]))
            if i < len(times) and None not in (o, h, l, c)]
    # During market hours the last daily bar is a live tick, not a close. Stop at
    # yesterday (the exchange's own calendar day), the same rule as crypto.
    if rows and (rows[-1][0] + (off or 0)) // DAY == (now + (off or 0)) // DAY:
        rows = rows[:-1]
    return rows, off


def capture_history(app, symbol: str, kind: str, years: int, now: int | None = None,
                    pause: float = PAGE_PAUSE_S) -> dict:
    """`years` of daily bars as a tape. `app` is the app module (its fetch helpers)."""
    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= MAX_YEARS:
        raise SystemExit(f"years must be a whole number from 1 to {MAX_YEARS}")
    now = int(time.time()) if now is None else now
    if kind == "crypto":
        rows, off = _crypto_days(app, symbol, years, now, pause), None
    else:
        rows, off = _stock_days(app, symbol, years, now)
    if len(rows) < MIN_BARS:
        raise SystemExit(f"only {len(rows)} bars came back for {symbol} over {years}y; not freezing that")
    ts = [r[0] for r in rows]
    return _stamp({"symbol": symbol.upper(), "kind": kind, "tf": "1D", "ts": ts,
                   "ohlc": [r[1] for r in rows], "volume": [r[2] for r in rows], "gmtoffset": off,
                   "regular": [True] * len(ts) if kind == "crypto"
                   else [app.is_regular_bar(t, off) for t in ts]}, kind)


def _years_arg(argv: list[str]) -> tuple[list[str], int | None]:
    if "--years" not in argv:
        return argv, None
    i = argv.index("--years")
    if i + 1 >= len(argv) or not argv[i + 1].isdigit():
        raise SystemExit("--years needs a whole number, e.g. --years 5")
    return argv[:i] + argv[i + 2:], int(argv[i + 1])


def main(argv: list[str]) -> int:
    argv, years = _years_arg(argv)
    if len(argv) < 3:
        print(__doc__)
        return 2
    symbol, kind, tf = argv[0].lower(), argv[1].lower(), argv[2]
    if years is None:
        tape, default_id = capture(symbol, kind, tf), f"{symbol}-{tf.lower()}"
    elif tf != "1D":
        raise SystemExit("--years freezes daily bars: use 1D")
    else:
        import app
        tape, default_id = capture_history(app, symbol, kind, years), f"{symbol}-1d-{years}y"
    tape_id = argv[3] if len(argv) > 3 else f"{default_id}-{tape['captured_at'][:10]}"
    if not TAPE_ID_RE.fullmatch(tape_id):
        raise SystemExit(f"tape id {tape_id!r} must be letters, digits, dot, dash or underscore")
    TAPES.mkdir(parents=True, exist_ok=True)
    out = TAPES / f"{tape_id}.json"
    out.write_text(json.dumps(tape), encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {len(tape['ts'])} bars, {_iso(tape['ts'][0])[:10]} to "
          f"{_iso(tape['ts'][-1])[:10]}, last close {tape['ohlc'][-1][3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
