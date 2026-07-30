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
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import datetime

import config
import indicators
from safety import BoundedCache, InvalidSymbol, clean_kind, clean_symbol
import symbols as symbol_catalog

# Pro modules are absent from the FREE buyer pack (see tools/build_buyer_pack.py).
# Import them defensively so the free build still starts; every route that uses
# them is gated by _enabled() below, which treats "not installed" as "locked".
# dca imports backtest, so a missing backtest also yields dca is None.
try:
    import backtest
except ModuleNotFoundError:
    backtest = None
try:
    import dca
except ModuleNotFoundError:
    dca = None
try:
    import options
except ModuleNotFoundError:
    options = None

_INSTALLED = {
    "proof": backtest is not None,
    "dca": dca is not None,
    "options": options is not None,
}


def _enabled(feature: str) -> bool:
    """True only if the tier grants the feature AND its module shipped."""
    return bool(config.features().get(feature)) and _INSTALLED.get(feature, True)

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

# CoinGecko's free API rate-limits shared datacenter IPs (429 on Render), so
# crypto falls back to Coinbase's public API (keyless, allows datacenter IPs).
# CoinGecko id -> (Coinbase product, ticker, display name). Coins Coinbase does
# not list (BNB, TRON) simply drop from the grid during a CoinGecko outage
# rather than 502-ing the whole tab.
COINBASE_MAP = {
    "bitcoin": ("BTC-USD", "BTC", "Bitcoin"),
    "ethereum": ("ETH-USD", "ETH", "Ethereum"),
    "solana": ("SOL-USD", "SOL", "Solana"),
    "ripple": ("XRP-USD", "XRP", "XRP"),
    "cardano": ("ADA-USD", "ADA", "Cardano"),
    "dogecoin": ("DOGE-USD", "DOGE", "Dogecoin"),
    "avalanche-2": ("AVAX-USD", "AVAX", "Avalanche"),
    "chainlink": ("LINK-USD", "LINK", "Chainlink"),
    "polkadot": ("DOT-USD", "DOT", "Polkadot"),
    "litecoin": ("LTC-USD", "LTC", "Litecoin"),
}
COINBASE_API = "https://api.exchange.coinbase.com"

# Optional CoinGecko Demo API key (free, key-scoped not IP-scoped). If set as an
# env var it is sent as a header so CoinGecko keeps working on Render too.
_CG_KEY = os.environ.get("MP_CG_KEY", "").strip()


def _cg_headers() -> dict:
    h = {"User-Agent": "Mozilla/5.0 MarketPulse"}
    if _CG_KEY:
        h["x-cg-demo-api-key"] = _CG_KEY
    return h


# Bounded on purpose. The keys include a caller-supplied symbol, so a plain
# dict let anyone grow this process's memory by asking for symbols that don't
# exist. 512 entries covers every symbol a real session touches across all
# timeframes, and evicts least-recently-used past that.
MAX_CACHE_ENTRIES = 512
_cache = BoundedCache(MAX_CACHE_ENTRIES)

# One fixed sentence for every upstream failure. Detail goes to the log, not
# to the caller — see Handler._upstream_failed.
UPSTREAM_ERROR_MESSAGE = "Market data is temporarily unavailable. Try again shortly."


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


# ------------------------------------------------- symbol universe

# Coinbase's catalogue changes when coins are listed or delisted, which is rare,
# so this is cached for six hours. COINBASE_MAP stays as the curated core (it
# carries display names and CoinGecko slugs the grid needs); this adds
# everything else Coinbase currently trades.
LISTED_CRYPTO_TTL = 6 * 3600


def listed_crypto() -> dict[str, str]:
    """Base ticker -> Coinbase product id, for every market Coinbase lists.

    Degrades to an empty map if Coinbase is unreachable, in which case symbol
    resolution falls back to the curated map and the app behaves as before.
    """
    hit = _cache.get("listed:crypto")
    if hit and (time.time() - hit[0]) < LISTED_CRYPTO_TTL:
        return hit[1]
    try:
        raw = _get_json(f"{COINBASE_API}/products", timeout=15)
        listed = symbol_catalog.parse_coinbase_products(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not load Coinbase catalogue: {exc}", file=sys.stderr)
        listed = {}
    if listed:
        _cache["listed:crypto"] = (time.time(), listed)
    return listed


def _px(value) -> float:
    """Round a price for the wire, keeping sub-penny coins intact."""
    return symbol_catalog.round_price(float(value))


def coinbase_product(symbol: str) -> str | None:
    """The Coinbase product for a slug or ticker, or None if it isn't tradable."""
    return symbol_catalog.resolve_crypto_product(symbol, COINBASE_MAP, listed_crypto())


def search_symbols(query: str, limit: int = 12) -> list[dict]:
    """Look a symbol up by name or ticker across stocks, ETFs, and crypto.

    Two sources, because each is only trustworthy for half the problem: Yahoo
    indexes company names but returns unusable identifiers for crypto, while
    Coinbase's catalogue is exactly the set of coins this app can actually
    price. Crypto matches lead — a user typing "pepe" means the coin.
    """
    key = f"search:{query.lower()}:{limit}"
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < 300:
        return hit[1]

    coins = symbol_catalog.search_listed_crypto(
        query, listed_crypto(), COINBASE_MAP, limit=max(1, limit // 2)
    )

    stocks: list[dict] = []
    try:
        url = ("https://query1.finance.yahoo.com/v1/finance/search"
               f"?q={urllib.parse.quote(query)}&quotesCount={limit}&newsCount=0")
        stocks = symbol_catalog.parse_yahoo_search(_get_json(url), limit=limit)
    except Exception as exc:  # noqa: BLE001 — a coin match is still useful
        print(f"[warn] symbol search upstream failed: {exc}", file=sys.stderr)

    rows = (coins + stocks)[:limit]
    _cache[key] = (time.time(), rows)
    return rows


# ---------------------------------------------------------------- crypto

def _signal_from_closes(closes: list[float]) -> dict:
    """Hourly-close signal; htf_factor=24 makes the higher-timeframe check daily."""
    if len(closes) > 35:
        return indicators.score_signals(closes, htf_factor=24)
    return {"score": 0, "label": "NEUTRAL", "css": "neutral", "rsi": None,
            "macd_hist": None, "sma": None, "reasons": ["not enough history"]}


def _crypto_from_coingecko(ids: list[str]) -> list[dict]:
    qs = urllib.parse.urlencode({
        "vs_currency": "usd",
        "ids": ",".join(ids),
        "order": "market_cap_desc",
        "sparkline": "true",
        "price_change_percentage": "24h",
    })
    url = f"https://api.coingecko.com/api/v3/coins/markets?{qs}"
    rows = []
    for c in _get_json(url, headers=_cg_headers()):
        closes = [p for p in (c.get("sparkline_in_7d") or {}).get("price", []) if p]
        rows.append({
            "kind": "crypto",
            "id": c.get("id"),
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "price": c.get("current_price"),
            "change": round(c.get("price_change_percentage_24h") or 0, 2),
            "spark": closes[-48:],
            "signal": _signal_from_closes(closes),
        })
    return rows


def _coinbase_closes(product: str, granularity: int) -> tuple[list[int], list[float]]:
    """(epoch_seconds, closes) ascending from Coinbase public candles.
    Coinbase returns up to 300 rows newest-first as [time,low,high,open,close,vol]."""
    url = f"{COINBASE_API}/products/{product}/candles?granularity={granularity}"
    raw = _get_json(url)
    rows = sorted((r for r in raw if r and r[4] is not None), key=lambda r: r[0])
    return [int(r[0]) for r in rows], [float(r[4]) for r in rows]


def _coinbase_ohlc(product: str, granularity: int) -> list[list[float]]:
    """[[open,high,low,close], ...] ascending from Coinbase candles
    ([time,low,high,open,close,vol] -> reordered to o,h,l,c)."""
    url = f"{COINBASE_API}/products/{product}/candles?granularity={granularity}"
    raw = _get_json(url)
    rows = sorted((r for r in raw if r and None not in r[1:5]), key=lambda r: r[0])
    return [[float(r[3]), float(r[2]), float(r[1]), float(r[4])] for r in rows]


# Timeframe presets for the live chart. Stocks map to Yahoo range/interval;
# crypto to a Coinbase granularity (seconds). "1m" is the tightest tape.
# Intraday timeframe map. The `10m` slot has no native venue interval on
# either Yahoo or Coinbase, so the fetch pulls 5m bars and pair-aggregates
# them into synthesized 10m candles server-side (see _pair_agg_ohlc).
INTRADAY_TF = {
    "stock": {"1m": ("1d", "1m"), "5m": ("5d", "5m"), "10m": ("5d", "5m"),
              "1h": ("1mo", "60m"), "day": ("1d", "5m"), "wide": ("5d", "15m")},
    "crypto": {"1m": 60, "5m": 300, "10m": 300, "1h": 3600,
               "day": 300, "wide": 3600},
}


def fetch_intraday(kind: str, symbol: str, tf: str = "wide") -> dict:
    """Recent intraday OHLC candles for the live trading chart, at a chosen
    timeframe. Stocks use Yahoo bars; crypto uses Coinbase candles. Short-
    cached so a live poll can refresh without hammering upstream.

    Response shape:
      ohlc: [[o,h,l,c], ...]       (unchanged — legacy candle renderer)
      ts:   [unix_seconds, ...]    (parallel to ohlc; empty if source lacks it)
    """
    tf = tf if tf in INTRADAY_TF["stock"] else "wide"
    key = f"intraday:{kind}:{symbol.lower()}:{tf}"
    hit = _cache.get(key)
    # 1-min tape needs a snappier cache so a live poll actually shows new bars.
    ttl = 20 if tf == "1m" else QUOTE_TTL
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    ohlc: list[list[float]] = []
    ts_arr: list[int] = []
    vol_arr: list[float] = []
    if kind == "crypto":
        prod = coinbase_product(symbol)
        if prod:
            try:
                gran = INTRADAY_TF["crypto"][tf]
                url = f"{COINBASE_API}/products/{prod}/candles?granularity={gran}"
                raw = _get_json(url) or []
                rows = sorted((r for r in raw if r and None not in r[1:5]), key=lambda r: r[0])
                for r in rows:
                    # Coinbase row: [time, low, high, open, close, volume]
                    # Precision scales with price: a fixed 4dp flattens
                    # sub-penny coins like PEPE to a row of zeros.
                    ohlc.append([_px(r[3]), _px(r[2]), _px(r[1]), _px(r[4])])
                    ts_arr.append(int(r[0]))
                    vol_arr.append(round(float(r[5] or 0), 2))
            except Exception:  # noqa: BLE001
                ohlc, ts_arr, vol_arr = [], [], []
    else:
        try:
            rng, interval = INTRADAY_TF["stock"][tf]
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                   f"?range={rng}&interval={interval}")
            result = _get_json(url)["chart"]["result"][0]
            q = result["indicators"]["quote"][0]
            times = result.get("timestamp") or []
            vols = q.get("volume") or []
            for i, (o, h, l, c) in enumerate(zip(q["open"], q["high"], q["low"], q["close"])):
                if None not in (o, h, l, c):
                    ohlc.append([_px(o), _px(h), _px(l), _px(c)])
                    ts_arr.append(int(times[i]) if i < len(times) else 0)
                    v = vols[i] if i < len(vols) else 0
                    vol_arr.append(float(v) if v is not None else 0.0)
        except Exception:  # noqa: BLE001
            ohlc, ts_arr, vol_arr = [], [], []
    # Synthesize 10m bars by pair-aggregating consecutive 5m bars.
    if tf == "10m" and ohlc:
        ohlc, ts_arr, vol_arr = _pair_agg_ohlc(ohlc, ts_arr, vol_arr)
    out = {"symbol": symbol.upper(), "kind": kind, "tf": tf, "ohlc": ohlc, "ts": ts_arr,
           "volume": vol_arr,
           "last": ohlc[-1][3] if ohlc else None, "server_ts": int(time.time())}
    _cache[key] = (time.time(), out)
    return out


def _pair_agg_ohlc(ohlc: list, ts: list, vol: list) -> tuple[list, list, list]:
    """Fold two adjacent bars into one: open = first.o, close = second.c,
    high = max, low = min, volume = sum, timestamp = first bar's start."""
    o2, t2, v2 = [], [], []
    n = len(ohlc) - (len(ohlc) % 2)
    for i in range(0, n, 2):
        a, b = ohlc[i], ohlc[i + 1]
        o2.append([a[0], max(a[1], b[1]), min(a[2], b[2]), b[3]])
        t2.append(ts[i] if i < len(ts) else 0)
        v2.append(round((vol[i] if i < len(vol) else 0) + (vol[i + 1] if i + 1 < len(vol) else 0), 2))
    return o2, t2, v2


# ---------------------------------------------------- chart overlays

def _daily_bars(kind: str, symbol: str) -> tuple[list[int], list[float], list[float], list[float]]:
    """Return (ts, highs, lows, closes) of ~120 daily bars for overlay math.
    Reuses existing fetchers so a hiccup here degrades gracefully to empty."""
    try:
        if kind == "crypto":
            prod = coinbase_product(symbol)
            if not prod:
                return [], [], [], []
            url = f"{COINBASE_API}/products/{prod}/candles?granularity=86400"
            raw = _get_json(url) or []
            rows = sorted((r for r in raw if r and None not in r[1:5]), key=lambda r: r[0])
            ts = [int(r[0]) for r in rows]
            highs = [float(r[2]) for r in rows]
            lows = [float(r[1]) for r in rows]
            closes = [float(r[4]) for r in rows]
            return ts, highs, lows, closes
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?range=6mo&interval=1d")
        result = _get_json(url)["chart"]["result"][0]
        stamps = result.get("timestamp") or []
        q = result["indicators"]["quote"][0]
        ts, highs, lows, closes = [], [], [], []
        for i, (h, l, c) in enumerate(zip(q.get("high", []), q.get("low", []), q.get("close", []))):
            if None in (h, l, c):
                continue
            ts.append(int(stamps[i]) if i < len(stamps) else 0)
            highs.append(float(h)); lows.append(float(l)); closes.append(float(c))
        return ts, highs, lows, closes
    except Exception:  # noqa: BLE001
        return [], [], [], []


def chart_overlay(kind: str, symbol: str) -> dict:
    """Daily EMA(14/21/57) series + TTM squeeze status, cached ~5 min.
    Returns EMAs as [[unix_ts, value], ...] pairs so the client can align
    them on the intraday chart without knowing anything about calendars."""
    key = f"overlay:{kind}:{symbol.lower()}"
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < 300:  # 5-min TTL — daily bars change once/day
        return hit[1]
    ts, highs, lows, closes = _daily_bars(kind, symbol)
    out: dict = {"symbol": symbol.upper(), "kind": kind, "server_ts": int(time.time()),
                 "emas": {"ema14": [], "ema21": [], "ema57": []}, "squeeze": None}
    if closes and len(closes) >= 14:
        for period, name in ((14, "ema14"), (21, "ema21"), (57, "ema57")):
            series = indicators.ema_series(closes, period)
            if not series:
                continue
            # ema_series length = len(closes) - period + 1; each value aligns
            # with the bar at index (period - 1 + i).
            pairs = []
            for i, v in enumerate(series):
                bar_idx = period - 1 + i
                if bar_idx < len(ts):
                    pairs.append([ts[bar_idx], _px(v)])
            out["emas"][name] = pairs
    # Squeeze: reuse the weekly path for stocks; compute daily-scale for crypto
    # (crypto has no natural weekly cadence in a 24/7 market).
    if kind == "crypto":
        if closes and len(closes) >= 22:
            try:
                weekly = indicators.ttm_squeeze(highs, lows, closes)
                out["squeeze"] = {"weekly": weekly, "biweekly": None,
                                  "grain": "daily"}
            except Exception:  # noqa: BLE001
                out["squeeze"] = None
    else:
        out["squeeze"] = _weekly_squeeze(symbol)
        if out["squeeze"]:
            out["squeeze"]["grain"] = "weekly"
    _cache[key] = (time.time(), out)
    return out


def _crypto_from_coinbase(ids: list[str]) -> list[dict]:
    """Keyless fallback: one hourly-candle call per supported coin, in parallel."""
    # Resolve every requested id, not just the curated ones — a coin the user
    # added by ticker is as real as one that shipped in the defaults. Anything
    # Coinbase does not list is dropped, same as before.
    targets = []
    for i in ids:
        product = coinbase_product(i)
        if not product:
            continue
        curated = COINBASE_MAP.get(i.lower())
        ticker = curated[1] if curated else i.upper()
        name = symbol_catalog.crypto_display_name(i, COINBASE_MAP)
        targets.append((i, (product, ticker, name)))

    def one(item):
        cg_id, (product, ticker, name) = item
        try:
            _, closes = _coinbase_closes(product, 3600)  # hourly (~12 days)
            if not closes:
                return None
            price = closes[-1]
            ref = closes[-25] if len(closes) >= 25 else closes[0]
            change = round((price - ref) / ref * 100, 2) if ref else 0
            return {
                "kind": "crypto", "id": cg_id, "symbol": ticker, "name": name,
                "price": price, "change": change, "spark": closes[-48:],
                "signal": _signal_from_closes(closes),
            }
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return [r for r in pool.map(one, targets) if r]


def fetch_crypto(ids: list[str]) -> list[dict]:
    key = "crypto:" + ",".join(ids)
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        rows = _crypto_from_coingecko(ids)
        if rows:
            return _store(key, rows)
    except Exception:  # noqa: BLE001  (429/geo/timeout) -> keyless fallback
        pass
    rows = _crypto_from_coinbase(ids)
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
            "price": _px(price),
            "change": change,
            "spark": [_px(c) for c in closes[-48:]],
            "signal": sig,
            "squeeze": _weekly_squeeze(symbol),
            "guides": _decision_guides(symbol, closes),
        }
    except Exception as exc:  # noqa: BLE001 — one bad symbol shouldn't kill the grid
        # Detail to the log; the row itself only says the quote didn't load, so
        # the grid never renders internal URLs or paths into the page.
        print(f"[error] quote {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {"kind": "stock", "symbol": symbol.upper(),
                "error": UPSTREAM_ERROR_MESSAGE}


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
        dates, closes = [], []
        try:
            url = (f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}"
                   "/market_chart?vs_currency=usd&days=365&interval=daily")
            data = _get_json(url, headers=_cg_headers())
            for ms, price in data.get("prices", []):
                dates.append(datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d"))
                closes.append(price)
        except Exception:  # noqa: BLE001  (429/geo) -> Coinbase daily candles
            dates, closes = [], []
        product = None if closes else coinbase_product(symbol)
        if product:
            stamps, cl = _coinbase_closes(product, 86400)  # daily (~300 days)
            dates = [datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d") for t in stamps]
            closes = cl
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


def _stock_ohlc_map(symbol: str) -> dict:
    """{'YYYY-MM-DD': (open, high, low, close)} from the same Yahoo 2y/1d
    feed fetch_history uses, so candles align 1:1 with the signal series.
    Crypto has no honest intraday OHLC here, so it is intentionally absent
    (the Proof chart falls back to a bright line for crypto)."""
    key = f"ohlc:{symbol.lower()}"
    cached = _cached(key)
    if cached is not None:
        return cached
    out: dict = {}
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?range=2y&interval=1d")
        result = _get_json(url)["chart"]["result"][0]
        stamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
        opens, highs, lows, closes = q["open"], q["high"], q["low"], q["close"]
        for ts, o, h, l, c in zip(stamps, opens, highs, lows, closes):
            if None in (o, h, l, c):
                continue
            d = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            out[d] = (o, h, l, c)
    except Exception:  # noqa: BLE001
        out = {}
    return _store(key, out)


def run_proof(kind: str, symbol: str) -> dict:
    dates, closes = fetch_history(kind, symbol)
    if len(closes) < backtest.WARMUP + max(backtest.HORIZONS) + 2:
        return {"symbol": symbol.upper(), "kind": kind, "error": "not enough history"}
    out = backtest.backtest_signals(dates, closes, kind=kind)
    out["strategy"] = backtest.simulate_strategy(dates, closes, kind=kind)
    out["walkforward"] = backtest.walk_forward(dates, closes, kind=kind)
    out["symbol"] = symbol.upper()
    out["kind"] = kind
    series = {"dates": dates, "closes": [_px(c) for c in closes]}
    if kind != "crypto":
        omap = _stock_ohlc_map(symbol)
        hits = sum(1 for d in dates if d in omap)
        if hits >= len(dates) * 0.9:  # enough real candles to be worth it
            # One [o,h,l,c] per signal date; fall back to a flat close-candle
            # for any gap so the x-axis stays aligned with the signal markers.
            candles = []
            for d, c in zip(dates, closes):
                bar = omap.get(d)
                if bar:
                    o, h, l, cl = bar
                    candles.append([_px(o), _px(h), _px(l), _px(cl)])
                else:
                    candles.append([c, c, c, c])
            series["ohlc"] = candles
    out["series"] = series
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

    @staticmethod
    def _upstream_failed(route: str, exc: Exception) -> str:
        """Log the real cause, hand the client a fixed sentence.

        The exception text carries the URL we built and local file paths, so
        echoing it told a caller how the server is wired. Operators still get
        the detail on stderr.
        """
        print(f"[error] {route}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return UPSTREAM_ERROR_MESSAGE

    def _symbol_and_kind(self, params: dict, default_kind: str = "stock"):
        """Pull a validated (symbol, kind) out of the query string.

        Raises InvalidSymbol, which the route handlers turn into a 400.
        """
        symbol = clean_symbol(params.get("symbol", [""])[0])
        kind = clean_kind(params.get("kind", [default_kind])[0], default=default_kind)
        return symbol, kind

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
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/proof":
            if not _enabled("proof"):
                return self._json({"locked": True, "upgrade": config.UPGRADE_URL,
                                   "error": "Proof Mode is a Pro feature."}, code=402)
            try:
                symbol, kind = self._symbol_and_kind(params)
                key = f"proof:{kind}:{symbol.lower()}"
                cached = _cached(key)
                return self._json(cached if cached is not None
                                  else _store(key, run_proof(kind, symbol)))
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/quote":
            try:
                symbol, kind = self._symbol_and_kind(params)
                return self._json(live_quote(kind, symbol))
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/intraday":
            try:
                symbol, kind = self._symbol_and_kind(params)
                tf = (params.get("tf", ["wide"])[0]).lower()
                return self._json(fetch_intraday(kind, symbol, tf))
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/chart-overlay":
            try:
                symbol, kind = self._symbol_and_kind(params)
                return self._json(chart_overlay(kind, symbol))
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/dca":
            if not _enabled("dca"):
                return self._json({"locked": True, "upgrade": config.UPGRADE_URL,
                                   "error": "The DCA Wizard is a Pro feature."}, code=402)
            try:
                symbol, kind = self._symbol_and_kind(params)
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
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/options":
            if not _enabled("options"):
                return self._json({"locked": True, "upgrade": config.UPGRADE_URL,
                                   "error": "The options engine is a Pro feature."}, code=402)
            try:
                symbol = clean_symbol(params.get("symbol", [""])[0])
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
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/probe-scan":
            if not _enabled("options"):
                return self._json({"locked": True, "upgrade": config.UPGRADE_URL,
                                   "error": "Probe scan is a Pro feature."}, code=402)
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
            except InvalidSymbol as exc:
                return self._json({"error": str(exc)}, code=400)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

        if path == "/api/search":
            try:
                q = (params.get("q", [""])[0]).strip()
                if len(q) < 1:
                    return self._json({"query": "", "results": []})
                # Bounded so the upstream lookup and the cache key stay small.
                return self._json({"query": q, "results": search_symbols(q[:64])})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": self._upstream_failed(path, exc)}, code=502)

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
            ".json": "application/json",
            ".webmanifest": "application/manifest+json",
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
