"""Options chain + Greeks — pure Python standard library.

Source: CBOE's free delayed-quotes JSON (no key, no auth). It carries the full
chain (strike, bid/ask, last, open interest, volume), market IMPLIED VOLATILITY,
and vendor GREEKS (delta/gamma/theta/vega/rho). For any contract CBOE leaves
ungraded we fall back to a Black-Scholes-Merton computation from the IV. Data is
delayed (~15 min); educational, not a live trading terminal and not advice.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import re
import urllib.request

RISK_FREE = 0.04
_HEADERS = {"User-Agent": "Mozilla/5.0 MarketPulse"}
_OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
_CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{}.json"


def _get(url: str):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---- Black-Scholes fallback (only used when CBOE omits a contract's greeks) ----
def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def greeks(spot, strike, t_years, sigma, kind, r=RISK_FREE, q=0.0) -> dict:
    """Black-Scholes-Merton Greeks; theta per-day, vega/rho per 1-point move."""
    if min(spot, strike, t_years, sigma) <= 0:
        return {}
    srt = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r - q + sigma * sigma / 2) * t_years) / srt
    d2 = d1 - srt
    pdf = _norm_pdf(d1)
    dq, dr = math.exp(-q * t_years), math.exp(-r * t_years)
    if kind == "call":
        delta = dq * _norm_cdf(d1)
        theta = (-spot * dq * pdf * sigma / (2 * math.sqrt(t_years))
                 - r * strike * dr * _norm_cdf(d2) + q * spot * dq * _norm_cdf(d1)) / 365
        rho = strike * t_years * dr * _norm_cdf(d2) / 100
    else:
        delta = -dq * _norm_cdf(-d1)
        theta = (-spot * dq * pdf * sigma / (2 * math.sqrt(t_years))
                 + r * strike * dr * _norm_cdf(-d2) - q * spot * dq * _norm_cdf(-d1)) / 365
        rho = -strike * t_years * dr * _norm_cdf(-d2) / 100
    gamma = dq * pdf / (spot * srt)
    vega = spot * dq * pdf * math.sqrt(t_years) / 100
    return {"delta": round(delta, 3), "gamma": round(gamma, 4),
            "theta": round(theta, 3), "vega": round(vega, 3), "rho": round(rho, 3)}


def _contract(o: dict, spot: float, expiry_date: _dt.date, kind: str) -> dict:
    strike = o["__strike"]
    iv = o.get("iv") or 0.0
    g = {k: o.get(k) for k in ("delta", "gamma", "theta", "vega", "rho")
         if o.get(k) is not None}
    if len(g) < 5 and iv > 0:  # backfill any missing greeks with Black-Scholes
        t = max((expiry_date - _dt.date.today()).days / 365.0, 1e-6)
        g = {**greeks(spot, strike, t, iv, kind), **g}
    return {
        "strike": strike,
        "bid": o.get("bid"), "ask": o.get("ask"), "last": o.get("last_trade_price"),
        "iv": round(iv * 100, 1) if iv else None,
        "delta": g.get("delta"), "gamma": g.get("gamma"), "theta": g.get("theta"),
        "vega": g.get("vega"), "rho": g.get("rho"),
        "oi": o.get("open_interest"), "vol": o.get("volume"),
        "itm": (strike < spot) if kind == "call" else (strike > spot),
    }


def chain(symbol: str, expiry: str | None = None) -> dict:
    """One expiry's calls+puts (IV + greeks) plus all available expirations.
    `expiry` is a 'YYYY-MM-DD' string; None picks the nearest upcoming date."""
    try:
        data = _get(_CBOE.format(symbol.upper())).get("data") or {}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"chain fetch failed: {exc}"}
    opts = data.get("options") or []
    if not opts:
        return {"error": f"no options data for {symbol.upper()}"}
    spot = data.get("current_price") or data.get("close") or 0
    by_exp: dict[str, dict] = {}
    for o in opts:
        m = _OCC.match(o.get("option", ""))
        if not m:
            continue
        _, ymd, cp, strike = m.groups()
        exp = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}"
        o["__strike"] = int(strike) / 1000.0
        bucket = by_exp.setdefault(exp, {"call": [], "put": []})
        bucket["call" if cp == "C" else "put"].append(o)
    expirations = sorted(by_exp)
    if not expirations:
        return {"error": f"no parseable contracts for {symbol.upper()}"}
    today = _dt.date.today().isoformat()
    # Default to the nearest expiry AFTER today — 0DTE chains are too thin to
    # build clean spreads. The user can still pick today from the dropdown.
    target = expiry if expiry in by_exp else next(
        (e for e in expirations if e > today),
        next((e for e in expirations if e >= today), expirations[0]))
    ed = _dt.date.fromisoformat(target)
    calls = sorted((_contract(o, spot, ed, "call") for o in by_exp[target]["call"]),
                   key=lambda c: c["strike"])
    puts = sorted((_contract(o, spot, ed, "put") for o in by_exp[target]["put"]),
                  key=lambda c: c["strike"])
    return {
        "symbol": symbol.upper(), "spot": round(spot, 2),
        "expiry": target, "expirations": expirations,
        "dte": (ed - _dt.date.today()).days,
        "calls": calls, "puts": puts, "source": "CBOE delayed",
    }


def _nearest_by_delta(legs, target_abs_delta):
    cand = [c for c in legs if c.get("delta") is not None and c.get("strike")]
    return min(cand, key=lambda c: abs(abs(c["delta"]) - target_abs_delta)) if cand else None


def suggest_strangle(ch: dict, wing_delta: float = 0.20) -> dict | None:
    """Long strangle for a coiled / either-way setup: buy an OTM call (~+wing_delta)
    and an OTM put (~-wing_delta). Profits on a big move in EITHER direction; the
    max loss is the combined debit, and it needs to clear a breakeven to pay. Returns
    both strikes, total debit, both breakevens, and the % move to each."""
    if ch.get("error"):
        return None
    spot = ch.get("spot") or 0
    call = _nearest_by_delta([c for c in ch["calls"] if (c.get("strike") or 0) >= spot], wing_delta)
    put = _nearest_by_delta([p for p in ch["puts"] if (p.get("strike") or 0) <= spot], wing_delta)
    if not call or not put or not spot:
        return None
    call_cost = call.get("ask") or call.get("last") or 0
    put_cost = put.get("ask") or put.get("last") or 0
    debit = round(call_cost + put_cost, 2)
    if debit <= 0:
        return None
    upper_be = round(call["strike"] + debit, 2)
    lower_be = round(put["strike"] - debit, 2)
    return {
        "type": "long strangle",
        "call": {"strike": call["strike"], "delta": call["delta"]},
        "put": {"strike": put["strike"], "delta": put["delta"]},
        "debit": debit,
        "per_contract": round(debit * 100, 2),
        "max_loss": debit,
        "upper_breakeven": upper_be,
        "lower_breakeven": lower_be,
        "move_up_pct": round((upper_be - spot) / spot * 100, 1),
        "move_down_pct": round((spot - lower_be) / spot * 100, 1),
    }


def suggest_spread(ch: dict, direction: str,
                   long_delta: float = 0.40, short_delta: float = 0.25) -> dict | None:
    """Build a vertical DEBIT spread for `direction` ('call'=bullish, 'put'=bearish)
    from a chain() result. Long leg ~long_delta, short leg ~short_delta further OTM.
    Delta-based selection naturally yields the correct strikes (calls: buy lower /
    sell higher; puts: buy higher / sell lower). Returns leg strikes + the math, or
    None if the chain can't form a sane spread."""
    if direction not in ("call", "put") or ch.get("error"):
        return None
    legs = ch["calls"] if direction == "call" else ch["puts"]
    long_leg = _nearest_by_delta(legs, long_delta)
    short_leg = _nearest_by_delta(legs, short_delta)
    if not long_leg or not short_leg or long_leg["strike"] == short_leg["strike"]:
        return None
    long_cost = long_leg.get("ask") or long_leg.get("last") or 0
    short_credit = short_leg.get("bid") or short_leg.get("last") or 0
    debit = round(long_cost - short_credit, 2)
    width = round(abs(long_leg["strike"] - short_leg["strike"]), 2)
    if debit <= 0 or width <= 0:
        return None
    max_profit = round(width - debit, 2)
    breakeven = round(long_leg["strike"] + (debit if direction == "call" else -debit), 2)
    rr = round(max_profit / debit, 2) if debit else None
    return {
        "type": f"{direction} debit spread",
        "direction": direction,
        "long": {"strike": long_leg["strike"], "delta": long_leg["delta"]},
        "short": {"strike": short_leg["strike"], "delta": short_leg["delta"]},
        "debit": debit,                 # net cost per share
        "per_contract": round(debit * 100, 2),
        "width": width,
        "max_profit": max_profit,       # per share
        "max_loss": debit,              # per share (= the debit)
        "breakeven": breakeven,
        "risk_reward": rr,
    }


def direction_nudge(ch: dict) -> dict | None:
    """Plain-English 'which way the data leans' banner. States the direction a
    seasoned trader would lean — explicitly framed as a read, NOT an order. The
    decision stays with the user."""
    lean = ch.get("lean")
    if not lean:
        return None
    label = lean.get("label", "NEUTRAL")
    direction = lean.get("direction")
    if ch.get("either_way"):
        return {"dir": "either-way", "icon": "⟁", "headline": "A MOVE IS COMING — direction unclear",
                "text": "The data says a big move is loading but not which way. The way a pro plays this "
                        "is non-directional — a strangle — or simply waits for the break. A read, not a "
                        "directive. The choice is yours."}
    if direction == "call":
        return {"dir": "bullish", "icon": "📈", "headline": "The data leans BULLISH (up)",
                "text": f"Signal is {label}. The way a seasoned trader would lean here is UP — that's the "
                        "call side (e.g. the call debit spread below). It's a lean from the data, not a "
                        "directive. The choice is yours."}
    if direction == "put":
        return {"dir": "bearish", "icon": "📉", "headline": "The data leans BEARISH (down)",
                "text": f"Signal is {label}. The way a seasoned trader would lean here is DOWN — that's the "
                        "put side (e.g. the put debit spread below). It's a lean from the data, not a "
                        "directive. The choice is yours."}
    return {"dir": "stand-aside", "icon": "🧘", "headline": "No clean direction",
            "text": "The data doesn't lean a clear way and nothing's coiled. The way a pro plays this is "
                    "often patience — no trade. Cash is a position. Entirely your call."}


def decision_read(ch: dict, sig: dict) -> dict | None:
    """Turn the live numbers into a plain-English, step-by-step decision read:
    Trend -> Coil -> Signal -> Volatility -> The play -> The catch, plus the
    non-negotiable risk rules. This explains HOW TO THINK, not what to buy."""
    if ch.get("error") or not sig:
        return None
    spot = ch.get("spot") or 0
    calls = ch.get("calls") or []
    atm_iv = None
    if calls and spot:
        atm = min(calls, key=lambda c: abs((c.get("strike") or 0) - spot))
        atm_iv = atm.get("iv")
    label = sig.get("label", "NEUTRAL")
    rsi = sig.get("rsi")
    reasons = sig.get("reasons", [])
    htf = sig.get("htf", 0)
    sq = ch.get("squeeze") or {}
    wk, bw = sq.get("weekly"), sq.get("biweekly")
    coiled, conflict = sq.get("coiled"), sq.get("conflict")
    either = ch.get("either_way")
    dte = ch.get("dte")

    up = any(("above SMA50" in r) or ("uptrend" in r) or ("golden cross" in r) for r in reasons)
    down = any(("below SMA50" in r) or ("downtrend" in r) or ("death cross" in r) for r in reasons)
    if up and not down and htf >= 0:
        trend = "Uptrend — price is above its trend average and the higher timeframe agrees. Buyers are in control."
    elif down and not up:
        trend = "Downtrend — price is below its trend average; rallies are suspect until that flips."
    else:
        trend = "Mixed / choppy — no clean trend, the averages are tangled. Hardest tape to trade."

    if coiled:
        which = []
        if wk and wk["state"] == "on":
            which.append(f"weekly ({wk['bars']} bars)")
        if bw and bw["state"] == "on":
            which.append(f"bi-weekly ({bw['bars']} bars)")
        dirw = "direction unresolved" if (either or conflict) else "leaning with the trend"
        coil = (f"Coiled — the {' & '.join(which)} squeeze is ON. Volatility is compressed and a "
                f"breakout is loading ({dirw}). 'On' means energy building, not up.")
    else:
        coil = "Not coiled — volatility has already expanded. It's moving, not winding up; no spring to release."

    signal = f"Composite signal reads {label}" + (f" (RSI {rsi})." if rsi is not None else ".")

    if atm_iv is None:
        vol = "Implied volatility unavailable for this expiry."
    else:
        regime = "a BIG" if atm_iv >= 60 else "a moderate" if atm_iv >= 35 else "a modest"
        vol = (f"ATM implied vol is {atm_iv}% — the market is pricing in {regime} expected move. "
               "High IV = options are EXPENSIVE (favor spreads / selling premium); low IV = cheap "
               "(favor buying). No IV-rank yet, so that's the raw level, not cheap-vs-rich vs history.")

    if ch.get("strangle") and either:
        s = ch["strangle"]
        play = (f"Direction is unresolved on a coil → a LONG STRANGLE plays the break EITHER way. "
                f"It needs roughly +{s['move_up_pct']}% or −{s['move_down_pct']}% to clear a breakeven; "
                f"max loss is the ${s['per_contract']} debit. Size it like a lotto, not a core bet.")
    elif ch.get("spread"):
        s = ch["spread"]
        side = "call (bullish)" if s["direction"] == "call" else "put (bearish)"
        play = (f"The lean is {side} → a {s['type'].upper()}: buy {s['long']['strike']} / sell "
                f"{s['short']['strike']}. Defined risk ${s['per_contract']} to make up to "
                f"${round(s['max_profit'] * 100)} (R:R {s['risk_reward']}).")
        if ch.get("strangle"):
            play += " A strangle is also on the table since it's coiled, if you'd rather not pick a side."
    else:
        play = ("No clean directional edge and no coil — the disciplined move here is often NO trade. "
                "Cash is a position; you don't have to swing at every pitch.")

    catch = []
    if dte is not None and dte <= 2:
        catch.append(f"This expiry is {dte} DTE — time decay (theta) is brutal; only sensible if you "
                     "expect the move in the next day or two.")
    if coiled and bw and bw["state"] == "on" and dte is not None and dte < 14:
        catch.append("The coil is on the BI-WEEKLY timeframe (a multi-week setup) but this expiry is "
                     "short — use a later expiry so the breakout has time to happen.")
    if not catch:
        catch.append("Match the expiry to your timeframe — too short and decay kills you, too long and "
                     "you overpay for time.")

    if ch.get("strangle") and either:
        bottom = "The disciplined read: play the breakout either way (strangle), sized like a lotto."
    elif ch.get("spread"):
        d = "call" if ch["spread"]["direction"] == "call" else "put"
        bottom = f"The disciplined read: a defined-risk {d} debit spread — IF you take the trade."
    else:
        bottom = "The disciplined read: stand aside until there's an edge."

    return {
        "steps": [
            {"k": "1 · Trend", "v": trend},
            {"k": "2 · Coil", "v": coil},
            {"k": "3 · Signal", "v": signal},
            {"k": "4 · Volatility", "v": vol},
            {"k": "5 · The play", "v": play},
            {"k": "6 · The catch", "v": " ".join(catch)},
        ],
        "risk": [
            "Your MAX LOSS is the debit — never put in more than you can lose entirely.",
            "Size small: one options trade should be a tiny slice of the account, not a hero bet.",
            "Check the earnings date before this expiry — an IV crush can sink a correct trade.",
        ],
        "bottom_line": bottom,
        "disclaimer": "This is a way to READ the data, not a recommendation. You make the call with your money.",
    }


def probe_plan(ch: dict, pot: float = 300, probe_frac: float = 0.20,
               min_delta: float = 0.25) -> dict | None:
    """The $X-pot Probe→Read→Escalate sizer, scaled to the stock's ACTUAL price.

    A probe only reveals a usable result if the option actually reacts to a
    normal move — that's governed by DELTA, not a flat dollar. Too far OTM
    (Δ≈0.01) is a dead lottery; Δ≈`min_delta` is the readability floor. So the
    'absolute most affordable usable probe' = the CHEAPEST OTM contract in the
    leaned direction whose |delta| ≥ min_delta. It's a single directional option
    (the lean picks the side) — no straddle needed. Qualifies for the pot if that
    probe costs ≤ probe_frac of the pot (20% → $60 on $300)."""
    lean = ch.get("lean") or {}
    direction = lean.get("direction")
    spot = ch.get("spot") or 0
    if not spot:
        return None
    budget = round(pot * probe_frac)
    if not direction:
        return {"pot": pot, "budget": budget, "qualifies": None,
                "note": "No directional lean right now — the probe needs a side to point at. "
                        "Wait for a lean rather than straddling (two sides doubles your cost)."}
    legs = ch["calls"] if direction == "call" else ch["puts"]
    otm = [c for c in legs
           if c.get("delta") is not None and (c.get("ask") or 0) > 0
           and ((c["strike"] > spot) if direction == "call" else (c["strike"] < spot))
           and abs(c["delta"]) >= min_delta]
    if not otm:
        return {"pot": pot, "budget": budget, "qualifies": False, "direction": direction,
                "note": f"No strike clears the readability floor (Δ≥{min_delta}) in this expiry."}
    p = min(otm, key=lambda c: (c.get("ask") or c.get("last")))
    cost = round((p.get("ask") or p.get("last")) * 100)
    move = round(abs(p["strike"] - spot) / spot * 100, 1)
    qualifies = cost <= budget
    plan = {
        "pot": pot, "budget": budget, "direction": direction, "min_delta": min_delta,
        "probe": {"strike": p["strike"], "cost": cost,
                  "delta": round(p["delta"], 2), "move_pct": move},
        "qualifies": qualifies,
        "min_pot": round(cost / probe_frac),
    }
    if qualifies:
        per_leg = round((pot - cost) / 2)
        aff = [c for c in legs
               if c.get("delta") is not None and (c.get("ask") or 0) > 0
               and ((c["strike"] >= spot) if direction == "call" else (c["strike"] <= spot))
               and (c.get("ask") or 0) * 100 <= per_leg]
        if aff:
            e = max(aff, key=lambda c: abs(c["delta"]))  # closest-to-money you can afford
            plan["escalate"] = {"strike": e["strike"],
                                "cost_each": round((e.get("ask") or e.get("last")) * 100),
                                "delta": round(e["delta"], 2)}
    return plan
