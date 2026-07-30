"""Chart indicator settings that arrive from a query string.

These are user-facing knobs (EMA periods, squeeze on/off) parsed from untrusted
input, so the parser has to be both forgiving and bounded: a nonsense value
should fall back to the defaults rather than break the chart, and no value
should be able to make the server do unbounded work.
"""

import pytest

from app import (
    DEFAULT_EMA_PERIODS,
    MAX_EMA_LINES,
    MAX_EMA_PERIOD,
    MIN_EMA_PERIOD,
    clean_ema_periods,
)

pytestmark = pytest.mark.unit


class TestCleanEmaPeriods:
    def test_parses_a_normal_list(self):
        assert clean_ema_periods("9,21,50") == (9, 21, 50)

    def test_tolerates_whitespace(self):
        assert clean_ema_periods(" 9 , 21 ") == (9, 21)

    def test_preserves_the_order_the_trader_gave(self):
        # Line colours are assigned by position, so reordering would silently
        # recolour their chart.
        assert clean_ema_periods("50,9,21") == (50, 9, 21)

    def test_drops_duplicates(self):
        assert clean_ema_periods("21,21,9") == (21, 9)

    @pytest.mark.parametrize("raw", [None, "", "   ", ",,,", "abc", "9.5,x"])
    def test_falls_back_to_defaults_when_nothing_usable(self, raw):
        # A broken indicator setting must never blank the chart.
        assert clean_ema_periods(raw) == DEFAULT_EMA_PERIODS

    def test_ignores_junk_but_keeps_the_good_values(self):
        assert clean_ema_periods("9,abc,21") == (9, 21)

    def test_caps_the_number_of_lines(self):
        out = clean_ema_periods("5,9,13,21,34,55,89")
        assert len(out) == MAX_EMA_LINES

    @pytest.mark.parametrize("raw", ["1", "0", "401", "999999"])
    def test_rejects_periods_outside_the_supported_range(self, raw):
        # An unbounded period is a way to make the server do arbitrary work.
        assert clean_ema_periods(raw) == DEFAULT_EMA_PERIODS

    def test_accepts_the_boundary_values(self):
        assert clean_ema_periods(str(MIN_EMA_PERIOD)) == (MIN_EMA_PERIOD,)
        assert clean_ema_periods(str(MAX_EMA_PERIOD)) == (MAX_EMA_PERIOD,)

    def test_negative_values_are_not_periods(self):
        assert clean_ema_periods("-14") == DEFAULT_EMA_PERIODS

    def test_a_huge_input_cannot_blow_up_the_response(self):
        # 10k comma-separated values must still yield at most MAX_EMA_LINES.
        assert len(clean_ema_periods(",".join(str(i) for i in range(2, 10_000)))) \
            == MAX_EMA_LINES
