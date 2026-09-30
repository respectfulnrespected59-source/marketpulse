"""The Para-Sail engine (owner 2026-09-30): one pure function the lesson compiler and the app both run,
so a number a lesson says out loud is the number the app shows for the same prices.

  BUY        one fill when the close sits within `zone` of the lowest close of the last `low_days`
             calendar days, at most once every `gap_days`
  PARA-SAIL  once the open position is worth `sail_at` more than it cost, sell `sell` of it — once
             per wave; the next buy re-arms it. hold = never sell (BTC is held)
  CAP        never more than `cap` of your own money in (put in minus taken out)
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "classes"))

import backtest  # noqa: E402
import lesson_compiler as lc  # noqa: E402
import parasail  # noqa: E402

pytestmark = pytest.mark.unit

DAY = 86_400
T0 = 1_760_000_000 - (1_760_000_000 % DAY)
SIDE = sum(backtest.cost_model("crypto"))


def days(n):
    return [T0 + i * DAY for i in range(n)]


def rules(**over):
    base = {"low_days": 3, "zone": 0.08, "gap_days": 1, "fill": 100, "cap": 10_000}
    return parasail.Rules.from_spec({**base, **over})


SAIL = [100.0, 120.0, 150.0, 160.0, 170.0, 90.0, 95.0, 200.0]


def test_rules_default_to_the_owners_settings():
    r = parasail.Rules.from_spec({})
    assert (r.low_days, r.zone, r.gap_days, r.sail_at, r.sell, r.hold) == (30, 0.08, 7, 0.40, 0.5, False)


def test_buys_inside_the_zone_sails_half_once_per_wave():
    out = parasail.simulate(days(len(SAIL)), SAIL, "crypto", rules())
    assert [b["bar"] for b in out["buys"]] == [0, 5, 6]
    assert [s["bar"] for s in out["sails"]] == [2, 7]


def test_hold_never_sells():
    out = parasail.simulate(days(len(SAIL)), SAIL, "crypto", rules(hold=True))
    assert out["sails"] == []
    assert out["profit"] == pytest.approx(out["hold_profit"])


def test_money_is_scored_against_the_peak_after_costs():
    out = parasail.simulate(days(len(SAIL)), SAIL, "crypto", rules())
    units = (1 - SIDE)
    sold1 = units / 2 * 150 * (1 - SIDE)
    units = units / 2 + 100 * (1 - SIDE) / 90 + 100 * (1 - SIDE) / 95
    sold2 = units / 2 * 200 * (1 - SIDE)
    units /= 2
    assert out["peak"] == pytest.approx(300 - sold1)
    assert out["profit"] == pytest.approx(units * 200 - (300 - sold1 - sold2))
    assert out["roi"] == pytest.approx(out["profit"] / out["peak"] * 100)


def test_a_month_is_calendar_days_so_weekends_do_not_stretch_a_stock_window():
    # Mon..Fri, Mon..Fri: a 7-day window on the second Friday reaches back to the Saturday before it,
    # so it holds that week's 5 trading bars only — never last Friday's 80.
    ts = [T0 + d * DAY for d in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)]
    closes = [100.0, 100.0, 100.0, 100.0, 80.0, 95.0, 96.0, 97.0, 98.0, 99.0]
    low, bar = parasail.trailing_low(ts, closes, 9, 7)
    assert (low, bar) == (95.0, 5)


def test_no_cap_means_no_cap():
    # Owner 09-30: "leave BTC uncapped" — the coin held as money is not limited to 10 % of the pile.
    assert parasail.Rules.from_spec({"cap": None}).cap is None
    out = parasail.simulate(days(10), [100.0] * 10, "crypto", rules(cap=None))
    assert [b["bar"] for b in out["buys"]] == list(range(10))
    assert "cap_bar" not in out and out["peak"] == 1000


def test_the_cap_names_the_first_day_it_refused_a_buy():
    out = parasail.simulate(days(10), [100.0] * 10, "crypto", rules(cap=300))
    assert [b["bar"] for b in out["buys"]] == [0, 1, 2]
    assert out["cap_bar"] == 3


def test_a_window_only_trades_inside_it_but_can_see_the_low_before_it():
    closes = [80.0, 100.0, 100.0, 100.0]
    # From bar 1 the last 3 days still hold bar 0's 80: 100 sits 25 % above it, outside the 8 % zone.
    out = parasail.simulate(days(4), closes, "crypto", rules(), start=1)
    assert [b["bar"] for b in out["buys"]] == [3]   # bar 3: 80 has left the window, 100 is the low


@pytest.mark.parametrize("bad", [
    {"zone": 0}, {"zone": 1.5}, {"zone": True}, {"low_days": 0}, {"low_days": 2.5}, {"gap_days": 0},
    {"fill": 0}, {"cap": 50}, {"sail_at": 0}, {"sell": 0}, {"sell": 1.5}, {"hold": "yes"},
    {"zone": float("nan")}, {"fill": float("inf")},
])
def test_nonsense_rules_are_refused(bad):
    with pytest.raises(parasail.ParaSailError):
        rules(**bad)


def test_mismatched_or_empty_prices_are_refused():
    with pytest.raises(parasail.ParaSailError):
        parasail.simulate(days(3), [100.0, 101.0], "crypto", rules())
    with pytest.raises(parasail.ParaSailError):
        parasail.simulate([], [], "crypto", rules())


def test_the_lesson_compiler_runs_this_same_engine():
    tape = {"symbol": "BTC", "kind": "crypto", "tf": "1D", "ts": days(len(SAIL)),
            "ohlc": [[c, c * 1.01, c * 0.99, c] for c in SAIL]}
    spec = {"fn": "parasail", "low_days": 3, "zone": 0.08, "gap_days": 1, "fill": 100, "cap": 10_000}
    var = lc.compute_vars({"p": spec}, tape)["p"]
    out = parasail.simulate(tape["ts"], SAIL, "crypto", rules())
    assert var.buys == out["buys"] and var.sails == out["sails"]
    assert (var.profit, var.peak, var.roi) == (out["profit"], out["peak"], out["roi"])
