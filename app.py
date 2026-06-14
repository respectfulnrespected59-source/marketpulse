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
import indicators

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
PORT = int(os.environ.get("PORT", "8000"))
CACHE_TTL = 60  # seconds

DEFAULT_CRYPTO = [
    "bitcoin", "ethereum", "solana", "binancecoin", "ripple", "cardano",
    "dogecoin", "avalanche-2", "chainlink", "polkadot", "tron", "litecoin",
]
DEFAULT_STOCKS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL",
    "META", "AMD", "NFLX", "SPY", "QQQ", "COIN",
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
    out = backtest.backtest_signals(dates, closes)
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

        if path == "/api/universe":
            return self._json({
                "crypto": DEFAULT_CRYPTO, "stocks": DEFAULT_STOCKS,
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
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  MarketPulse running -> http://127.0.0.1:{PORT}\n  (Ctrl+C to stop)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")


if __name__ == "__main__":
    main()
