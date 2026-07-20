"""Alpaca broker client — pure stdlib REST (no alpaca-py, no pip).

Defaults to the PAPER endpoint. Keys come exclusively from the environment
(MP_ALPACA_KEY_ID / MP_ALPACA_SECRET); they are never read from disk or logged.

Only the few endpoints the agent needs:
  account()            equity / buying power / status
  positions()          open positions
  position(symbol)     one position or None
  submit_order(...)    place a notional market order (buy or sell/close)
  clock()              market open/closed (stocks; crypto trades 24/7)

This is a thin transport. ALL safety decisions live in guardrails.py — the
broker just does what it's told once a request has been authorized.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import config


class BrokerError(Exception):
    pass


class AuthError(BrokerError):
    pass


def _headers() -> dict:
    if not config.keys_present():
        raise AuthError(
            "Alpaca keys not set. Export MP_ALPACA_KEY_ID and MP_ALPACA_SECRET "
            "(see agent/.env.example).")
    return {
        "APCA-API-KEY-ID": config.ALPACA_KEY_ID,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET,
        "Content-Type": "application/json",
        "User-Agent": "MarketPulseAgent/1.0",
    }


# --------------------------------------------------------------- key scoping
# Alpaca has no "trade-only" API key toggle (unlike Binance/Coinbase, where you
# can mint a key with withdrawals disabled). So we enforce the equivalent HERE,
# at our own chokepoint: an explicit allowlist of the endpoints this agent
# legitimately needs. Anything else -- account configuration changes, transfers,
# journals, bulk position closes -- is refused before the request is built, even
# if a bug or a tampered caller asks for it.
#
# Same principle as guardrails.check_symbol_allowed: do not trust the caller.
# Exact paths only -- a prefix rule here would also admit sub-resources such as
# /v2/account/configurations and /v2/account/activities, which we do not want.
_ALLOWED_EXACT = (
    ("GET",  "/v2/account"),        # equity + buying power
    ("GET",  "/v2/positions"),      # all open positions
    ("GET",  "/v2/clock"),          # market open/closed
    ("POST", "/v2/orders"),         # the ONLY write this agent may perform
)
# Prefixes, for paths that legitimately carry a symbol segment.
_ALLOWED_PREFIX = (
    ("GET", "/v2/positions/"),      # a single position, /v2/positions/AAPL
    ("GET", "/v2/stocks/"),         # market data (data base)
    ("GET", "/v2/crypto/"),         # market data (data base)
)


class DisallowedEndpointError(AuthError):
    """The agent tried to call an Alpaca endpoint outside its allowlist."""


def _assert_allowed(method: str, path: str) -> None:
    base = path.split("?", 1)[0]
    if (method, base) in _ALLOWED_EXACT:
        return
    for m, p in _ALLOWED_PREFIX:
        if method == m and base.startswith(p) and len(base) > len(p):
            return
    raise DisallowedEndpointError(
        f"{method} {base} is not in the agent's endpoint allowlist. "
        "This agent may read the account and submit orders; it may not move "
        "money, change account configuration, or close positions in bulk.")


def _request(method: str, path: str, body: dict | None = None, base: str | None = None):
    _assert_allowed(method, path)
    url = (base or config.ALPACA_BASE) + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code in (401, 403):
            raise AuthError(f"Alpaca auth failed ({exc.code}): {detail}") from exc
        raise BrokerError(f"Alpaca {method} {path} -> {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BrokerError(f"Network error reaching Alpaca: {exc.reason}") from exc


# ----------------------------------------------------------------- reads
def account() -> dict:
    return _request("GET", "/v2/account")


def positions() -> list[dict]:
    return _request("GET", "/v2/positions")


def position(symbol: str) -> dict | None:
    # Alpaca position symbols drop the slash for crypto (BTC/USD -> BTCUSD).
    sym = symbol.replace("/", "")
    try:
        return _request("GET", f"/v2/positions/{sym}")
    except BrokerError as exc:
        if "404" in str(exc):
            return None
        raise


def clock() -> dict:
    return _request("GET", "/v2/clock")


def latest_price(symbol: str) -> float:
    """Authoritative live last-trade price from Alpaca's market-data API.

    Pulled fresh (never from the dashboard's cache) so the slippage guard
    compares the proposal's reference price against what the market is doing
    *right now*. Raises BrokerError if the price can't be obtained — callers
    must treat that as fail-closed (refuse the send), per the security skill's
    "simulate before send" / mandatory min_amount_out rule.
    """
    if "/" in symbol:  # crypto pair, e.g. BTC/USD
        path = "/v1beta3/crypto/us/latest/trades?symbols=" + symbol
        data = _request("GET", path, base=config.ALPACA_DATA_BASE)
        trade = (data.get("trades") or {}).get(symbol)
    else:  # stock ticker
        path = f"/v2/stocks/{symbol}/trades/latest"
        data = _request("GET", path, base=config.ALPACA_DATA_BASE)
        trade = data.get("trade")
    price = float((trade or {}).get("p", 0) or 0)
    if price <= 0:
        raise BrokerError(f"No live price for {symbol} (got {data!r})")
    return price


# ----------------------------------------------------------------- writes
def submit_order(symbol: str, side: str, notional: str | None = None,
                 qty: str | None = None) -> dict:
    """Place a market order. Crypto is GTC; stocks are DAY.

    Exactly one of `notional` (dollar amount) or `qty` (units) must be given.
    Buys use notional; sells/closes typically use qty (the full position).
    """
    if (notional is None) == (qty is None):
        raise BrokerError("Provide exactly one of notional or qty")

    is_crypto = "/" in symbol
    order = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "time_in_force": "gtc" if is_crypto else "day",
    }
    if notional is not None:
        order["notional"] = str(notional)
    else:
        order["qty"] = str(qty)
    return _request("POST", "/v2/orders", body=order)
