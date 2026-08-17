"""Does the signal pay when expressed as an options spread? Measured, with receipts.

`backtest.py` measures the signal as a long-only stock timing rule against
buy-and-hold. That is not what the app does with it. The app turns the same
signal into a 2-DTE debit spread — a different instrument, a different payoff,
and a job nobody ever measured it for. Every conclusion drawn from the stock
backtest about the options product is a guess.

THE DESIGN DECISION THAT MAKES THIS HONEST
------------------------------------------
    Entry is modelled. Exit is not.

A debit spread held to expiry is worth exactly its intrinsic value, and the
real historical close on the expiry date is a fact we already have. So the
exit — the half that decides win or lose — involves no model at all. Only the
entry price needs Black-Scholes.

And every modelling choice at entry is made to COST the strategy money:

  * implied vol is trailing REALISED vol, computed from bars up to and
    including the entry bar only — never a bar from the future
  * the bid-ask is charged on both legs at entry
  * commission is charged on both legs, both ways
  * `sensitivity()` re-runs the whole thing at 0.8x .. 1.6x that vol, because
    entry price is the one guessed number and a conclusion that flips between
    plausible volatilities is not a conclusion

Every trade returned carries the reason it fired, what was bought, what it
cost and what it settled at — so the result can be shown and argued with
rather than taken on faith.

Not a substitute for forward paper. Historical option chains would be better;
this is what can be measured honestly without them.
"""
from __future__ import annotations

import math

import backtest
import indicators

RISK_FREE = 0.04
TRADING_DAYS = 252
CONTRACT_MULTIPLIER = 100
COMMISSION_PER_CONTRACT = 0.65

# Mirrors what options.suggest_spread actually picks on the live board: a long
# leg near the money and a short leg roughly 2.2% away (the TSLA 340/332.5 on a
# 340 spot this engine suggested today).
DEFAULT_WIDTH_PCT = 0.022
# Observed on the live chain: TSLA 340P quoted 4.20/4.30, ~2.4% of price.
DEFAULT_SPREAD_PCT = 0.025
DEFAULT_DTE = 2
VOL_WINDOW = 20

BULL = ("BUY", "STRONG BUY")
BEAR = ("SELL", "STRONG SELL")


# ------------------------------------------------------- Black-Scholes

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, sigma: float,
             right: str, r: float = RISK_FREE) -> float:
    """Black-Scholes price of one European option.

    Degenerate inputs collapse to intrinsic rather than raising: at expiry, or
    at zero volatility, the option IS its intrinsic value and pretending
    otherwise would invent premium out of nothing.
    """
    intrinsic = (max(spot - strike, 0.0) if right == "call"
                 else max(strike - spot, 0.0))
    if t_years <= 0 or sigma is None or sigma <= 0:
        return intrinsic

    v = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t_years) / v
    d2 = d1 - v
    disc = math.exp(-r * t_years)
    if right == "call":
        return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def realised_vol(closes: list[float], index: int,
                 window: int = VOL_WINDOW) -> float | None:
    """Annualised volatility of the `window` bars ending AT `index`.

    The slice is closed at `index + 1`, so a bar after the entry can never
    reach this calculation. That single boundary is the difference between a
    measurement and the classic backtest lie.
    """
    lo = index - window + 1
    if lo < 1 or index >= len(closes):
        return None
    rets = []
    for i in range(max(lo, 1), index + 1):
        prev, cur = closes[i - 1], closes[i]
        if prev > 0 and cur > 0:
            rets.append(math.log(cur / prev))
    if len(rets) < 2:
        return None
    return indicators._stdev(rets) * math.sqrt(TRADING_DAYS)


# --------------------------------------------------------- one trade

def simulate_trade(direction: str, spot: float, long_strike: float,
                   short_strike: float, sigma: float | None, dte: int,
                   exit_spot: float, contracts: int = 1,
                   spread_pct: float = DEFAULT_SPREAD_PCT,
                   r: float = RISK_FREE) -> dict | None:
    """Price a debit spread at entry, settle it on the real close at expiry."""
    if sigma is None or sigma <= 0 or spot <= 0:
        return None                      # unpriceable is refused, never guessed

    t = dte / TRADING_DAYS
    long_px = bs_price(spot, long_strike, t, sigma, direction, r)
    short_px = bs_price(spot, short_strike, t, sigma, direction, r)

    # Cross the spread on both legs: pay up for the long, receive less for the
    # short. This is the cost the mid price hides.
    long_fill = long_px * (1 + spread_pct)
    short_fill = short_px * (1 - spread_pct)
    debit = max(long_fill - short_fill, 0.01)

    # The exit. No model — intrinsic against the real historical close.
    if direction == "call":
        intrinsic = max(exit_spot - long_strike, 0.0) - max(exit_spot - short_strike, 0.0)
    else:
        intrinsic = max(long_strike - exit_spot, 0.0) - max(short_strike - exit_spot, 0.0)
    intrinsic = max(intrinsic, 0.0)

    commission = COMMISSION_PER_CONTRACT * 2 * 2 * contracts   # 2 legs, both ways
    cost_usd = debit * CONTRACT_MULTIPLIER * contracts + commission
    pnl = (intrinsic - debit) * CONTRACT_MULTIPLIER * contracts - commission

    return {
        "direction": direction, "spot": round(spot, 4),
        "long_strike": round(long_strike, 4), "short_strike": round(short_strike, 4),
        "width": round(abs(long_strike - short_strike), 4),
        "sigma": round(sigma, 4), "dte": dte,
        "debit": round(debit, 4), "cost_usd": round(cost_usd, 2),
        "commission": round(commission, 2),
        "exit_spot": round(exit_spot, 4), "intrinsic": round(intrinsic, 4),
        "pnl_usd": round(pnl, 2),
        "won": pnl > 0,
    }


# ---------------------------------------------------- walking history

def manage_trade(direction: str, spot: float, long_strike: float,
                 short_strike: float, sigma: float | None, path: list[float],
                 t_total: float, take_profit: float, stop_loss: float,
                 contracts: int = 1, spread_pct: float = DEFAULT_SPREAD_PCT,
                 r: float = RISK_FREE) -> dict | None:
    """Enter on the signal, leave at the target — the scalper's trade.

    `backtest_options` holds to expiry, which for a short-dated spread is close
    to the worst exit available: it can be up 40% within the hour and still
    settle at zero, and hold-to-expiry records only the zero. Someone taking
    profits never experiences that number. Measuring them with that model
    describes a strategy nobody runs.

    So this walks the path bar by bar, reprices the spread with the time that
    is genuinely left, and exits on whichever comes first — target, stop, or
    expiry. Two rules keep it honest:

      * it leaves on the FIRST bar that qualifies, never the best one, because
        picking the best bar in hindsight is not an exit rule, it is a wish
      * the exit is charged the bid-ask just like the entry, since getting out
        costs exactly what getting in did
    """
    if sigma is None or sigma <= 0 or not path:
        return None

    t = t_total if t_total and t_total > 0 else 1e-9
    long_px = bs_price(spot, long_strike, t, sigma, direction, r)
    short_px = bs_price(spot, short_strike, t, sigma, direction, r)
    debit = max(long_px * (1 + spread_pct) - short_px * (1 - spread_pct), 0.01)

    commission = COMMISSION_PER_CONTRACT * 2 * 2 * contracts
    steps = len(path)
    exit_value, exit_reason, exit_index = None, "expiry", steps - 1

    for j, px in enumerate(path):
        # Time genuinely remaining at this bar — the decay a live position feels.
        remaining = t * (1.0 - (j + 1) / steps)
        lv = bs_price(px, long_strike, remaining, sigma, direction, r)
        sv = bs_price(px, short_strike, remaining, sigma, direction, r)
        # Closing crosses the spread the other way: sell the long, buy the short.
        value = max(lv * (1 - spread_pct) - sv * (1 + spread_pct), 0.0)
        move = (value - debit) / debit

        if move >= take_profit:
            exit_value, exit_reason, exit_index = value, "target", j
            break
        if move <= -stop_loss:
            exit_value, exit_reason, exit_index = value, "stop", j
            break

    if exit_value is None:
        # Ran to the end: settle on intrinsic against the real final price.
        final = path[-1]
        if direction == "call":
            exit_value = max(final - long_strike, 0.0) - max(final - short_strike, 0.0)
        else:
            exit_value = max(long_strike - final, 0.0) - max(short_strike - final, 0.0)
        exit_value = max(exit_value, 0.0)

    pnl = (exit_value - debit) * CONTRACT_MULTIPLIER * contracts - commission
    return {
        "direction": direction, "spot": round(spot, 4),
        "long_strike": round(long_strike, 4), "short_strike": round(short_strike, 4),
        "sigma": round(sigma, 4),
        "debit": round(debit, 4), "exit_value": round(exit_value, 4),
        "exit_reason": exit_reason, "exit_index": exit_index,
        "bars_held": exit_index + 1,
        "pnl_pct": round((exit_value - debit) / debit, 4),
        "pnl_usd": round(pnl, 2),
        "commission": round(commission, 2),
        "cost_usd": round(debit * CONTRACT_MULTIPLIER * contracts + commission, 2),
        "won": pnl > 0,
    }


REGIME_WINDOW = 200


def regime_at(closes: list[float], index: int,
              window: int = REGIME_WINDOW) -> str | None:
    """Which way the tape was leaning at `index`, knowable at that moment.

    Price against its own 200-bar average — the crudest possible trend filter,
    chosen deliberately: anything cleverer invites fitting, and the question
    here is not "what is the best filter" but "does regime explain the losses".

    The average ends AT `index`, so no future bar reaches it. A regime label
    derived from the whole series would be hindsight wearing a lab coat, and
    it would make every bearish signal look brilliant in the drawdowns we
    already know happened.
    """
    lo = index - window + 1
    if lo < 0 or index >= len(closes):
        return None
    avg = sum(closes[lo:index + 1]) / window
    return "uptrend" if closes[index] > avg else "downtrend"


def by_regime(trades: list[dict]) -> dict:
    """Split a set of trades into regime buckets, losing none of them."""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        buckets.setdefault(t.get("regime") or "unknown", []).append(t)
    return {name: summarize(rows) for name, rows in buckets.items()}


def _strikes(direction: str, spot: float, width_pct: float) -> tuple[float, float]:
    """Long near the money, short `width_pct` further out — the shape the live
    suggester produces, so the measurement matches the product."""
    width = spot * width_pct
    return (spot, spot + width) if direction == "call" else (spot, spot - width)


def backtest_options(dates: list[str], closes: list[float], symbol: str,
                     dte: int = DEFAULT_DTE, width_pct: float = DEFAULT_WIDTH_PCT,
                     spread_pct: float = DEFAULT_SPREAD_PCT,
                     iv_multiple: float = 1.0,
                     contracts: int = 1) -> dict:
    """Fire the app's own signal into a debit spread at every bar, and settle it.

    Labels come from backtest._compute_labels — the SAME engine the live board
    runs — so this measures the shipped signal rather than a re-derivation of
    it that could quietly differ.
    """
    trades: list[dict] = []
    labels = backtest._compute_labels(closes) if len(closes) > backtest.WARMUP else []

    for i, label in enumerate(labels):
        if not label:
            continue
        direction = "call" if label in BULL else "put" if label in BEAR else None
        if direction is None:
            continue
        exit_i = i + dte
        if exit_i >= len(closes):
            continue                      # no future to settle against: skip
        sigma = realised_vol(closes, i)
        if sigma is None:
            continue
        spot = closes[i]
        long_k, short_k = _strikes(direction, spot, width_pct)
        t = simulate_trade(direction, spot, long_k, short_k, sigma * iv_multiple,
                           dte, closes[exit_i], contracts, spread_pct)
        if not t:
            continue
        t.update({
            "symbol": symbol, "label": label,
            "regime": regime_at(closes, i),
            "entry_index": i, "exit_index": exit_i,
            "entry_date": dates[i] if i < len(dates) else str(i),
            "exit_date": dates[exit_i] if exit_i < len(dates) else str(exit_i),
            "move_pct": round((closes[exit_i] - spot) / spot * 100, 2),
        })
        trades.append(t)

    return {"symbol": symbol, "dte": dte, "iv_multiple": iv_multiple,
            "trades": trades, "summary": summarize(trades)}


def backtest_scalp(highs: list[float], lows: list[float], closes: list[float],
                   dates: list[str], symbol: str, take_profit: float = 0.25,
                   stop_loss: float = 0.50, max_bars: int = 12,
                   cooldown: int = 0, squeeze_only: bool = False,
                   dte_days: int = DEFAULT_DTE, iv_multiple: float = 1.0,
                   width_pct: float = DEFAULT_WIDTH_PCT,
                   spread_pct: float = DEFAULT_SPREAD_PCT,
                   contracts: int = 1) -> dict:
    """Enter on a signal, manage the exit, then WAIT before looking again.

    This is the honest counterpart to entering on every signalling bar. Signals
    persist across runs of bars, so bar-by-bar entry counts one move twenty
    times — and those twenty copies win or lose together. The trade count looks
    like statistical power and is nothing of the kind; it is one observation
    wearing twenty hats.

    Here the walker holds a single position, exits it, and only then resumes
    scanning (after `cooldown` bars, if set). What comes out is a much smaller
    number of much more independent trades, which is the number worth trusting.

    `squeeze_only` additionally requires the TTM squeeze to have just FIRED —
    compressed on the previous bar, released on this one — so the entry needs
    energy actually releasing, not merely a direction.
    """
    trades: list[dict] = []
    if len(closes) <= backtest.WARMUP + max_bars + 2:
        return {"symbol": symbol, "trades": [], "summary": summarize([])}

    labels = backtest._compute_labels(closes)
    squeeze = indicators.ttm_squeeze_series(highs, lows, closes) if squeeze_only else None

    i = 0
    while i < len(labels):
        label = labels[i]
        direction = ("call" if label in BULL else
                     "put" if label in BEAR else None)
        if direction is None:
            i += 1
            continue
        if squeeze_only:
            on = squeeze["on"] if squeeze else None
            # fired = compressed on the previous bar, released on this one
            if not on or i < 1 or not on[i - 1] or on[i]:
                i += 1
                continue
        if i + max_bars >= len(closes):
            break
        sigma = realised_vol(closes, i)
        if sigma is None:
            i += 1
            continue

        spot = closes[i]
        long_k, short_k = _strikes(direction, spot, width_pct)
        out = manage_trade(direction, spot, long_k, short_k, sigma * iv_multiple,
                           closes[i + 1:i + 1 + max_bars], dte_days / TRADING_DAYS,
                           take_profit, stop_loss, contracts, spread_pct)
        if not out:
            i += 1
            continue

        out.update({
            "symbol": symbol, "label": label,
            "regime": regime_at(closes, i),
            "entry_index": i,
            "entry_date": dates[i] if i < len(dates) else str(i),
        })
        trades.append(out)
        # The position occupied these bars. Nothing else may be opened inside
        # them, or the samples stop being independent again.
        i += out["bars_held"] + max(cooldown, 0) + 1

    return {"symbol": symbol, "take_profit": take_profit, "stop_loss": stop_loss,
            "max_bars": max_bars, "cooldown": cooldown,
            "squeeze_only": squeeze_only,
            "trades": trades, "summary": summarize(trades)}


def summarize(trades: list[dict]) -> dict:
    """Win rate and expectancy — or None when there is nothing to average.

    Zero trades reports None rather than 0 or 100%. A 0/0 win rate rendered as
    a percentage is the most flattering lie a backtest can tell.
    """
    n = len(trades)
    if not n:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": None,
                "expectancy_usd": None, "total_usd": 0.0,
                "avg_win_usd": None, "avg_loss_usd": None}

    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    total = sum(t["pnl_usd"] for t in trades)
    return {
        "trades": n, "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1),
        "expectancy_usd": round(total / n, 2),
        "total_usd": round(total, 2),
        "avg_win_usd": round(sum(t["pnl_usd"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss_usd": round(sum(t["pnl_usd"] for t in losses) / len(losses), 2) if losses else None,
    }


def sensitivity(dates: list[str], closes: list[float], symbol: str,
                multiples: tuple[float, ...] = (0.8, 1.0, 1.2, 1.6),
                **kw) -> dict:
    """Re-run across implied-vol assumptions.

    Entry price is the single guessed number in this measurement, so a result
    is only meaningful next to how sensitive it is. Higher assumed vol means a
    more expensive entry, so totals must fall monotonically — if they do not,
    something is wrong with the pricer, and the test suite says so.
    """
    bands = []
    for m in multiples:
        out = backtest_options(dates, closes, symbol, iv_multiple=m, **kw)
        s = out["summary"]
        bands.append({"iv_multiple": m, "trades": s["trades"],
                      "win_rate": s["win_rate"], "total_usd": s["total_usd"],
                      "expectancy_usd": s["expectancy_usd"]})
    return {"symbol": symbol, "bands": bands}
