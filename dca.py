"""DCA Wizard — the honest 'GROW' engine.

Dollar-cost averaging done three ways, backtested on real history with the same
cost model Proof Mode uses, plus a forward projection. Nothing here is a promise;
it is what each *deployment style* would have done on this asset, after costs.

Three styles, same total budget, so the comparison is apples-to-apples:

  1. PLAIN DCA  — fixed dollars every period, rain or shine. The discipline play.
  2. LUMP SUM   — the whole budget deployed on day one, then held. The benchmark
                  that historically wins ~2/3 of the time (markets rise more than
                  they fall) — we say so out loud instead of hiding it.
  3. TILT DCA   — MarketPulse's edge: the SAME cadence, but each period's buy is
                  nudged up when the live signal engine reads the asset as cheap
                  (bullish composite score) and trimmed when it reads rich. Still
                  always buying — never a market-timing all-or-nothing. Sometimes
                  the engine's 'cheap' gets cheaper; the backtest shows when the
                  tilt actually helped and when it didn't.

The tilt uses ONLY data up to each buy date (closes[:i+1]) — no lookahead. Early
buys before the indicator warmup fall back to a neutral 1.0 tilt.
"""
from __future__ import annotations

import backtest
import indicators

# Bars per contribution period, per market. Stocks trade ~5 days/week (Yahoo
# daily bars skip weekends); CoinGecko crypto history is one calendar-day bar.
CADENCE_BARS = {
    "weekly": {"stock": 5, "crypto": 7},
    "biweekly": {"stock": 10, "crypto": 14},
    "monthly": {"stock": 21, "crypto": 30},
}
PERIODS_PER_YEAR = {"weekly": 52, "biweekly": 26, "monthly": 12}

# Tilt bounds: a period's buy can swing to half or 1.5x the base contribution,
# never to zero (it is still DCA, not timing). Score spans roughly -6..+6.
MIN_TILT, MAX_TILT = 0.5, 1.5
SCORE_SPAN = 6.0

# Forward-projection scenarios (assumed constant annual return — an assumption,
# NOT a forecast). Kept deliberately spread so no single number reads as a promise.
PROJECTION_RATES = {"bear": 0.0, "base": 0.07, "bull": 0.12}


def _norm_kind(kind: str) -> str:
    return "crypto" if kind == "crypto" else "stock"


def bars_per_period(cadence: str, kind: str) -> int:
    return CADENCE_BARS.get(cadence, CADENCE_BARS["monthly"])[_norm_kind(kind)]


def per_period_amount(monthly: float, cadence: str) -> float:
    """Convert a monthly budget into a per-contribution amount, holding the
    ANNUAL spend constant across cadences so the three styles compare fairly."""
    ppy = PERIODS_PER_YEAR.get(cadence, 12)
    return round(monthly * 12.0 / ppy, 2)


def tilt_from_score(score: int) -> float:
    """Map a composite signal score to a contribution multiplier in
    [MIN_TILT, MAX_TILT]. Bullish/cheap (positive score) buys more."""
    raw = 1.0 + (score / SCORE_SPAN) * (MAX_TILT - 1.0)
    return round(max(MIN_TILT, min(MAX_TILT, raw)), 3)


def _score_at(closes: list[float], i: int) -> int:
    """Engine score using only data through bar i (no lookahead). Neutral until
    there is enough history for the indicators to mean anything."""
    if i < backtest.WARMUP:
        return 0
    return indicators.score_signals(closes[: i + 1])["score"]


def _buy(cash_in: float, raw_price: float, comm: float, slip: float) -> float:
    """Shares bought for `cash_in` dollars, after slippage + commission."""
    price = raw_price * (1 + slip)
    net = cash_in * (1 - comm)
    return net / price if price else 0.0


def _period_indices(n: int, step: int) -> list[int]:
    return list(range(0, n, step)) if step > 0 else []


def simulate_dca(dates: list[str], closes: list[float], kind: str,
                 per_period: float, cadence: str, mode: str = "plain") -> dict:
    """Accumulate shares by buying every `cadence` period. mode 'tilt' scales
    each buy by the signal score at that bar; 'plain' buys a flat amount."""
    comm, slip = backtest.cost_model(kind)
    step = bars_per_period(cadence, kind)
    idxs = _period_indices(len(closes), step)

    invested = 0.0
    shares = 0.0
    contributions: list[dict] = []
    idx_set = set(idxs)
    value_curve: list[float] = []     # market value of holdings, per bar
    invested_curve: list[float] = []  # cumulative dollars put in, per bar

    for i, price in enumerate(closes):
        if i in idx_set:
            tilt = tilt_from_score(_score_at(closes, i)) if mode == "tilt" else 1.0
            amount = round(per_period * tilt, 2)
            got = _buy(amount, price, comm, slip)
            invested += amount
            shares += got
            contributions.append({
                "date": dates[i] if i < len(dates) else str(i),
                "price": round(price, 4), "amount": amount,
                "tilt": tilt, "shares": round(got, 8),
            })
        value_curve.append(round(shares * price, 2))
        invested_curve.append(round(invested, 2))

    final_price = closes[-1] if closes else 0.0
    final_value = shares * final_price
    profit = final_value - invested
    return {
        "mode": mode,
        "periods": len(idxs),
        "invested": round(invested, 2),
        "shares": round(shares, 8),
        "avg_cost": round(invested / shares, 4) if shares else None,
        "final_price": round(final_price, 4),
        "final_value": round(final_value, 2),
        "profit": round(profit, 2),
        "return_pct": round(profit / invested * 100, 2) if invested else None,
        "max_paper_dd_pct": backtest._max_drawdown_pct(value_curve),
        "contributions": contributions,
        "value_curve": value_curve,
        "invested_curve": invested_curve,
    }


def simulate_lump(dates: list[str], closes: list[float], kind: str,
                  total: float) -> dict:
    """Deploy the whole budget on the first period bar, then hold to the end."""
    comm, slip = backtest.cost_model(kind)
    shares = _buy(total, closes[0], comm, slip) if closes else 0.0
    value_curve = [round(shares * c, 2) for c in closes]
    invested_curve = [round(total, 2)] * len(closes)  # all in on day one
    final_price = closes[-1] if closes else 0.0
    final_value = shares * final_price
    profit = final_value - total
    return {
        "mode": "lump",
        "periods": 1,
        "invested": round(total, 2),
        "shares": round(shares, 8),
        "avg_cost": round(closes[0], 4) if closes else None,
        "final_price": round(final_price, 4),
        "final_value": round(final_value, 2),
        "profit": round(profit, 2),
        "return_pct": round(profit / total * 100, 2) if total else None,
        "max_paper_dd_pct": backtest._max_drawdown_pct(value_curve),
        "value_curve": value_curve,
        "invested_curve": invested_curve,
    }


def _regime(closes: list[float]) -> dict:
    """Classify the window: up / down / flat by first-to-last move."""
    if len(closes) < 2 or not closes[0]:
        return {"tag": "flat", "move_pct": 0.0}
    move = round((closes[-1] - closes[0]) / closes[0] * 100, 2)
    tag = "up" if move > 10 else "down" if move < -10 else "flat"
    return {"tag": tag, "move_pct": move}


_REGIME_NOTE = {
    "up": ("The market mostly ROSE across this window. History's edge goes to "
           "lump sum here — money in early rode the whole climb. DCA still cut "
           "your entry risk; you just paid for that safety in some upside."),
    "down": ("The market mostly FELL across this window. This is DCA's home turf "
             "— every period bought cheaper, so the average cost beat a day-one "
             "lump that caught the falling knife."),
    "flat": ("Choppy, sideways window — no strong trend. DCA smooths the churn, "
             "and the tilt has the most room to help by leaning into the dips."),
}


def _verdict(plain: dict, lump: dict, tilt: dict, regime: dict) -> dict:
    """Honest read: who won per-dollar, plus the general truth about lump sum."""
    def ret(d: dict) -> float:
        return d["return_pct"] if d["return_pct"] is not None else -1e9

    by_return = sorted(
        [("plain", plain), ("lump", lump), ("tilt", tilt)],
        key=lambda kv: ret(kv[1]), reverse=True,
    )
    winner = by_return[0][0]
    both = tilt["return_pct"] is not None and plain["return_pct"] is not None
    tilt_helped = both and tilt["return_pct"] > plain["return_pct"]
    return {
        "winner_by_return": winner,
        "ranking": [k for k, _ in by_return],
        "tilt_vs_plain_pct": round(tilt["return_pct"] - plain["return_pct"], 2) if both else None,
        "tilt_helped": tilt_helped,
        "regime_note": _REGIME_NOTE[regime["tag"]],
        "honest_truth": ("Lump sum beats DCA in most historical windows because "
                         "markets rise more often than they fall — but it hurts "
                         "far more when you're early into a drop. DCA trades some "
                         "average upside for a calmer ride and no all-in timing. "
                         "The tilt only adds value when the engine's 'cheap' "
                         "actually was — it is a lean, not a guarantee."),
        "same_dollars_note": ("All three were given the SAME total budget; return "
                              "% is the fair per-dollar comparison. Lump often "
                              "shows a bigger final value simply because every "
                              "dollar was at work from day one — more time in, "
                              "more risk taken earlier."),
    }


def project(per_period: float, cadence: str, years: float) -> dict:
    """Forward compounding projection of the contribution stream under three
    assumed annual returns. An ASSUMPTION, not a forecast — labeled as such."""
    ppy = PERIODS_PER_YEAR.get(cadence, 12)
    n = int(round(ppy * years))
    contributed = round(per_period * n, 2)

    def fv_at(periods: int, annual: float) -> float:
        r = annual / ppy
        return per_period * periods if r == 0 else per_period * (((1 + r) ** periods - 1) / r)

    scenarios = {}
    for name, annual in PROJECTION_RATES.items():
        fv = fv_at(n, annual)
        scenarios[name] = {
            "annual_rate_pct": round(annual * 100, 1),
            "future_value": round(fv, 2),
            "growth": round(fv - contributed, 2),
        }

    # Year-by-year curve for the "where it's going" growth chart.
    curve = []
    for y in range(int(years) + 1):
        ny = ppy * y
        pt = {"year": y, "contributed": round(per_period * ny, 2)}
        for name, annual in PROJECTION_RATES.items():
            pt[name] = round(fv_at(ny, annual), 2)
        curve.append(pt)

    return {
        "years": years, "periods": n, "per_period": per_period,
        "contributed": contributed, "scenarios": scenarios, "curve": curve,
        "disclaimer": ("Assumes a constant annual return and steady contributions. "
                       "Real returns vary year to year and can be negative. This "
                       "projects the MATH of compounding, not a prediction of this "
                       "or any asset. Past performance is not future results."),
    }


def _nudge(symbol: str, sig: dict | None, cadence: str) -> dict:
    """Plain-English lean for THIS period's tilt buy — a read, not a directive."""
    score = (sig or {}).get("score", 0)
    label = (sig or {}).get("label", "NEUTRAL")
    tilt = tilt_from_score(score)
    if tilt > 1.05:
        head, icon = f"Lean IN — ~{tilt}x your base buy", "\U0001F4C8"
        text = (f"The engine reads {label} on {symbol}: it looks relatively cheap, "
                f"so a tilt-DCA adds a bit more this {cadence} buy.")
    elif tilt < 0.95:
        head, icon = f"Ease OFF — ~{tilt}x your base buy", "\U0001F4C9"
        text = (f"The engine reads {label} on {symbol}: it looks rich, so a "
                f"tilt-DCA trims this {cadence} buy (but still buys).")
    else:
        head, icon = "Hold the line — ~1.0x base", "⚖️"
        text = (f"The engine reads {label} on {symbol}: nothing extreme, so a "
                f"tilt-DCA buys about the flat amount this {cadence}.")
    return {"tilt": tilt, "label": label, "icon": icon, "headline": head,
            "text": text + " A lean from the data, not a directive — the choice is yours."}


def dca_report(dates: list[str], closes: list[float], kind: str, symbol: str,
               monthly: float, cadence: str, years: float) -> dict:
    """Full DCA Wizard payload: plan + 3-way backtest + projection + nudge."""
    if cadence not in PERIODS_PER_YEAR:
        cadence = "monthly"
    knd = _norm_kind(kind)
    per_period = per_period_amount(monthly, cadence)

    step = bars_per_period(cadence, knd)
    n_periods = max(1, len(closes) // step)
    total_budget = round(per_period * n_periods, 2)

    plain = simulate_dca(dates, closes, knd, per_period, cadence, "plain")
    tilt = simulate_dca(dates, closes, knd, per_period, cadence, "tilt")
    lump = simulate_lump(dates, closes, knd, plain["invested"] or total_budget)
    regime = _regime(closes)

    sig = indicators.score_signals(closes) if len(closes) > 1 else None
    return {
        "symbol": symbol.upper(), "kind": knd,
        "plan": {
            "monthly": round(monthly, 2), "cadence": cadence,
            "per_period": per_period, "periods_per_year": PERIODS_PER_YEAR[cadence],
            "window_periods": plain["periods"], "window_budget": plain["invested"],
        },
        "backtest": {"plain": plain, "tilt": tilt, "lump": lump},
        "regime": regime,
        "verdict": _verdict(plain, lump, tilt, regime),
        "projection": project(per_period, cadence, years),
        "nudge": _nudge(symbol.upper(), sig, cadence),
        "series": {"dates": dates, "closes": [round(c, 4) for c in closes]},
    }
