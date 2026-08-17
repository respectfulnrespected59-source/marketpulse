"""Options paper positions — the honest cost of a multi-leg trade.

`options.py` reads a chain and suggests a spread. It stops there, which left
the app in an awkward place: it would argue you into a put debit spread and
then have nowhere to prove the idea. This module is the missing half — the
position model and the live mark that make an options paper record possible.

Everything here is pure math over plain dicts. No network, no clock reads
except where a date is explicitly passed in, no storage. The browser keeps
the record; this decides what the record should say.

WHY THE FILL RULES ARE SO BLUNT
-------------------------------
`backtest.py` charges stocks 5bps of slippage because a fill at the mid price
flatters itself. On options that understates the problem badly. A TSLA put
quoting 4.20 bid / 4.30 ask has a 2.4% spread, and a two-leg vertical crosses
it FOUR times on a round trip. Mark that book at mid and a strategy that
bleeds money reads as profitable — which is precisely how someone talks
themselves into sizing up.

So: buying pays the ask, selling receives the bid, marking uses the price you
would really close at, and commission is charged per leg per contract in both
directions. Every rule here costs the paper trader money, on purpose. If a
strategy still shows an edge after all of it, the edge might be real.
"""
from __future__ import annotations

import datetime as _dt

# One contract controls 100 shares. Every dollar figure in this module runs
# through this, and forgetting it is the classic 100x options error.
CONTRACT_MULTIPLIER = 100

# Per leg, per contract, each way. Roughly the retail standard; a two-leg
# vertical therefore costs 4 x this over a full round trip.
COMMISSION_PER_CONTRACT = 0.65


class Unfillable(Exception):
    """A leg had no usable quote, so the position cannot be priced.

    Raised rather than skipping the leg: half a vertical is a naked option
    with completely different risk, and silently opening one would be the
    worst bug this module could have.
    """


# ----------------------------------------------------------------- fills

def fill_price(quote: dict, action: str) -> float | None:
    """The price this side of the trade really fills at.

    buy -> the ask. sell -> the bid. Never the mid, never the last trade.
    Returns None when that side of the book is empty, because a missing bid
    means nobody is buying and pretending otherwise invents liquidity.
    """
    if not isinstance(quote, dict):
        return None
    raw = quote.get("ask") if action == "buy" else quote.get("bid")
    try:
        px = float(raw)
    except (TypeError, ValueError):
        return None
    # A zero or negative quote is not a price, it is an empty book.
    return px if px > 0 else None


def leg_action(side: str, phase: str) -> str:
    """What you do to this leg — 'buy' or 'sell'.

    A long leg is bought to open and sold to close; a short leg is the
    reverse. Both directions land on the unfavourable side of the spread,
    which is the point.
    """
    opening = phase == "open"
    if side == "long":
        return "buy" if opening else "sell"
    return "sell" if opening else "buy"


def _leg_key(leg: dict) -> tuple:
    return (leg.get("right"), float(leg.get("strike")))


# ------------------------------------------------------------- opening

def open_position(symbol: str, expiry: str, legs: list[dict],
                  contracts: int = 1, opened: float | None = None) -> dict:
    """Price a new multi-leg position at real fills.

    `legs` are dicts of {right, strike, side, quote}. The returned position
    carries the price every leg actually filled at, so the record can never
    drift back toward the mid later.

    entry_debit is per share and signed: positive is a debit (cash out),
    negative is a credit (cash in).
    """
    if not legs:
        raise ValueError("a position needs at least one leg")
    n = int(contracts)
    if n < 1:
        raise ValueError("contracts must be at least 1")

    priced: list[dict] = []
    net = 0.0
    for leg in legs:
        action = leg_action(leg.get("side", "long"), "open")
        px = fill_price(leg.get("quote") or {}, action)
        if px is None:
            raise Unfillable(
                f"{leg.get('right')} {leg.get('strike')} has no "
                f"{'ask' if action == 'buy' else 'bid'} "
                f"— refusing to open a partial position"
            )
        # Paying adds to the debit, receiving subtracts from it.
        net += px if action == "buy" else -px
        priced.append({
            "right": leg.get("right"),
            "strike": float(leg.get("strike")),
            "side": leg.get("side", "long"),
            "qty": n,
            "entry": px,
        })

    entry_debit = round(net, 2)
    commission = round(COMMISSION_PER_CONTRACT * len(priced) * n, 2)
    return {
        "symbol": str(symbol).upper(),
        "expiry": expiry,
        "contracts": n,
        "legs": priced,
        "entry_debit": entry_debit,
        "cost_usd": round(entry_debit * CONTRACT_MULTIPLIER * n + commission, 2),
        "commission": commission,
        "opened": opened,
    }


# ------------------------------------------------------------- marking

def mark_value(position: dict, chain: dict) -> float | None:
    """What the position is worth per share if closed right now.

    `chain` maps (right, strike) -> quote. Closing sells the longs at their
    bid and buys the shorts back at their ask — the unfavourable side, again.

    Returns None if ANY leg is unquoted. A partial mark is worse than no
    mark: it is how a losing book comes to look flat.
    """
    net = 0.0
    for leg in position.get("legs") or []:
        action = leg_action(leg.get("side", "long"), "close")
        px = fill_price(chain.get(_leg_key(leg)) or {}, action)
        if px is None:
            return None
        net += px if action == "sell" else -px
    return round(net, 2)


def position_pnl(position: dict, chain: dict) -> dict:
    """Open P&L at the current mark, gross and net of every commission.

    net_usd charges BOTH the commission already paid to open and the one it
    would cost to close. That is the number that matters, because a position
    you cannot exit is not a profit.
    """
    n = int(position.get("contracts") or 1)
    mark = mark_value(position, chain)
    if mark is None:
        return {"mark": None, "gross_usd": None, "net_usd": None,
                "pct_of_max": None, "unquoted": True}

    gross = round((mark - float(position["entry_debit"])) * CONTRACT_MULTIPLIER * n, 2)
    exit_commission = round(
        COMMISSION_PER_CONTRACT * len(position.get("legs") or []) * n, 2)
    net = round(gross - float(position.get("commission") or 0) - exit_commission, 2)

    best = max_profit_usd(position)
    return {
        "mark": mark,
        "gross_usd": gross,
        "net_usd": net,
        "exit_commission": exit_commission,
        "pct_of_max": round(gross / best * 100, 1) if best else None,
        "unquoted": False,
    }


def net_greeks(position: dict, chain: dict) -> dict:
    """Position-level greeks — longs add, shorts subtract, scaled by contracts.

    Net theta is the one to watch on a short-dated spread: the short leg pays
    for most of the long leg's decay, and that difference is the whole reason
    to trade a vertical instead of a naked long option.
    """
    out = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    seen = False
    n = int(position.get("contracts") or 1)
    for leg in position.get("legs") or []:
        q = chain.get(_leg_key(leg)) or {}
        sign = 1 if leg.get("side", "long") == "long" else -1
        for g in out:
            try:
                out[g] += sign * float(q[g]) * n
            except (KeyError, TypeError, ValueError):
                continue
            seen = True
    return {k: round(v, 4) for k, v in out.items()} if seen else {}


# ------------------------------------------------- the shape of the risk

def _long_leg(position: dict) -> dict | None:
    return next((l for l in position.get("legs") or []
                 if l.get("side") == "long"), None)


def spread_width(position: dict) -> float | None:
    """Distance between the two strikes of a vertical."""
    legs = position.get("legs") or []
    if len(legs) != 2:
        return None
    return round(abs(float(legs[0]["strike"]) - float(legs[1]["strike"])), 4)


def max_loss_usd(position: dict) -> float | None:
    """Worst case in dollars.

    On a debit spread that is simply the debit — which is the entire appeal.
    On a credit spread it is the width minus the credit taken in.
    """
    n = int(position.get("contracts") or 1)
    debit = float(position.get("entry_debit") or 0)
    if debit > 0:
        return round(debit * CONTRACT_MULTIPLIER * n, 2)
    width = spread_width(position)
    if width is None:
        return None
    return round((width + debit) * CONTRACT_MULTIPLIER * n, 2)


def max_profit_usd(position: dict) -> float | None:
    """Best case in dollars: width minus the debit, or the credit received."""
    n = int(position.get("contracts") or 1)
    debit = float(position.get("entry_debit") or 0)
    width = spread_width(position)
    if debit <= 0:
        return round(-debit * CONTRACT_MULTIPLIER * n, 2)
    if width is None:
        return None
    return round((width - debit) * CONTRACT_MULTIPLIER * n, 2)


def breakeven(position: dict) -> float | None:
    """Where the underlying has to be at expiry to get the debit back.

    Puts break even BELOW the long strike, calls ABOVE it.
    """
    long_leg = _long_leg(position)
    if not long_leg:
        return None
    debit = float(position.get("entry_debit") or 0)
    strike = float(long_leg["strike"])
    return round(strike - debit if long_leg.get("right") == "put"
                 else strike + debit, 4)


def risk_reward(position: dict) -> float | None:
    """Max profit per dollar risked."""
    best, worst = max_profit_usd(position), max_loss_usd(position)
    if not best or not worst:
        return None
    return round(best / worst, 4)


# ------------------------------------------------------------- expiry

def intrinsic(right: str, strike: float, spot: float) -> float:
    """What the contract is worth at expiry — no time value left to argue about."""
    if right == "put":
        return round(max(float(strike) - float(spot), 0.0), 4)
    return round(max(float(spot) - float(strike), 0.0), 4)


def settle(position: dict, spot: float) -> dict:
    """Settle the position at expiry against the underlying.

    No closing commission is charged: letting a spread expire really is the
    cheaper exit, and the ledger should reflect that rather than inventing a
    fee. (In the real world an in-the-money short leg can be assigned, which
    does cost — worth surfacing before anyone trades this for money.)
    """
    n = int(position.get("contracts") or 1)
    net = 0.0
    for leg in position.get("legs") or []:
        v = intrinsic(leg.get("right"), leg["strike"], spot)
        net += v if leg.get("side", "long") == "long" else -v

    value = round(net, 4)
    gross = round((value - float(position["entry_debit"])) * CONTRACT_MULTIPLIER * n, 2)
    return {
        "value": value,
        "gross_usd": gross,
        "net_usd": round(gross - float(position.get("commission") or 0), 2),
        "spot": spot,
        "why": "expired",
    }


def _as_date(value) -> _dt.date:
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value))


def is_expired(expiry: str, today=None) -> bool:
    """True only AFTER expiry day.

    Expiry day itself is a full trading session, so settling it at the open
    would report a result the trader never actually got.
    """
    now = _as_date(today) if today is not None else _dt.date.today()
    return _as_date(expiry) < now


def days_to_expiry(expiry: str, today=None) -> int:
    """Calendar days remaining — the number that makes theta frightening."""
    now = _as_date(today) if today is not None else _dt.date.today()
    return (_as_date(expiry) - now).days


def chain_index(chain: dict) -> dict:
    """Turn an /api/options payload into the (right, strike) -> quote map
    that mark_value and net_greeks expect."""
    out: dict[tuple, dict] = {}
    for right, key in (("call", "calls"), ("put", "puts")):
        for c in chain.get(key) or []:
            try:
                out[(right, float(c["strike"]))] = {**c, "right": right}
            except (KeyError, TypeError, ValueError):
                continue
    return out
