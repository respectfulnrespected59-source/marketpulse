"""Tests for the DCA Wizard — deterministic, synthetic price series only.

Verifies the accumulation math, the no-lookahead signal tilt, the honest
three-way comparison, and the forward projection compounding.
"""
import math

import pytest

import dca

pytestmark = pytest.mark.unit


# ------------------------------------------------------------ helpers / knobs
def test_per_period_amount_holds_annual_spend_constant():
    # $200/mo = $2400/yr, spread across each cadence's periods-per-year.
    assert dca.per_period_amount(200, "monthly") == 200.0
    assert dca.per_period_amount(200, "weekly") == round(200 * 12 / 52, 2)
    assert dca.per_period_amount(200, "biweekly") == round(200 * 12 / 26, 2)


def test_bars_per_period_by_kind():
    assert dca.bars_per_period("weekly", "stock") == 5
    assert dca.bars_per_period("weekly", "crypto") == 7
    assert dca.bars_per_period("monthly", "stock") == 21
    assert dca.bars_per_period("bogus", "stock") == 21  # falls back to monthly


def test_tilt_from_score_bounds_and_direction():
    assert dca.tilt_from_score(0) == 1.0
    assert dca.tilt_from_score(6) == pytest.approx(1.5)   # max cheap tilt
    assert dca.tilt_from_score(-6) == pytest.approx(0.5)  # max rich trim
    assert dca.tilt_from_score(99) == 1.5                 # clamped up
    assert dca.tilt_from_score(-99) == 0.5                # clamped down
    assert dca.tilt_from_score(3) > 1.0 and dca.tilt_from_score(-3) < 1.0


# ------------------------------------------------------------ accumulation math
def _flat(n, price=100.0):
    dates = [f"2024-01-{(i % 28) + 1:02d}" for i in range(n)]
    closes = [price] * n
    return dates, closes


def test_plain_dca_constant_price_only_loses_slippage():
    dates, closes = _flat(210)  # 10 monthly buys (step 21)
    r = dca.simulate_dca(dates, closes, "stock", 200.0, "monthly", "plain")
    assert r["periods"] == 10
    assert r["invested"] == 2000.0
    # stock: 0 commission, 5bps slippage/side -> final = invested / 1.0005
    assert r["return_pct"] == pytest.approx((1 / 1.0005 - 1) * 100, abs=0.01)
    assert r["avg_cost"] == pytest.approx(100 * 1.0005, abs=0.01)
    assert all(c["tilt"] == 1.0 for c in r["contributions"])  # plain never tilts


def test_lump_sum_deploys_full_budget_on_day_one():
    dates, closes = _flat(210)
    r = dca.simulate_lump(dates, closes, "stock", 2000.0)
    assert r["periods"] == 1
    assert r["invested"] == 2000.0
    assert r["return_pct"] == pytest.approx((1 / 1.0005 - 1) * 100, abs=0.01)


def test_dca_profits_when_price_rises_after_buying():
    # steady climb over the window -> positive return, avg cost below final.
    dates = [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(210)]
    closes = [100 + i for i in range(210)]  # 100 -> 309
    r = dca.simulate_dca(dates, closes, "stock", 200.0, "monthly", "plain")
    assert r["return_pct"] > 0
    assert r["avg_cost"] < r["final_price"]
    assert r["shares"] > 0


# ------------------------------------------------------------ no-lookahead tilt
def test_tilt_first_buy_is_neutral_no_lookahead():
    dates = [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(210)]
    closes = [100 + 5 * math.sin(i / 7) + 0.3 * i for i in range(210)]
    r = dca.simulate_dca(dates, closes, "stock", 200.0, "monthly", "tilt")
    # Bar 0 is before indicator warmup -> tilt must be exactly neutral.
    assert r["contributions"][0]["tilt"] == 1.0


def test_tilt_varies_and_stays_in_bounds():
    dates = [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(400)]
    closes = [100 + 20 * math.sin(i / 11) for i in range(400)]  # choppy -> tilts move
    r = dca.simulate_dca(dates, closes, "stock", 200.0, "monthly", "tilt")
    tilts = [c["tilt"] for c in r["contributions"]]
    assert all(dca.MIN_TILT <= t <= dca.MAX_TILT for t in tilts)
    assert len(set(tilts)) > 1  # the tilt actually did something


# ------------------------------------------------------------ regime + verdict
def test_regime_classification():
    assert dca._regime([100, 130])["tag"] == "up"
    assert dca._regime([100, 70])["tag"] == "down"
    assert dca._regime([100, 103])["tag"] == "flat"


def test_verdict_ranks_by_return_and_is_honest():
    plain = {"return_pct": 10.0}
    tilt = {"return_pct": 8.0}
    lump = {"return_pct": 25.0}
    v = dca._verdict(plain, lump, tilt, {"tag": "up"})
    assert v["winner_by_return"] == "lump"
    assert v["ranking"] == ["lump", "plain", "tilt"]
    assert v["tilt_helped"] is False
    assert v["tilt_vs_plain_pct"] == -2.0
    assert "Lump sum beats DCA" in v["honest_truth"]


# ------------------------------------------------------------ projection
def test_projection_compounds_and_bear_equals_contributions():
    p = dca.project(200.0, "monthly", 10)
    assert p["periods"] == 120
    assert p["contributed"] == 24000.0
    # 0% scenario: future value == what you put in, zero growth.
    assert p["scenarios"]["bear"]["future_value"] == pytest.approx(24000.0)
    assert p["scenarios"]["bear"]["growth"] == pytest.approx(0.0)
    # positive rate: annuity future-value formula.
    r = 0.07 / 12
    expected = 200.0 * (((1 + r) ** 120 - 1) / r)
    assert p["scenarios"]["base"]["future_value"] == pytest.approx(expected, abs=1.0)
    assert p["scenarios"]["bull"]["future_value"] > p["scenarios"]["base"]["future_value"]


# ------------------------------------------------------------ full report
def test_dca_report_shape_and_bad_cadence_fallback():
    dates = [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(300)]
    closes = [100 + 0.2 * i + 6 * math.sin(i / 9) for i in range(300)]
    r = dca.dca_report(dates, closes, "stock", "test", 200.0, "nonsense", 10)
    assert r["symbol"] == "TEST"
    assert r["plan"]["cadence"] == "monthly"  # bad cadence -> monthly
    for style in ("plain", "tilt", "lump"):
        assert style in r["backtest"]
    assert r["verdict"]["winner_by_return"] in ("plain", "tilt", "lump")
    assert set(r["projection"]["scenarios"]) == {"bear", "base", "bull"}
    assert "tilt" in r["nudge"] and 0.5 <= r["nudge"]["tilt"] <= 1.5
    assert r["series"]["closes"]  # chart data present
