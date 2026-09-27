"""Alpaca broker client — pure stdlib REST (no alpaca-py, no pip).

Keys come from credentials.load() at REQUEST time (env vars, or the
owner-only agent/data/alpaca.json the app writes); they are never logged. The
paper or live base URL follows the keys' mode, so paper keys can never place a
live order by accident (and Alpaca would reject them there anyway).

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
import re
import urllib.error
import urllib.request

import agent_config as config
import credentials

PAPER_BASE = "https://paper-api.alpaca.markets"
LIVE_BASE = "https://api.alpaca.markets"


class BrokerError(Exception):
    pass


class AuthError(BrokerError):
    pass


def _creds(creds: "credentials.Credentials | None" = None) -> "credentials.Credentials":
    creds = creds or credentials.load()
    if creds is None:
        raise AuthError("Alpaca is not connected. Add your keys in the Trade desk "
                        "(or export MP_ALPACA_KEY_ID / MP_ALPACA_SECRET for the CLI).")
    return creds


def trading_base(creds: "credentials.Credentials") -> str:
    return LIVE_BASE if creds.mode == "live" else PAPER_BASE


def _headers(creds: "credentials.Credentials") -> dict:
    return {
        "APCA-API-KEY-ID": creds.key_id,
        "APCA-API-SECRET-KEY": creds.secret,
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
    # latest_price() for crypto. The old list only had /v2/crypto/, so every
    # crypto approval was refused for "no live price" (fail-safe, but crypto
    # could never trade). Found by tests/test_money_core.py.
    ("GET",  "/v1beta3/crypto/us/latest/trades"),
)
# Reading one order back (its fill) is safe; cancelling or listing-to-cancel is not allowed.
# Prefixes, for paths that legitimately carry a symbol segment.
_ALLOWED_PREFIX = (
    ("GET", "/v2/positions/"),      # a single position, /v2/positions/AAPL
    ("GET", "/v2/orders/"),         # one order's status + fill, /v2/orders/<id>
    ("GET", "/v2/stocks/"),         # market data (data base)
    ("GET", "/v2/crypto/"),         # market data (data base)
)


class DisallowedEndpointError(AuthError):
    """The agent tried to call an Alpaca endpoint outside its allowlist."""


_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SINGLE_SEGMENT = ("/v2/positions/", "/v2/orders/")   # one symbol / one order id, nothing more


def _assert_allowed(method: str, path: str) -> None:
    base = path.split("?", 1)[0]
    # No encoded or relative tricks: "%2F", "..", backslashes never reach a match.
    if "%" in base or "\\" in base or any(seg == ".." for seg in base.split("/")):
        raise DisallowedEndpointError(f"{method} {base} is not a plain Alpaca path.")
    if (method, base) in _ALLOWED_EXACT:
        return
    for m, p in _ALLOWED_PREFIX:
        if method != m or not base.startswith(p) or len(base) <= len(p):
            continue
        segs = base[len(p):].split("/")
        if p in _SINGLE_SEGMENT and len(segs) != 1:
            continue
        if all(_SEGMENT.match(s) for s in segs):
            return
    raise DisallowedEndpointError(
        f"{method} {base} is not in the agent's endpoint allowlist. "
        "This agent may read the account and submit orders; it may not move "
        "money, change account configuration, or close positions in bulk.")


class DuplicateOrderError(BrokerError):
    """Alpaca already has an order with this client_order_id: it must not be resent."""


class NotFoundError(BrokerError):
    """A genuine HTTP 404 (e.g. no position held), never inferred from message text."""


_DUPLICATE_CODE = 40010001


def _is_duplicate(raw: str) -> bool:
    """A repeated client_order_id: Alpaca answers 422 with its duplicate code or a
    message saying the id must be unique. Judged on the parsed body, never a loose
    substring: another 422 that merely mentions the field is NOT a duplicate."""
    try:
        body = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    msg = str(body.get("message", "")).lower()
    return body.get("code") == _DUPLICATE_CODE or ("client_order_id" in msg and "unique" in msg)


def _urlopen_transport(method: str, url: str, headers: dict, body: str | None) -> tuple[int, str]:
    data = body.encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise BrokerError(f"Network error reaching Alpaca: {exc.reason}") from exc


# Swappable so tests can stand in a faithful fake Alpaca; production uses urlopen.
_TRANSPORT = _urlopen_transport


def _request(method: str, path: str, body: dict | None = None, base: str | None = None,
             creds: "credentials.Credentials | None" = None):
    _assert_allowed(method, path)
    creds = _creds(creds)
    url = (base or trading_base(creds)) + path
    status, raw = _TRANSPORT(method, url, _headers(creds),
                             json.dumps(body) if body is not None else None)
    if status < 400:
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise BrokerError(f"Alpaca sent an unreadable reply ({status}): {raw[:120]!r}") from None
    if status in (401, 403):
        raise AuthError(f"Alpaca auth failed ({status}): {raw[:300]}")
    if status == 404:
        raise NotFoundError(f"Alpaca {method} {path} -> 404: {raw[:300]}")
    if status == 422 and _is_duplicate(raw):
        raise DuplicateOrderError(f"Alpaca already has this order: {raw[:300]}")
    raise BrokerError(f"Alpaca {method} {path} -> {status}: {raw[:300]}")


def verify(creds: "credentials.Credentials") -> dict:
    """Check keys against THEIR OWN mode's URL before they are saved: paper keys
    declared as live (or the reverse) fail here, not at the first real order."""
    acct = _request("GET", "/v2/account", creds=creds)
    if acct.get("trading_blocked") or acct.get("account_blocked"):
        raise AuthError("This Alpaca account is blocked from trading.")
    return acct


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
    except NotFoundError:
        return None


def clock() -> dict:
    return _request("GET", "/v2/clock")


def get_order(order_id: str) -> dict:
    return _request("GET", f"/v2/orders/{order_id}")


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
                 qty: str | None = None, client_order_id: str | None = None) -> dict:
    """Place a market order. Crypto is GTC; stocks are DAY.

    Exactly one of `notional` (dollar amount) or `qty` (units) must be given.
    Buys use notional; sells/closes typically use qty (the full position).
    `client_order_id` (the proposal id) makes a resend impossible: Alpaca
    rejects a repeated id with 422, raised here as DuplicateOrderError.
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
    if client_order_id:
        order["client_order_id"] = client_order_id
    return _request("POST", "/v2/orders", body=order)
