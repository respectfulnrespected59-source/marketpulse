"""The FX + futures scalper study must not flatter itself either.

Adds to the crypto study's pins what the new venue brings: the short side
(a mirrored market must produce the mirrored trades, to the R), costs charged
in pips/points, and session gaps (no fills across a closed market, and flat
before one).
"""
import importlib.util
import os
import random

import pytest

pytestmark = pytest.mark.unit

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools",
                     "fx_futures_scalper_study.py")
_spec = importlib.util.spec_from_file_location("fx_futures_scalper_study", _PATH)
fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fx)

T0 = 1_800_000_000 - (1_800_000_000 % 3600)
GAP = 2 * 86400                                          # a weekend


def bar(k, o, h, l, c):
    return [T0 + k * 300, l, h, o, c, 0.0]


def flat(n, px=100.0):
    return [bar(k, px, px + 0.1, px - 0.1, px) for k in range(n)]


def breakdown(n=60):
    """Flat tape; bar 40 closes under the prior-12 low."""
    bars = flat(n)
    bars[40] = bar(40, 100.0, 100.1, 99.0, 99.1)
    return bars


def shut_after(bars, k):
    """The market closes after bar k and reopens a weekend later."""
    return bars[:k + 1] + [[b[0] + GAP] + b[1:] for b in bars[k + 1:]]


def test_prereg_fingerprint_is_stable():
    assert fx.prereg_fingerprint() == fx.prereg_fingerprint()
    assert len(fx.prereg_fingerprint()) == 64


def test_a_short_that_reaches_target_earns_exactly_its_reward_in_r():
    bars = breakdown()
    bars[42] = bar(42, 99.9, 99.95, 99.5, 99.6)          # falls through the target, never near the stop
    tr = fx.simulate(bars, "BRK", 0.0, 1.0, [-1] * len(bars))
    t = tr[0]
    assert t["dir"] == -1 and t["reason"] == "target"
    assert t["entry"] == 100.0 and t["t_entry"] == bars[41][0], "entry is the NEXT bar's open"
    assert t["r"] == pytest.approx(1.2), "target is 1.2 ATR, stop is 1.0 ATR"


def test_a_mirrored_market_gives_mirrored_trades():
    rng = random.Random(7)
    n, px, bars = 2400, 150.0, []
    for k in range(n):
        o = px
        px += rng.gauss(0, 0.15)
        bars.append(bar(k, o, max(o, px) + abs(rng.gauss(0, 0.05)), min(o, px) - abs(rng.gauss(0, 0.05)), px))
    mirror = [[b[0], 300 - b[2], 300 - b[1], 300 - b[3], 300 - b[4], b[5]] for b in bars]
    hourly = [rng.choice((-1, 0, 1)) for _ in range(n // 12 + 1)]
    trend = [hourly[k // 12] for k in range(n)]
    flipped = [-s for s in trend]
    for rule in ("BRK", "DIP"):
        a = fx.simulate(bars, rule, 1.6, 0.01, trend)
        b = fx.simulate(mirror, rule, 1.6, 0.01, flipped)
        assert len(a) > 20 and {x["dir"] for x in a} == {1, -1}, "both sides must actually trade"
        assert [(x["t_entry"], x["dir"], x["reason"]) for x in a] == \
               [(y["t_entry"], -y["dir"], y["reason"]) for y in b], rule
        assert [x["r"] for x in a] == pytest.approx([y["r"] for y in b]), rule


def test_when_stop_and_target_both_hit_in_one_bar_a_short_is_stopped():
    bars = breakdown()
    bars[42] = bar(42, 100.0, 150.0, 50.0, 100.0)
    tr = fx.simulate(bars, "BRK", 0.0, 1.0, [-1] * len(bars))
    assert tr[0]["reason"] == "stop" and tr[0]["r"] == pytest.approx(-1.0)


def test_the_round_trip_cost_comes_off_every_trade_in_price_and_in_r():
    bars = breakdown()
    bars[42] = bar(42, 99.9, 99.95, 99.5, 99.6)          # a real move, so pnl / r recovers the risk
    free = fx.simulate(bars, "BRK", 0.0, 0.01, [-1] * len(bars))[0]
    paid = fx.simulate(bars, "BRK", 1.6, 0.01, [-1] * len(bars))[0]
    risk = free["pnl_px"] / free["r"]
    assert paid["pnl_px"] == pytest.approx(free["pnl_px"] - 0.016)
    assert paid["pnl_pips"] == pytest.approx(free["pnl_pips"] - 1.6)
    assert paid["r"] == pytest.approx(free["r"] - 0.016 / risk)


def test_no_fill_across_a_closed_market():
    bars = shut_after(breakdown(), 40)                   # the signal bar is the last before the close
    assert fx.simulate(bars, "BRK", 0.0, 1.0, [-1] * len(bars)) == []


def test_a_position_goes_flat_before_the_market_closes():
    bars = shut_after(breakdown(), 44)
    tr = fx.simulate(bars, "BRK", 0.0, 1.0, [-1] * len(bars))
    assert tr[0]["reason"] == "session" and tr[0]["exit"] == bars[44][4] and tr[0]["bars"] == 4


def test_the_time_stop_closes_after_twelve_bars():
    tr = fx.simulate(breakdown(80), "BRK", 0.0, 1.0, [-1] * 80)
    assert tr[0]["reason"] == "time" and tr[0]["bars"] == 13


def test_no_trade_without_the_engine_trend():
    bars = breakdown()
    assert fx.simulate(bars, "BRK", 0.0, 1.0, [0] * len(bars)) == []
    assert fx.simulate(bars, "BRK", 0.0, 1.0, [None] * len(bars)) == []
    assert fx.simulate(bars, "BRK", 0.0, 1.0, [1] * len(bars)) == [], "a breakdown is not a long"


def test_the_gate_needs_every_condition():
    per = {s: {"oos": {"net_r": 1.0}} for s in fx.PREREG["universe"]}
    good = {"trades": 150, "net_r": 9.0, "profit_factor": 1.4, "max_dd_r": 8.0}
    assert fx.verdict(per, {"net_r": 2.0}, good)["ALL_PASS"]
    assert not fx.verdict(per, {"net_r": 2.0}, dict(good, trades=99))["ALL_PASS"]
    assert not fx.verdict(per, {"net_r": 2.0}, dict(good, max_dd_r=15.01))["ALL_PASS"]
    assert not fx.verdict(per, {"net_r": 2.0}, dict(good, profit_factor=1.19))["ALL_PASS"]
    assert not fx.verdict(per, {"net_r": -0.1}, good)["ALL_PASS"]
    three = {s: {"oos": {"net_r": 1.0 if k < 3 else -1.0}} for k, s in enumerate(fx.PREREG["universe"])}
    assert not fx.verdict(three, {"net_r": 2.0}, good)["ALL_PASS"]
