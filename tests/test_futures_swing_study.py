"""The futures swing study must not flatter itself.

Pins the v1 rule exactly (enter on STRONG BUY, leave on SELL/STRONG SELL,
next-open fills), the short mirror, no same-bar flip, cost charged per round
trip in points, labels that never see a future close, and every gate able to
go red, including G6 (a rule that only rides the drift must fail).
"""
import importlib.util
import os
import random

import pytest

pytestmark = pytest.mark.unit

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools",
                     "futures_swing_study.py")
_spec = importlib.util.spec_from_file_location("futures_swing_study", _PATH)
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

SB, B, N, S, SS = "STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"


def bars_from_opens(opens, closes=None):
    closes = closes or opens
    return [[k * 3600.0, min(o, c) - 1, max(o, c) + 1, float(o), float(c), 0.0]
            for k, (o, c) in enumerate(zip(opens, closes))]


def test_prereg_fingerprint_is_stable():
    assert fs.prereg_fingerprint() == fs.prereg_fingerprint()
    assert len(fs.prereg_fingerprint()) == 64


def test_long_enters_and_exits_at_the_next_open_net_of_cost():
    bars = bars_from_opens([100, 101, 102, 103, 110, 120, 125, 130])
    labels = [None, SB, N, N, B, S, N, N]
    t = fs.simulate(bars, labels, "L", usd_per_pt=5.0, rt_cost_pts=0.9)
    assert len(t) == 1
    assert t[0]["entry"] == 102 and t[0]["t_entry"] == bars[2][0], "fills at the open AFTER the signal close"
    assert t[0]["exit"] == 125, "exit fills at the open after the SELL close"
    assert t[0]["pnl_pts"] == pytest.approx(125 - 102 - 0.9)
    assert t[0]["usd"] == pytest.approx((125 - 102 - 0.9) * 5.0)
    assert t[0]["bars"] == 4 and t[0]["reason"] == "signal"


def test_long_only_rule_never_shorts():
    bars = bars_from_opens([100] * 6)
    assert fs.simulate(bars, [None, SS, SS, N, N, N], "L", 5.0, 0.9) == []


def test_a_buy_label_alone_does_not_enter():
    bars = bars_from_opens([100] * 6)
    assert fs.simulate(bars, [None, B, B, B, N, N], "LS", 5.0, 0.9) == []


def test_the_short_mirror_earns_the_mirrored_dollars():
    opens = [100, 101, 102, 103, 110, 120, 125, 130]
    labels = [None, SB, N, N, B, S, N, N]
    mirror = {SB: SS, SS: SB, B: S, S: B, N: N, None: None}
    long_t = fs.simulate(bars_from_opens(opens), labels, "LS", 2.0, 1.5)
    short_t = fs.simulate(bars_from_opens([200 - o for o in opens]), [mirror[x] for x in labels], "LS", 2.0, 1.5)
    assert [x["dir"] for x in short_t] == [-1]
    assert short_t[0]["usd"] == pytest.approx(long_t[0]["usd"])


def test_no_same_bar_flip_from_long_to_short():
    bars = bars_from_opens([100, 100, 100, 100, 100, 100, 100])
    labels = [SB, N, SS, SS, N, N, N]
    t = fs.simulate(bars, labels, "LS", 5.0, 0.0)
    assert [(x["dir"], x["t_entry"]) for x in t[:2]] == [(1, bars[1][0]), (-1, bars[4][0])], \
        "the exit fills at open 3; the short needs a flat book at a close, so it fills at open 4"


def test_an_open_position_is_closed_at_the_last_close():
    bars = bars_from_opens([100, 101, 102, 103], closes=[100, 101, 102, 107])
    t = fs.simulate(bars, [SB, N, N, N], "L", 5.0, 0.9)
    assert t[0]["reason"] == "end" and t[0]["exit"] == 107 and t[0]["bars"] == 3


def test_a_signal_on_the_last_bar_opens_nothing():
    bars = bars_from_opens([100, 100, 100])
    assert fs.simulate(bars, [None, None, SB], "L", 5.0, 0.9) == []


def test_labels_never_see_a_future_close():
    rnd = random.Random(7)
    px, closes = 5000.0, []
    for _ in range(620):
        px *= 1 + rnd.gauss(0, 0.004)
        closes.append(px)
    spec = {"htf_factor": 24, "window": 1400, "warmup": 504}
    base = fs.labels_for(closes, spec)
    k = 560
    shocked = closes[:k + 1] + [c * 3 for c in closes[k + 1:]]
    assert fs.labels_for(shocked, spec)[:k + 1] == base[:k + 1]
    assert base[:504] == [None] * 504 and all(x is not None for x in base[504:])


def test_the_hourly_label_uses_only_the_trailing_window():
    rnd = random.Random(3)
    closes = [100 + rnd.gauss(0, 1) for _ in range(300)]
    spec = {"htf_factor": 24, "window": 120, "warmup": 250}
    far_past_changed = [c * 5 for c in closes[:150]] + closes[150:]
    assert fs.labels_for(far_past_changed, spec)[270:] == fs.labels_for(closes, spec)[270:]


def test_clean_bars_drops_the_unfinished_bar_and_holes():
    raw = {"timestamp": [0, 3600, 7200, 10800],
           "indicators": {"quote": [{"open": [1, None, 3, 4], "high": [1, 2, 3, 4], "low": [1, 2, 3, 4],
                                     "close": [1, 2, 3, 4], "volume": [None, 0, 5, 5]}]}}
    out = fs.clean_bars(raw, now_s=12000, bar_s=3600)
    assert [b[0] for b in out] == [0.0, 7200.0], "bar 3600 has a hole; bar 10800 ends after now"


def _stats(net, trades=30, pf=2.0, dd=100.0, bars=300):
    return {"trades": trades, "net_usd": net, "profit_factor": pf, "max_dd_usd": dd, "bars_in_market": bars}


def _passing():
    per = {"MES": {"oos": _stats(500)}, "MNQ": {"oos": _stats(400)}}
    return per, _stats(900), _stats(900, dd=300), {"usd": 1000.0, "bars": 2000}


def test_verdict_passes_only_when_every_gate_holds():
    per, pi, po, h = _passing()
    assert fs.verdict(per, pi, po, h)["ALL_PASS"]


@pytest.mark.parametrize("gate,mutate", [
    ("G1", lambda per, pi, po, h: per["MNQ"]["oos"].update(net_usd=-1.0)),
    ("G2", lambda per, pi, po, h: po.update(profit_factor=1.29)),
    ("G3", lambda per, pi, po, h: po.update(trades=19)),
    ("G4", lambda per, pi, po, h: po.update(max_dd_usd=901.0)),
    ("G5", lambda per, pi, po, h: pi.update(net_usd=0.0)),
    ("G6", lambda per, pi, po, h: h.update(usd=900.0 / 300 * 2000)),
])
def test_every_gate_can_go_red(gate, mutate):
    per, pi, po, h = _passing()
    mutate(per, pi, po, h)
    v = fs.verdict(per, pi, po, h)
    assert not v[gate]["pass"] and not v["ALL_PASS"]


def test_a_rule_that_is_never_in_the_market_fails_g6():
    per, pi, po, h = _passing()
    po.update(bars_in_market=0)
    assert not fs.verdict(per, pi, po, h)["G6"]["pass"]


def test_riding_the_drift_does_not_beat_holding():
    """Always long == hold: its $/bar cannot beat hold's, so G6 must be red."""
    opens = [100 + k for k in range(40)]
    bars = bars_from_opens(opens)
    labels = [SB] + [N] * 39
    t = fs.simulate(bars, labels, "L", 5.0, 0.9)
    st = fs.stats(t)
    h = fs.hold(bars[1:], 5.0, 0.9)
    per = {"MES": {"oos": _stats(1.0)}, "MNQ": {"oos": _stats(1.0)}}
    assert not fs.verdict(per, _stats(1.0), {**st, "trades": 30, "profit_factor": 2.0}, h)["G6"]["pass"]
