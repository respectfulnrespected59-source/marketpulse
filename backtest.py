"""Proof Mode — walk the live signal engine backward over real history.

Three complementary views, all honest:

1. Signal quality (`backtest_signals`) — every time the engine flipped into
   STRONG BUY / STRONG SELL, what did price do over the next 5/10/30 bars?
   Descriptive, not a prediction. Nets out trading costs so the hit-rate you
   see is what you'd actually have kept.

2. Realistic strategy P&L (`simulate_strategy`) — actually *trades* the agent's
   rule (buy on STRONG BUY, sell on the next SELL/STRONG SELL flip) with real
   fills: slippage worsens every entry and exit, commissions are charged per
   side, and the result is compared against simple buy-and-hold. Gross-vs-net
   makes the cost drag impossible to hide.

3. Walk-forward (`walk_forward`) — runs the rule on an OUT-OF-SAMPLE holdout
   (older train vs newer test) and across sequential time folds. NOTE: the
   engine has no fitted parameters, so this is NOT parameter optimization; it
   answers a different, equally important question — is the edge stable across
   time, or did it come from one lucky stretch?

Nothing here is a performance promise. It is what the rules would have done,
after costs, on this history.
"""
from __future__ import annotations

import indicators

HORIZONS = (5, 10, 30)
WARMUP = 50  # bars needed before indicators are meaningful (SMA50 + MACD)

# ----------------------------------------------------------------- cost model
# Per-side costs in basis points (1 bp = 0.01%). Defaults reflect a realistic
# commission-free broker (Alpaca): stocks pay no commission but still eat
# spread/slippage on market orders; crypto pays a real taker fee plus wider
# slippage. These are deliberately conservative — better to under-promise.
COMMISSION_BPS = {"stock": 0.0, "crypto": 25.0}   # per side
SLIPPAGE_BPS = {"stock": 5.0, "crypto": 20.0}     # per side

# Fraction of available cash deployed on each entry (leaves a buffer for fees).
POSITION_FRACTION = 0.95
START_EQUITY = 10_000.0

ENTRY_LABEL = "STRONG BUY"
EXIT_LABELS = ("SELL", "STRONG SELL")


def cost_model(kind: str) -> tuple[float, float]:
    """Return (commission_fraction, slippage_fraction) per side for a kind."""
    k = "crypto" if kind == "crypto" else "stock"
    return COMMISSION_BPS[k] / 10_000.0, SLIPPAGE_BPS[k] / 10_000.0


def round_trip_cost_pct(kind: str) -> float:
    """Total entry+exit cost as a percentage of notional (commission+slippage)."""
    comm, slip = cost_model(kind)
    return round(2 * (comm + slip) * 100, 4)


# ----------------------------------------------------------------- signal grade
def _forward_returns(closes: list[float], i: int, cost_pct: float) -> dict:
    """% change from bar i to bar i+h for each horizon, plus a net column that
    subtracts the round-trip cost (None if not enough data)."""
    base = closes[i]
    out: dict = {}
    for h in HORIZONS:
        j = i + h
        raw = round((closes[j] - base) / base * 100, 2) if j < len(closes) and base else None
        out[f"fwd{h}"] = raw
        out[f"net{h}"] = round(raw - cost_pct, 2) if raw is not None else None
    return out


def backtest_signals(dates: list[str], closes: list[float], kind: str = "stock") -> dict:
    """Find STRONG BUY / STRONG SELL flips and grade their forward outcome.

    A signal is recorded only on the bar it *enters* a strong state (a state
    change), so we don't double-count every day it stays there. `kind` selects
    the cost model used for the net columns.
    """
    cost_pct = round_trip_cost_pct(kind)
    events: list[dict] = []
    prev_label = None

    for i in range(WARMUP, len(closes)):
        sig = indicators.score_signals(closes[: i + 1])
        label = sig["label"]
        is_strong = label in ("STRONG BUY", "STRONG SELL")
        if is_strong and label != prev_label:
            direction = "buy" if label == "STRONG BUY" else "sell"
            fwd = _forward_returns(closes, i, cost_pct)
            events.append({
                "date": dates[i] if i < len(dates) else str(i),
                "idx": i,
                "type": label,
                "dir": direction,
                "price": round(closes[i], 4),
                "rsi": sig["rsi"],
                **fwd,
            })
        prev_label = label if is_strong else None

    return {"events": events, "summary": _summarize(events, cost_pct)}


def _summarize(events: list[dict], cost_pct: float) -> dict:
    """Directional hit-rate + average forward move on the 30-bar horizon, with
    a net (after-cost) hit-rate alongside the raw one."""
    graded = [e for e in events if e.get("fwd30") is not None]
    buys = [e for e in graded if e["dir"] == "buy"]
    sells = [e for e in graded if e["dir"] == "sell"]

    def capture(e: dict, field: str) -> float:
        """Move in the signal's direction (a sell that drops counts as +)."""
        return e[field] if e["dir"] == "buy" else -e[field]

    def hit_rate(group: list[dict], field: str) -> float | None:
        if not group:
            return None
        wins = sum(1 for e in group if capture(e, field) > 0)
        return round(wins / len(group) * 100, 1)

    def avg_capture(group: list[dict], field: str) -> float | None:
        if not group:
            return None
        return round(sum(capture(e, field) for e in group) / len(group), 2)

    all_graded = buys + sells
    return {
        "signals": len(events),
        "graded": len(graded),
        "win_rate": hit_rate(all_graded, "fwd30"),
        "net_win_rate": hit_rate(all_graded, "net30"),
        "buy_signals": len(buys),
        "buy_win_rate": hit_rate(buys, "fwd30"),
        "sell_signals": len(sells),
        "sell_win_rate": hit_rate(sells, "fwd30"),
        "avg_move_30d": avg_capture(all_graded, "fwd30"),
        "net_avg_move_30d": avg_capture(all_graded, "net30"),
        "round_trip_cost_pct": cost_pct,
        "best": max((capture(e, "fwd30") for e in all_graded), default=None),
        "worst": min((capture(e, "fwd30") for e in all_graded), default=None),
    }


# ----------------------------------------------------------------- strategy sim
def _compute_labels(closes: list[float]) -> list[str | None]:
    """Engine label at every bar (None during warmup). The expensive step,
    computed once and reused by every simulation window."""
    labels: list[str | None] = [None] * len(closes)
    for i in range(WARMUP, len(closes)):
        labels[i] = indicators.score_signals(closes[: i + 1])["label"]
    return labels


def _max_drawdown_pct(curve: list[float]) -> float:
    """Largest peak-to-trough drop in the equity curve, as a positive %."""
    peak = curve[0] if curve else 0.0
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak)
    return round(-worst * 100, 2)


def _run(closes: list[float], labels: list[str | None], comm: float,
         slip: float, lo: int = 0, hi: int | None = None) -> dict:
    """Trade the agent rule with explicit cash accounting over bars [lo, hi).

    `labels[i]` is the engine label computed on closes[:i+1] (or None during
    warmup) — always globally correct, so restricting the window only changes
    which trades are *counted*, never introduces lookahead. Buys deploy
    POSITION_FRACTION of cash; sells liquidate fully. Slippage worsens fills
    (buy higher, sell lower); commission is charged on each side. Any position
    still open at the window's end is force-closed on its last bar so every
    trade has a realized result.
    """
    hi = len(closes) if hi is None else hi
    cash = START_EQUITY
    shares = 0.0
    entry_price = 0.0
    entry_idx = lo
    trades: list[dict] = []
    fees_paid = 0.0
    slippage_cost = 0.0
    curve: list[float] = []

    def close_position(i: int, raw_close: float) -> None:
        nonlocal cash, shares, fees_paid, slippage_cost
        sell_price = raw_close * (1 - slip)
        proceeds = shares * sell_price
        commission = proceeds * comm
        cash += proceeds - commission
        fees_paid += commission
        slippage_cost += shares * (raw_close - sell_price)
        cost_basis = shares * entry_price
        net_pnl = (proceeds - commission) - cost_basis
        trades.append({
            "entry_idx": entry_idx,
            "exit_idx": i,
            "bars_held": i - entry_idx,
            "entry_price": round(entry_price, 4),
            "exit_price": round(sell_price, 4),
            "net_pnl": round(net_pnl, 2),
            "net_return_pct": round(net_pnl / cost_basis * 100, 2) if cost_basis else 0.0,
        })

    for i in range(lo, hi):
        raw_close = closes[i]
        label = labels[i]
        if shares == 0.0 and label == ENTRY_LABEL:
            invest = cash * POSITION_FRACTION
            buy_price = raw_close * (1 + slip)
            commission = invest * comm
            shares = (invest - commission) / buy_price if buy_price else 0.0
            cash -= invest
            entry_price = buy_price
            entry_idx = i
            fees_paid += commission
            slippage_cost += shares * (buy_price - raw_close)
        elif shares > 0.0 and label in EXIT_LABELS:
            close_position(i, raw_close)
            shares = 0.0
        curve.append(cash + shares * raw_close)

    if shares > 0.0:  # force-close any open position on the window's last bar
        close_position(hi - 1, closes[hi - 1])
        shares = 0.0
        curve[-1] = cash

    end_equity = curve[-1] if curve else START_EQUITY
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    return {
        "end_equity": round(end_equity, 2),
        "return_pct": round((end_equity / START_EQUITY - 1) * 100, 2),
        "trades": trades,
        "num_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "avg_win_pct": round(sum(t["net_return_pct"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss_pct": round(sum(t["net_return_pct"] for t in losses) / len(losses), 2) if losses else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown_pct": _max_drawdown_pct(curve),
        "fees_paid": round(fees_paid, 2),
        "slippage_cost": round(slippage_cost, 2),
        "avg_bars_held": round(sum(t["bars_held"] for t in trades) / len(trades), 1) if trades else None,
    }


def _buy_hold(closes: list[float], comm: float, slip: float,
              lo: int = WARMUP, hi: int | None = None) -> float:
    """Buy at bar `lo`, hold to bar `hi-1`, pay one round trip. Window-aware so
    it is a fair benchmark for both the full sim and each walk-forward fold."""
    hi = len(closes) if hi is None else hi
    entry = closes[lo] * (1 + slip)
    shares = (START_EQUITY * (1 - comm)) / entry if entry else 0.0
    exit_price = closes[hi - 1] * (1 - slip)
    end_equity = shares * exit_price * (1 - comm)
    return round((end_equity / START_EQUITY - 1) * 100, 2)


def simulate_strategy(dates: list[str], closes: list[float], kind: str = "stock") -> dict:
    """Realistic round-trip simulation of the agent rule, net vs gross vs hold.

    Returns net (after fees+slippage) and gross (zero-cost) results plus the
    buy-and-hold benchmark, so the cost drag and the edge-vs-holding question
    are both answered explicitly.
    """
    if len(closes) <= WARMUP + 2:
        return {"error": "not enough history"}

    comm, slip = cost_model(kind)
    labels = _compute_labels(closes)

    net = _run(closes, labels, comm, slip)
    gross = _run(closes, labels, 0.0, 0.0)
    bh = _buy_hold(closes, comm, slip)

    return {
        "kind": kind,
        "start_equity": START_EQUITY,
        "position_fraction": POSITION_FRACTION,
        "commission_bps": COMMISSION_BPS["crypto" if kind == "crypto" else "stock"],
        "slippage_bps": SLIPPAGE_BPS["crypto" if kind == "crypto" else "stock"],
        "net": net,
        "gross_return_pct": gross["return_pct"],
        "cost_drag_pct": round(gross["return_pct"] - net["return_pct"], 2),
        "buy_hold_return_pct": bh,
        "beats_buy_hold": net["return_pct"] > bh,
    }


# ----------------------------------------------------------------- walk-forward
def _fold_view(r: dict) -> dict:
    """Trim a full `_run` result down to the fields a fold/holdout reports."""
    return {
        "return_pct": r["return_pct"],
        "num_trades": r["num_trades"],
        "win_rate": r["win_rate"],
        "max_drawdown_pct": r["max_drawdown_pct"],
    }


def walk_forward(dates: list[str], closes: list[float], kind: str = "stock",
                 folds: int = 4, train_frac: float = 0.7) -> dict:
    """Out-of-sample validation of the FIXED rule across time.

    HONESTY NOTE: the signal engine has no parameters to fit, so this is not
    parameter optimization — running on a holdout cannot "cheat" by re-tuning.
    What it tests is whether the edge is *consistent across time* or an artifact
    of one favorable period. Two views:
      holdout: train (older `train_frac`) vs test (newer remainder)
      folds:   `folds` sequential equal windows, each scored on its own,
               each compared to buy-and-hold over the same window.
    """
    n = len(closes)
    # Need enough room for a warmup, a meaningful holdout, and non-trivial folds.
    if n <= WARMUP + max(folds * 5, 30) + 2:
        return {"error": "not enough history for walk-forward"}

    comm, slip = cost_model(kind)
    labels = _compute_labels(closes)

    # --- single out-of-sample holdout ---
    split = WARMUP + int((n - WARMUP) * train_frac)
    train = _run(closes, labels, comm, slip, lo=WARMUP, hi=split)
    test = _run(closes, labels, comm, slip, lo=split, hi=n)
    test_bh = _buy_hold(closes, comm, slip, lo=split, hi=n)
    holdout = {
        "split_date": dates[split] if split < len(dates) else str(split),
        "train_frac": train_frac,
        "train": _fold_view(train),
        "test": _fold_view(test),
        "test_buy_hold_pct": test_bh,
        "test_vs_buy_hold": round(test["return_pct"] - test_bh, 2),
        # "holds up" = it actually traded out-of-sample and ended positive.
        "holds_up": test["num_trades"] > 0 and test["return_pct"] > 0,
    }

    # --- sequential time folds ---
    bounds = [WARMUP + round((n - WARMUP) * f / folds) for f in range(folds + 1)]
    fold_results: list[dict] = []
    for f in range(folds):
        lo, hi = bounds[f], bounds[f + 1]
        if hi - lo < 5:
            continue
        r = _run(closes, labels, comm, slip, lo=lo, hi=hi)
        fold_results.append({
            "fold": f + 1,
            "from": dates[lo] if lo < len(dates) else str(lo),
            "to": dates[hi - 1] if hi - 1 < len(dates) else str(hi - 1),
            **_fold_view(r),
            "buy_hold_pct": _buy_hold(closes, comm, slip, lo=lo, hi=hi),
        })

    rets = [fr["return_pct"] for fr in fold_results]
    summary = {
        "folds": len(fold_results),
        "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "positive_folds": sum(1 for r in rets if r > 0),
        "beat_hold_folds": sum(1 for fr in fold_results
                               if fr["return_pct"] > fr["buy_hold_pct"]),
        "best_fold_pct": max(rets, default=None),
        "worst_fold_pct": min(rets, default=None),
    }
    return {
        "kind": kind,
        "holdout": holdout,
        "folds": fold_results,
        "fold_summary": summary,
        "note": ("Fixed-rule strategy (no fitted params): this checks edge "
                 "stability across time, not parameter overfitting."),
    }
