"""The scalper study's simulator must not flatter itself.

Each test pins a way intraday backtests commonly lie: peeking at future bars,
reading an hour that has not closed, taking the target when the stop hit first
in the same bar, and forgetting that fees are paid on both legs.
"""
import importlib.util
import os

import pytest

pytestmark = pytest.mark.unit

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "scalper_study.py")
_spec = importlib.util.spec_from_file_location("scalper_study", _PATH)
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)

T0 = 1_800_000_000 - (1_800_000_000 % 3600)     # an hour boundary


def bar(k, o, h, l, c, v=100.0):
    return [T0 + k * 300, l, h, o, c, v]


def flat(n, px=100.0, v=100.0):
    return [bar(k, px, px + 0.1, px - 0.1, px, v) for k in range(n)]


def test_prereg_fingerprint_is_stable():
    assert ss.prereg_fingerprint() == ss.prereg_fingerprint()
    assert len(ss.prereg_fingerprint()) == 64


def test_the_trend_filter_never_reads_an_hour_that_has_not_closed():
    import math
    n = 12 * 300                                           # 300 hours of 5m bars
    bars = []
    for k in range(n):                                     # a wavy uptrend, so hourly scores vary
        px = 100 + k * 0.01 + 3 * math.sin(k / 40)
        bars.append(bar(k, px, px + 0.05, px - 0.05, px))
    crashed = [list(b) for b in bars]
    for b in crashed[-12:]:                                # crash inside the final, open hour
        b[1] = b[2] = b[3] = b[4] = 20.0
    got = ss.hourly_scores(crashed)
    hour_close = {}
    for b in crashed:
        hour_close[int(b[0]) // 3600] = b[4]
    hours = sorted(hour_close)
    prev_hour_closes = [hour_close[h] for h in hours[:-1]]  # everything BEFORE the open hour
    want = ss.indicators.score_signals(prev_hour_closes, htf_factor=24)["score"]
    # the last 5m bar closes ON the hour boundary, when that hour is complete: only
    # the first 11 bars of the open hour must be blind to it
    assert all(s == want for s in got[-12:-1]), "bars inside an hour see only the hour before it"
    peeked = ss.indicators.score_signals([hour_close[h] for h in hours], htf_factor=24)["score"]
    assert peeked != want, "the crash must change the score, or this test proves nothing"


def test_a_breakout_signal_does_not_change_when_the_future_changes():
    bars = flat(60)
    bars[40] = bar(40, 100.0, 101.0, 99.9, 100.9, 400.0)   # clears the prior-12 high on 4x volume
    trend = [1] * len(bars)
    a = ss.simulate(bars, "BRK", 0.0, 0.0, trend)
    future = [list(b) for b in bars]
    for k in range(42, 60):
        future[k] = bar(k, 50.0, 50.1, 49.9, 50.0)
    b = ss.simulate(future, "BRK", 0.0, 0.0, trend)
    assert a and b and a[0]["t_entry"] == b[0]["t_entry"] == bars[41][0], "entry is the NEXT bar's open"


def test_no_trade_without_the_engine_trend():
    bars = flat(60)
    bars[40] = bar(40, 100.0, 101.0, 99.9, 100.9, 400.0)
    assert ss.simulate(bars, "BRK", 0.0, 0.0, [0] * len(bars)) == []
    assert ss.simulate(bars, "BRK", 0.0, 0.0, [None] * len(bars)) == []


def test_when_stop_and_target_both_hit_in_one_bar_the_stop_wins():
    bars = flat(60)
    bars[40] = bar(40, 100.0, 101.0, 99.9, 100.9, 400.0)
    bars[42] = bar(42, 100.0, 150.0, 50.0, 100.0)          # huge range: both levels touched
    tr = ss.simulate(bars, "BRK", 0.0, 0.0, [1] * len(bars))
    assert tr[0]["reason"] == "stop" and tr[0]["ret"] < 0


def test_a_flat_round_trip_loses_both_fees_and_both_slippages():
    bars = flat(60)
    bars[40] = bar(40, 100.0, 101.0, 99.9, 100.9, 400.0)
    tr = ss.simulate(bars, "BRK", 0.0025, 0.0005, [1] * len(bars))
    t = tr[0]
    expected = (1 - 0.0025) ** 2 * (t["exit"] / t["entry"]) - 1
    assert t["ret"] == pytest.approx(expected)
    assert t["entry"] > 100.0 and t["exit"] < t["entry"] * 1.02


def test_the_time_stop_closes_after_twelve_bars():
    bars = flat(80)
    bars[40] = bar(40, 100.0, 101.0, 99.9, 100.9, 400.0)
    tr = ss.simulate(bars, "BRK", 0.0, 0.0, [1] * len(bars))
    assert tr[0]["reason"] == "time" and tr[0]["bars"] == 13   # 12 bars held, sold at the 13th open


def test_the_gate_needs_every_condition():
    stake = ss.PREREG["stake_usd"]
    coin = {"oos": {"net_usd": 1.0}}
    good = {"trades": 80, "net_usd": 5.0, "profit_factor": 1.5, "max_dd_usd": 10.0}
    v = ss.verdict({s: coin for s in ss.PREREG["universe"]}, {"net_usd": 1.0}, good)
    assert v["ALL_PASS"]
    few = dict(good, trades=59)
    assert not ss.verdict({s: coin for s in ss.PREREG["universe"]}, {"net_usd": 1.0}, few)["ALL_PASS"]
    deep = dict(good, max_dd_usd=stake + 0.01)
    assert not ss.verdict({s: coin for s in ss.PREREG["universe"]}, {"net_usd": 1.0}, deep)["ALL_PASS"]
