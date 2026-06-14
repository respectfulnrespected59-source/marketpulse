"""Proof Mode — walk the live signal engine backward over real history.

The whole pitch: we don't claim dollar returns, we *prove the logic*. This runs
the exact same `indicators.score_signals` used on the live dashboard across every
historical bar, records each time it flipped into STRONG BUY / STRONG SELL, and
measures what price actually did over the next 5 / 10 / 30 bars.

Output is descriptive history, NOT a prediction or a performance promise.
"""
from __future__ import annotations

import indicators

HORIZONS = (5, 10, 30)
WARMUP = 50  # bars needed before indicators are meaningful (SMA50 + MACD)


def _forward_returns(closes: list[float], i: int) -> dict:
    """% change from bar i to bar i+h for each horizon (None if not enough data)."""
    base = closes[i]
    out = {}
    for h in HORIZONS:
        j = i + h
        out[f"fwd{h}"] = round((closes[j] - base) / base * 100, 2) if j < len(closes) and base else None
    return out


def backtest_signals(dates: list[str], closes: list[float]) -> dict:
    """Find STRONG BUY / STRONG SELL flips and grade their forward outcome.

    A signal is recorded only on the bar it *enters* a strong state (a state
    change), so we don't double-count every day it stays there.
    """
    events: list[dict] = []
    prev_label = None

    for i in range(WARMUP, len(closes)):
        sig = indicators.score_signals(closes[: i + 1])
        label = sig["label"]
        is_strong = label in ("STRONG BUY", "STRONG SELL")
        if is_strong and label != prev_label:
            direction = "buy" if label == "STRONG BUY" else "sell"
            fwd = _forward_returns(closes, i)
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

    return {"events": events, "summary": _summarize(events)}


def _summarize(events: list[dict]) -> dict:
    """Directional hit-rate + average forward move, per the 30-bar horizon."""
    graded = [e for e in events if e.get("fwd30") is not None]
    buys = [e for e in graded if e["dir"] == "buy"]
    sells = [e for e in graded if e["dir"] == "sell"]

    def hit_rate(group: list[dict]) -> float | None:
        if not group:
            return None
        wins = 0
        for e in group:
            move = e["fwd30"]
            if (e["dir"] == "buy" and move > 0) or (e["dir"] == "sell" and move < 0):
                wins += 1
        return round(wins / len(group) * 100, 1)

    def avg_capture(group: list[dict]) -> float | None:
        """Average move *in the signal's direction* (sell move counts as +abs)."""
        if not group:
            return None
        total = sum((e["fwd30"] if e["dir"] == "buy" else -e["fwd30"]) for e in group)
        return round(total / len(group), 2)

    all_graded = buys + sells
    return {
        "signals": len(events),
        "graded": len(graded),
        "win_rate": hit_rate(all_graded),
        "buy_signals": len(buys),
        "buy_win_rate": hit_rate(buys),
        "sell_signals": len(sells),
        "sell_win_rate": hit_rate(sells),
        "avg_move_30d": avg_capture(all_graded),
        "best": max((e["fwd30"] if e["dir"] == "buy" else -e["fwd30"] for e in all_graded), default=None),
        "worst": min((e["fwd30"] if e["dir"] == "buy" else -e["fwd30"] for e in all_graded), default=None),
    }
