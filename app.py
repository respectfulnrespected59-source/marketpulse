"""MarketPulse backend — pure Python standard library (no pip installs).

Serves the static dashboard and a small JSON API that proxies live market data
server-side (so the browser never hits CORS) and attaches technical signals.

Data sources (both free, no API key):
  - Crypto: CoinGecko /coins/markets (price, 24h change, 7d hourly sparkline)
  - Stocks: Yahoo Finance /v8/finance/chart (daily OHLC)

Run:  python app.py   ->  open http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import datetime

import backtest
import config
import dca
import indicators
import options

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
PORT = int(os.environ.get("PORT", "8000"))
CACHE_TTL = 60  # seconds

DEFAULT_CRYPTO = [
    "bitcoin", "ethereum", "solana", "binancecoin", "ripple", "cardano",
    "dogecoin", "avalanche-2", "chainlink", "polkadot", "tron", "litecoin",
]
DEFAULT_STOCKS = [
    "TSLA", "SNDK", "NVDA", "MU", "WDC", "MRVL",
]

# Liquid, mostly lower-priced optionable names the probe scanner sweeps to find
# setups whose probe actually fits a small pot (the watchlist runs rich).
SCAN_UNIVERSE = [
    "F", "SOFI", "PLTR", "INTC", "T", "BAC", "CSCO", "PFE",
    "SNAP", "HOOD", "NIO", "AAL", "WBD", "CMCSA", "UBER",
    # volatile low-dollar movers — best odds of a cheap, usable probe
    "PLUG", "LCID", "RIVN", "MARA", "RIOT", "CHPT", "AFRM", "DKNG",
]

# Johannesburg Stock Exchange (JSE) via Yahoo's `.JO` suffix — real African
# market data, free, no login (mystocks.africa's dashboard is auth-gated with no
# public API). Quotes are in ZA cents (e.g. MTN.JO 22955 = R229.55); the signal
# engine works on the raw series regardless.
AFRICA_STOCKS = [
    "NPN.JO", "MTN.JO", "SOL.JO", "SBK.JO", "FSR.JO", "AGL.JO",
    "SHP.JO", "CPI.JO", "VOD.JO", "NED.JO", "GFI.JO", "CFR.JO",
]

# AI Come-Up universe — liquid AI / semi / compute names, deliberately mixing
# pricey leaders with low-dollar movers so a small-pot PROBE actually fits. This
# is the sandbox to APPLY the method to — NOT a buy list or a set of picks.
AI_STOCKS = [
    "NVDA", "AMD", "MU", "MRVL", "AVGO", "TSM", "ARM", "SMCI",
    "PLTR", "SOUN", "BBAI", "AI", "IONQ", "RGTI",
]

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str):
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < CACHE_TTL:
        return hit[1]
    return None


def _store(key: str, value):
    _cache[key] = (time.time(), value)
    return value


def _get_json(url: str, headers: dict | None = None, timeout: int = 12):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0 MarketPulse"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- crypto

def fetch_crypto(ids: list[str]) -> list[dict]:
    key = "crypto:" + ",".join(ids)
    cached = _cached(key)
    if cached is not None:
        return cached
    qs = urllib.parse.urlencode({
        "vs_currency": "usd",
        "ids": ",".join(ids),
        "order": "market_cap_desc",
        "sparkline": "true",
        "price_change_percentage": "24h",
    })
    url = f"https://api.coingecko.com/api/v3/coins/markets?{qs}"
    rows = []
    for c in _get_json(url):
        closes = [p for p in (c.get("sparkline_in_7d") or {}).get("price", []) if p]
        # sparkline is hourly; htf_factor=24 makes the higher-timeframe check daily.
        sig = indicators.score_signals(closes, htf_factor=24) if len(closes) > 35 else {
            "score": 0, "label": "NEUTRAL", "css": "neutral", "rsi": None,
            "macd_hist": None, "sma": None, "reasons": ["not enough history"],
        }
        rows.append({
            "kind": "crypto",
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "price": c.get("current_price"),
            "change": round(c.get("price_change_percentage_24h") or 0, 2),
            "spark": closes[-48:],
            "signal": sig,
        })
    return _store(key, rows)


# ---------------------------------------------------------------- stocks

def _weekly_squeeze(symbol: str) -> dict | None:
    """Weekly + bi-weekly TTM squeeze for a stock (separate weekly OHLC pull).
    Returns {"weekly": {...}|None, "biweekly": {...}|None} or None on failure —
    a squeeze hiccup must never blank out a card."""
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?range=5y&interval=1wk")
        q = _get_json(url)["chart"]["result"][0]["indicators"]["quote"][0]
        highs, lows, closes = [], [], []
        for h, l, c in zip(q["high"], q["low"], q["close"]):
            if None not in (h, l, c):
                highs.append(h); lows.append(l); closes.append(c)
        weekly = indicators.ttm_squeeze(highs, lows, closes)
        bh, bl, bc = indicators.resample_ohlc(highs, lows, closes, 2)
        biweekly = indicators.ttm_squeeze(bh, bl, bc)
        return {"weekly": weekly, "biweekly": biweekly}
    except Exception:  # noqa: BLE001
        return None


def _session_vwap(symbol: str) -> float | None:
    """True intraday session VWAP from 5-minute bars (most recent session)."""
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?range=1d&interval=5m")
        q = _get_json(url)["chart"]["result"][0]["indicators"]["quote"][0]
        return indicators.session_vwap(q.get("high", []), q.get("low", []),
                                       q.get("close", []), q.get("volume", []))
    except Exception:  # noqa: BLE001
        return None


def _decision_guides(symbol: str, closes: list[float]) -> dict | None:
    """5/14/21 MA stack (daily) + intraday session VWAP, with price position."""
    stack = indicators.ma_stack(closes)
    if not stack:
        return None
    vwap = _session_vwap(symbol)
    price = closes[-1]
    return {**stack, "vwap": vwap,
            "vs_vwap": None if vwap is None else ("above" if price >= vwap else "below")}


def _quick_signal(symbol: str) -> dict | None:
    """Lightweight daily signal for the options strategy helper (label-driven)."""
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?range=1y&interval=1d")
        closes = [c for c in _get_json(url)["chart"]["result"][0]
                  ["indicators"]["quote"][0]["close"] if c is not None]
        return indicators.score_signals(closes) if len(closes) > 1 else None
    except Exception:  # noqa: BLE001
        return None


def _scan_one(symbol: str, pot: float) -> dict | None:
    """Run the probe sizer on one symbol for the scanner (chain + lean + plan)."""
    try:
        ch = options.chain(symbol)
        if ch.get("error"):
            return None
        sig = _quick_signal(symbol)
        label = sig.get("label") if sig else "NEUTRAL"
        direction = ("call" if label in ("BUY", "STRONG BUY")
                     else "put" if label in ("SELL", "STRONG SELL") else None)
        ch["lean"] = {"label": label, "direction": direction}
        pp = options.probe_plan(ch, pot)
        if not pp:
            return None
        pr = pp.get("probe") or {}
        return {"symbol": symbol, "spot": ch.get("spot"), "label": label,
                "direction": direction, "qualifies": pp.get("qualifies"),
                "probe_cost": pr.get("cost"), "strike": pr.get("strike"),
                "move_pct": pr.get("move_pct"), "delta": pr.get("delta"),
                "min_pot": pp.get("min_pot")}
    except Exception:  # noqa: BLE001 — one bad symbol shouldn't kill the scan
        return None


def fetch_one_stock(symbol: str) -> dict | None:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=1y&interval=1d"
    )
    try:
        data = _get_json(url)
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        price = closes[-1]
        prev = closes[-2]
        change = round((price - prev) / prev * 100, 2) if prev else 0.0
        sig = indicators.score_signals(closes)
        meta = result.get("meta", {})
        return {
            "kind": "stock",
            "symbol": symbol.upper(),
            "name": meta.get("longName") or meta.get("shortName") or symbol.upper(),
            "price": round(price, 2),
            "change": change,
            "spark": [round(c, 2) for c in closes[-48:]],
            "signal": sig,
            "squeeze": _weekly_squeeze(symbol),
            "guides": _decision_guides(symbol, closes),
        }
    except Exception as exc:  # noqa: BLE001 — one bad symbol shouldn't kill the grid
        return {"kind": "stock", "symbol": symbol.upper(), "error": str(exc)}


def fetch_stocks(symbols: list[str]) -> list[dict]:
    key = "stocks:" + ",".join(symbols)
    cached = _cached(key)
    if cached is not None:
        return cached
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(fetch_one_stock, symbols) if r]
    return _store(key, rows)


# ---------------------------------------------------------------- live quote

QUOTE_TTL = 15  # seconds — fresher than the grid cache for the Live Tracker


def live_quote(kind: str, symbol: str) -> dict:
    """A single symbol's fresh price + the app's live READ (signal), for the
    Live Tracker. Short-cached so a recording can poll without hammering the
    upstream free APIs. Honest note: crypto price can lag ~1 min (upstream
    cache); this is a swing/DCA tracker, not a tick-by-tick day-trading feed."""
    key = f"quote:{kind}:{symbol.lower()}"
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < QUOTE_TTL:
        return hit[1]
    if kind == "crypto":
        rows = fetch_crypto([symbol.lower()])
        row = rows[0] if rows else {"error": "no data"}
    else:
        row = fetch_one_stock(symbol) or {"error": "no data"}
    out = {
        "symbol": symbol.upper(), "kind": kind,
        "price": row.get("price"), "change": row.get("change"),
        "signal": row.get("signal"), "error": row.get("error"),
        "ts": int(time.time()),
    }
    _cache[key] = (time.time(), out)
    return out


# ---------------------------------------------------------------- history / proof

def fetch_history(kind: str, symbol: str):
    """Return (dates 'YYYY-MM-DD', closes) of ~1-2y daily history."""
    key = f"hist:{kind}:{symbol}"
    cached = _cached(key)
    if cached is not None:
        return cached
    if kind == "crypto":
        url = (f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}"
               "/market_chart?vs_currency=usd&days=365&interval=daily")
        data = _get_json(url)
        dates, closes = [], []
        for ms, price in data.get("prices", []):
            dates.append(datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d"))
            closes.append(price)
    else:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?range=2y&interval=1d")
        result = _get_json(url)["chart"]["result"][0]
        stamps = result["timestamp"]
        raw = result["indicators"]["quote"][0]["close"]
        dates, closes = [], []
        for ts, c in zip(stamps, raw):
            if c is None:
                continue
            dates.append(datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"))
            closes.append(c)
    return _store(key, (dates, closes))


def run_proof(kind: str, symbol: str) -> dict:
    dates, closes = fetch_history(kind, symbol)
    if len(closes) < backtest.WARMUP + max(backtest.HORIZONS) + 2:
        return {"symbol": symbol.upper(), "kind": kind, "error": "not enough history"}
    out = backtest.backtest_signals(dates, closes, kind=kind)
    out["strategy"] = backtest.simulate_strategy(dates, closes, kind=kind)
    out["walkforward"] = backtest.walk_forward(dates, closes, kind=kind)
    out["symbol"] = symbol.upper()
    out["kind"] = kind
    out["series"] = {"dates": dates, "closes": [round(c, 4) for c in closes]}
    return out


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quieter console
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/markets":
            try:
                kind = (params.get("type", ["crypto"])[0]).lower()
                syms = params.get("symbols", [None])[0]
                cap = None if config.features()["unlimited_symbols"] else config.FREE_SYMBOL_CAP
                if kind == "stocks":
                    symbols = [s.strip().upper() for s in syms.split(",")] if syms else DEFAULT_STOCKS
                    if cap:
                        symbols = symbols[:cap]
                    return self._json({"type": "stocks", "rows": fetch_stocks(symbols),
                                       "ts": int(time.time())})
                ids = [s.strip().lower() for s in syms.split(",")] if syms else DEFAULT_CRYPTO
                if cap:
                    ids = ids[:cap]
                return self._json({"type": "crypto", "rows": fetch_crypto(ids),
                                   "ts": int(time.time())})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, code=502)

        if path == "/api/proof":
            if not config.features()["proof"]:
                return self._json({"locked": True, "upgrade": config.UPGRADE_URL,
                                   "error": "Proof Mode is a Pro feature."}, code=402)
            try:
                symbol = (params.get("symbol", [""])[0]).strip()
                kind = (params.get("kind", ["stock"])[0]).lower()
                if not symbol:
                    return self._json({"error": "symbol required"}, code=400)
                key = f"proof:{kind}:{symbol.lower()}"
                cached = _cached(key)
                return self._json(cached if cached is not None
                                  else _store(key, run_proof(kind, symbol)))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, code=502)

        if path == "/api/quote":
            try:
                symbol = (params.get("symbol", [""])[0]).strip()
                kind = (params.get("kind", ["stock"])[0]).lower()
                if not symbol:
                    return self._json({"error": "symbol required"}, code=400)
                return self._json(live_quote(kind, symbol))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, code=502)

        if path == "/api/dca":
            if not config.features()["proof"]:
                return self._json({"locked": True, "upgrade": config.UPGRADE_URL,
                                   "error": "The DCA Wizard is a Pro feature."}, code=402)
            try:
                symbol = (params.get("symbol", [""])[0]).strip()
                kind = (params.get("kind", ["stock"])[0]).lower()
                if not symbol:
                    return self._json({"error": "symbol required"}, code=400)
                try:
                    monthly = max(1.0, min(1_000_000.0, float(params.get("monthly", ["200"])[0])))
                except (TypeError, ValueError):
                    monthly = 200.0
                cadence = (params.get("cadence", ["monthly"])[0]).lower()
                try:
                    years = max(1.0, min(40.0, float(params.get("years", ["10"])[0])))
                except (TypeError, ValueError):
                    years = 10.0
                key = f"dca:{kind}:{symbol.lower()}:{monthly}:{cadence}:{years}"
                cached = _cached(key)
                if cached is not None:
                    return self._json(cached)
                dates, closes = fetch_history(kind, symbol)
                if len(closes) < backtest.WARMUP + 2:
                    return self._json({"symbol": symbol.upper(), "kind": kind,
                                       "error": "not enough history"})
                report = dca.dca_report(dates, closes, kind, symbol, monthly, cadence, years)
                return self._json(_store(key, report))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, code=502)

        if path == "/api/options":
            try:
                symbol = (params.get("symbol", [""])[0]).strip()
                if not symbol:
                    return self._json({"error": "symbol required"}, code=400)
                expiry = params.get("expiry", [None])[0]
                try:
                    pot = max(50, min(1_000_000, int(float(params.get("pot", ["300"])[0]))))
                except (TypeError, ValueError):
                    pot = 300
                key = f"opt:{symbol.lower()}:{expiry or 'near'}:{pot}"
                cached = _cached(key)
                if cached is not None:
                    return self._json(cached)
                ch = options.chain(symbol, expiry)
                # Signal-driven debit-spread suggestion: bullish lean -> call debit,
                # bearish -> put debit, neutral -> no directional spread.
                sig = _quick_signal(symbol)
                if sig and not ch.get("error"):
                    label = sig.get("label")
                    direction = ("call" if label in ("BUY", "STRONG BUY")
                                 else "put" if label in ("SELL", "STRONG SELL")
                                 else None)
                    ch["lean"] = {"label": label, "direction": direction}
                    if direction:
                        ch["spread"] = options.suggest_spread(ch, direction)
                    # Squeeze-aware "either-way": a coiled TTM squeeze means a
                    # breakout is loading. If direction is unresolved (neutral
                    # signal or weekly vs bi-weekly momentum disagree), a long
                    # strangle plays the move either way.
                    sq = _weekly_squeeze(symbol) or {}
                    wk, bw = sq.get("weekly"), sq.get("biweekly")
                    coiled = bool((wk and wk["state"] == "on") or (bw and bw["state"] == "on"))
                    moms = [x["mom"] for x in (wk, bw) if x]
                    conflict = len(set(moms)) > 1
                    ch["squeeze"] = {"weekly": wk, "biweekly": bw,
                                     "coiled": coiled, "conflict": conflict}
                    if coiled:
                        ch["strangle"] = options.suggest_strangle(ch)
                        ch["either_way"] = bool(label == "NEUTRAL" or conflict)
                    # Plain-English "how to read this" decision walkthrough.
                    ch["read"] = options.decision_read(ch, sig)
                    # "Which way the data leans" nudge (a read, not an order).
                    ch["nudge"] = options.direction_nudge(ch)
                    # $-pot Probe→Read→Escalate sizer scaled to the stock's price.
                    ch["probe_plan"] = options.probe_plan(ch, pot)
                return self._json(_store(key, ch))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, code=502)

        if path == "/api/probe-scan":
            try:
                try:
                    pot = max(50, min(1_000_000, int(float(params.get("pot", ["300"])[0]))))
                except (TypeError, ValueError):
                    pot = 300
                key = f"probescan:{pot}"
                cached = _cached(key)
                if cached is not None:
                    return self._json(cached)
                with ThreadPoolExecutor(max_workers=8) as pool:
                    rows = [r for r in pool.map(lambda s: _scan_one(s, pot), SCAN_UNIVERSE) if r]
                qualifiers = sorted(
                    (r for r in rows if r.get("qualifies") and r.get("probe_cost")),
                    key=lambda r: r["probe_cost"])
                near = sorted(
                    (r for r in rows if r.get("qualifies") is False and r.get("min_pot")),
                    key=lambda r: r["min_pot"])[:6]
                # Crypto: no options chain, but a $X probe = $X of the coin
                # (fractional, always "affordable"). A coin "qualifies" when it
                # has a clear directional signal to probe (spot, not options).
                crypto = []
                try:
                    for r in fetch_crypto(DEFAULT_CRYPTO):
                        s = r.get("signal") or {}
                        sc = s.get("score", 0)
                        if sc and not r.get("error"):
                            crypto.append({"symbol": r["symbol"], "price": r["price"],
                                           "label": s.get("label"), "score": sc,
                                           "dir": "long" if sc > 0 else "short"})
                    crypto.sort(key=lambda c: -abs(c["score"]))
                    crypto = crypto[:8]
                except Exception:  # noqa: BLE001
                    crypto = []
                out = {"pot": pot, "budget": round(pot * 0.20), "scanned": len(rows),
                       "qualifiers": qualifiers, "near": near, "crypto": crypto}
                return self._json(_store(key, out))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, code=502)

        if path == "/api/universe":
            return self._json({
                "crypto": DEFAULT_CRYPTO, "stocks": DEFAULT_STOCKS,
                "africa": AFRICA_STOCKS, "ai": AI_STOCKS,
                "tier": config.TIER, "features": config.features(),
                "upgrade": config.UPGRADE_URL, "freeCap": config.FREE_SYMBOL_CAP,
            })

        # static files
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain")
        ctype = {
            ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
            ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        }.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)


def main():
    os.makedirs(STATIC, exist_ok=True)
    # Local runs stay on loopback (safe for the downloadable buyer tool). A host
    # like Render sets HOST=0.0.0.0 so the service is reachable publicly.
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, PORT), Handler)
    shown = "127.0.0.1" if host == "127.0.0.1" else host
    print(f"\n  MarketPulse running -> http://{shown}:{PORT}\n  (Ctrl+C to stop)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")


if __name__ == "__main__":
    main()
