"""Tests for indicators.py — the technical-analysis math behind every signal.

Expected values are hand-computed so a regression in the math is caught, not
just a crash. Pure functions, no network, no I/O.
"""
from __future__ import annotations

import pytest

import indicators as ind

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------- SMA
def test_sma_basic():
    assert ind.sma([1, 2, 3, 4], 2) == 3.5  # (3+4)/2


def test_sma_too_few_values_is_none():
    assert ind.sma([1, 2], 3) is None


def test_sma_nonpositive_period_is_none():
    assert ind.sma([1, 2, 3], 0) is None


# ----------------------------------------------------------------- EMA
def test_ema_series_seeds_with_sma():
    # k=2/3, seed=(1+2)/2=1.5 -> 3*k+1.5*(1-k)=2.5 -> 4*k+2.5*(1-k)=3.5
    assert ind.ema_series([1, 2, 3, 4], 2) == pytest.approx([1.5, 2.5, 3.5])


def test_ema_latest_value():
    assert ind.ema([1, 2, 3, 4], 2) == pytest.approx(3.5)


def test_ema_too_short_is_none():
    assert ind.ema([1, 2], 5) is None


# ----------------------------------------------------------------- RSI
def test_rsi_all_gains_is_100():
    assert ind.rsi(list(range(1, 17)), 14) == 100.0


def test_rsi_all_losses_is_0():
    assert ind.rsi(list(range(16, 0, -1)), 14) == 0.0


def test_rsi_insufficient_history_is_none():
    assert ind.rsi([1, 2, 3], 14) is None


# ----------------------------------------------------------------- MACD
def test_macd_constant_series_is_flat():
    line, sig, hist = ind.macd([5.0] * 40)
    assert line == 0.0 and sig == 0.0 and hist == 0.0


def test_macd_too_short_is_none_triple():
    assert ind.macd([1, 2, 3]) == (None, None, None)


def test_macd_accelerating_uptrend_histogram_positive():
    # A *linear* ramp makes the MACD line constant -> histogram ~0. Momentum
    # only shows up when the trend accelerates, so use a convex (i**2) series.
    _, _, hist = ind.macd([float(i * i) for i in range(1, 60)])
    assert hist is not None and hist > 0


# ----------------------------------------------------------------- Bollinger %B
def test_bollinger_flat_window_is_midpoint():
    assert ind.bollinger_pct_b([5.0] * 20) == 0.5


def test_bollinger_too_short_is_none():
    assert ind.bollinger_pct_b([1, 2, 3], 20) is None


def test_bollinger_uptrend_above_midpoint():
    pb = ind.bollinger_pct_b([float(i) for i in range(20)])
    assert pb is not None and pb > 0.5


# ----------------------------------------------------------------- Stochastic
def test_stochastic_top_of_range_is_100():
    assert ind.stochastic_k([1, 2, 3, 4, 5], 5) == 100.0


def test_stochastic_flat_window_is_50():
    assert ind.stochastic_k([5.0] * 5, 5) == 50.0


def test_stochastic_too_short_is_none():
    assert ind.stochastic_k([1, 2], 14) is None


# ----------------------------------------------------------------- HTF trend
def test_htf_trend_factor_below_two_is_zero():
    assert ind.htf_trend(list(range(200)), factor=1) == 0


def test_htf_trend_uptrend_is_plus_one():
    assert ind.htf_trend(list(range(120)), factor=5, period=20) == 1


def test_htf_trend_downtrend_is_minus_one():
    assert ind.htf_trend(list(range(120, 0, -1)), factor=5, period=20) == -1


# ----------------------------------------------------------------- score_signals
def test_score_signals_clean_uptrend_reads_buy():
    sig = ind.score_signals([float(i) for i in range(1, 251)])
    assert sig["label"] == "BUY"
    assert sig["score"] == 1
    assert "above SMA50" in sig["reasons"]
    assert "golden cross (50>200)" in sig["reasons"]


def test_score_signals_clean_downtrend_reads_sell():
    sig = ind.score_signals([float(i) for i in range(250, 0, -1)])
    assert sig["label"] == "SELL"
    assert sig["score"] == -1
    assert "below SMA50" in sig["reasons"]
    assert "death cross (50<200)" in sig["reasons"]


def test_score_signals_exposes_transparent_fields():
    sig = ind.score_signals([float(i) for i in range(1, 100)])
    for key in ("score", "label", "css", "rsi", "macd_hist", "htf", "reasons"):
        assert key in sig
    assert isinstance(sig["reasons"], list) and sig["reasons"]


# ----------------------------------------------------------------- MA stack
def test_ma_stack_uptrend_is_bull():
    assert ind.ma_stack(list(range(1, 30)))["stack"] == "bull"


def test_ma_stack_downtrend_is_bear():
    assert ind.ma_stack(list(range(30, 0, -1)))["stack"] == "bear"


def test_ma_stack_empty_is_none():
    assert ind.ma_stack([]) is None


def test_ma_stack_too_few_for_full_stack_is_mixed():
    out = ind.ma_stack([1, 2, 3])
    assert out["stack"] == "mixed" and out["ma5"] is None


# ----------------------------------------------------------------- VWAP
def test_session_vwap_volume_weighted():
    # tp1=(10+8+9)/3=9, tp2=(20+18+19)/3=19, equal volume -> 14.0
    assert ind.session_vwap([10, 20], [8, 18], [9, 19], [100, 100]) == 14.0


def test_session_vwap_zero_volume_is_none():
    assert ind.session_vwap([10], [8], [9], [0]) is None


# ----------------------------------------------------------------- resample
def test_resample_ohlc_factor_two():
    H, L, C = ind.resample_ohlc([1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4], factor=2)
    assert H == [2, 4]
    assert L == [1, 3]
    assert C == [2, 4]  # close of each coarse bar = last fine close in it


# ----------------------------------------------------------------- TTM squeeze
def test_ttm_squeeze_insufficient_history_is_none():
    assert ind.ttm_squeeze([1] * 10, [1] * 10, [1] * 10) is None


def test_ttm_squeeze_flat_closes_wide_ranges_is_on():
    # Flat closes (std=0 -> tiny Bollinger) but wide H/L (big true range ->
    # wide Keltner) => Bollinger sits inside Keltner => squeeze ON.
    n = 50
    out = ind.ttm_squeeze([105.0] * n, [95.0] * n, [100.0] * n)
    assert out["state"] == "on"
    assert out["bars"] >= 1


def test_ttm_squeeze_expanded_market_is_off():
    # Closes track their own bar's range (no compression) -> not coiling.
    n = 50
    closes = [float(i) for i in range(n)]
    highs = [c + 0.01 for c in closes]
    lows = [c - 0.01 for c in closes]
    out = ind.ttm_squeeze(highs, lows, closes)
    assert out["state"] in ("off", "fired")
