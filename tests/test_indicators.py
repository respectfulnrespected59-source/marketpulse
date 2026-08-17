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


# ------------------------------------------------- TTM squeeze, per bar
#
# ttm_squeeze() answers "what is it doing right now" in one dict. Drawing it
# needs the same reading at EVERY bar: the Bollinger/Keltner lines you watch
# pinch together, a dot per bar saying whether it was compressed, and the
# momentum histogram underneath.
#
# The load-bearing test in here is the agreement one. The chart and the chip
# are two renderings of one truth, and if the series ever disagreed with
# ttm_squeeze() the screen would argue with itself — dots showing a coil while
# the badge says off. So the series is checked against the existing function
# as the authority, not against my own re-derivation of the same formula.

def _coiled_bars(n=60):
    """Flat range = Bollinger bands sit inside the Keltner channel."""
    return [105.0] * n, [95.0] * n, [100.0] * n


def _expanded_bars(n=60):
    closes = [float(i) for i in range(n)]
    return [c + 0.01 for c in closes], [c - 0.01 for c in closes], closes


class TestSqueezeProximity:
    """How FAR is the squeeze from forming — not just whether it has.

    The chip can say on / off / fired, which means it only ever reports a
    squeeze that already exists. A trader watching the bands pinch can see it
    coming a few bars out; the indicator could not say so. These gaps are that
    reading: the distance each Bollinger band still has to travel before it
    closes inside the Keltner channel.

    Sign convention is chosen so both gaps mean the same thing:
        positive = still outside, squeeze has NOT formed
        negative = inside, compressed
    """

    def test_an_expanded_market_reports_positive_gaps(self):
        h, l, c = _expanded_bars()
        out = ind.ttm_squeeze(h, l, c)
        assert out["gap_upper"] > 0 or out["gap_lower"] > 0

    def test_a_coiled_market_reports_negative_gaps(self):
        h, l, c = _coiled_bars()
        out = ind.ttm_squeeze(h, l, c)
        assert out["gap_upper"] < 0
        assert out["gap_lower"] < 0

    def test_the_gaps_agree_with_the_state_it_reports(self):
        # The proximity numbers and the on/off verdict are two views of one
        # measurement; if they ever disagree the chip contradicts itself.
        for bars in (_coiled_bars(), _expanded_bars()):
            out = ind.ttm_squeeze(*bars)
            compressed = out["gap_upper"] < 0 and out["gap_lower"] < 0
            assert compressed is (out["state"] == "on")

    def test_it_reports_the_worst_of_the_two_gaps(self):
        # A squeeze needs BOTH bands inside, so the binding constraint is
        # whichever side is further out.
        out = ind.ttm_squeeze(*_expanded_bars())
        assert out["gap"] == max(out["gap_upper"], out["gap_lower"])

    def test_it_reports_the_band_width(self):
        out = ind.ttm_squeeze(*_expanded_bars())
        assert out["width"] > 0

    def test_a_flat_market_does_not_divide_by_zero(self):
        n = 60
        out = ind.ttm_squeeze([100.0] * n, [100.0] * n, [100.0] * n)
        assert out is not None
        assert "gap" in out


class TestTtmSqueezeSeries:
    def test_too_little_history_is_none(self):
        assert ind.ttm_squeeze_series([1.0] * 5, [1.0] * 5, [1.0] * 5) is None

    def test_every_series_is_bar_aligned(self):
        h, l, c = _coiled_bars()
        out = ind.ttm_squeeze_series(h, l, c)
        for key in ("bb_upper", "bb_lower", "kc_upper", "kc_lower", "basis", "on", "mom"):
            assert len(out[key]) == len(c), key

    def test_warmup_bars_are_none_not_zero(self):
        # A zero band would draw a line across the chart at price 0.
        h, l, c = _coiled_bars()
        out = ind.ttm_squeeze_series(h, l, c)
        assert out["bb_upper"][0] is None
        assert out["basis"][0] is None
        assert out["on"][0] is None

    def test_the_last_reading_agrees_with_ttm_squeeze(self):
        # THE contract: chart and chip must never disagree.
        for bars in (_coiled_bars(), _expanded_bars()):
            h, l, c = bars
            scalar = ind.ttm_squeeze(h, l, c)
            series = ind.ttm_squeeze_series(h, l, c)
            assert series["on"][-1] is (scalar["state"] == "on")

    def test_the_bar_count_agrees_with_ttm_squeeze(self):
        # Consecutive compressed dots must equal the "ON·N" the badge shows.
        h, l, c = _coiled_bars()
        scalar = ind.ttm_squeeze(h, l, c)
        series = ind.ttm_squeeze_series(h, l, c)
        run = 0
        for flag in reversed(series["on"]):
            if flag:
                run += 1
            else:
                break
        assert run == scalar["bars"]

    def test_a_coiled_market_marks_the_dots_on(self):
        h, l, c = _coiled_bars()
        assert ind.ttm_squeeze_series(h, l, c)["on"][-1] is True

    def test_an_expanded_market_marks_the_dots_off(self):
        h, l, c = _expanded_bars()
        assert ind.ttm_squeeze_series(h, l, c)["on"][-1] is False

    def test_when_compressed_the_bollinger_band_sits_inside_the_keltner(self):
        # This IS the squeeze definition — the visual the trader is watching.
        h, l, c = _coiled_bars()
        out = ind.ttm_squeeze_series(h, l, c)
        i = len(c) - 1
        assert out["bb_upper"][i] < out["kc_upper"][i]
        assert out["bb_lower"][i] > out["kc_lower"][i]

    def test_bands_are_ordered_wherever_they_are_drawn(self):
        h, l, c = _expanded_bars()
        out = ind.ttm_squeeze_series(h, l, c)
        for i in range(len(c)):
            if out["bb_upper"][i] is None:
                continue
            assert out["bb_upper"][i] >= out["basis"][i] >= out["bb_lower"][i]
            assert out["kc_upper"][i] >= out["basis"][i] >= out["kc_lower"][i]

    def test_the_histogram_has_values_on_recent_bars(self):
        h, l, c = _expanded_bars()
        mom = ind.ttm_squeeze_series(h, l, c)["mom"]
        assert mom[-1] is not None
        assert any(v is not None for v in mom)

    def test_a_rising_market_ends_with_positive_momentum(self):
        # Sign drives the histogram's colour, so it has to be right.
        h, l, c = _expanded_bars()
        assert ind.ttm_squeeze_series(h, l, c)["mom"][-1] > 0

    def test_a_falling_market_ends_with_negative_momentum(self):
        closes = [float(60 - i) for i in range(60)]
        highs = [x + 0.01 for x in closes]
        lows = [x - 0.01 for x in closes]
        assert ind.ttm_squeeze_series(highs, lows, closes)["mom"][-1] < 0

    def test_dead_flat_data_does_not_divide_by_zero(self):
        n = 60
        out = ind.ttm_squeeze_series([100.0] * n, [100.0] * n, [100.0] * n)
        assert out is not None
        assert out["bb_upper"][-1] is not None

    def test_it_reports_the_length_it_used(self):
        h, l, c = _coiled_bars()
        assert ind.ttm_squeeze_series(h, l, c)["length"] == 20
