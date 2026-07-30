"""The live-chart data path: candle aggregation, timeframes, and fetch shape.

None of this touches the network — `_get_json` is monkeypatched, so these are
pure assertions about how upstream bars become chart bars.
"""

import pytest

import app

pytestmark = pytest.mark.unit


# Two 5-minute bars that should fold into one 10-minute bar.
BAR_A = [10.0, 12.0, 9.0, 11.0]   # o, h, l, c
BAR_B = [11.0, 15.0, 8.0, 14.0]
TS_A, TS_B = 1753849200, 1753849500
VOL_A, VOL_B = 100.0, 250.0


class TestAggOhlc:
    def test_folds_two_bars_into_one(self):
        ohlc, ts, vol = app._agg_ohlc([BAR_A, BAR_B], [TS_A, TS_B], [VOL_A, VOL_B], 2)

        assert len(ohlc) == 1
        # Open comes from the first bar, close from the second, high/low span both.
        assert ohlc[0] == [10.0, 15.0, 8.0, 14.0]
        # The merged bar is stamped with the start of the window.
        assert ts == [TS_A]
        assert vol == [350.0]

    def test_folds_several_pairs(self):
        bars = [BAR_A, BAR_B] * 3
        stamps = [TS_A, TS_B, TS_A + 600, TS_B + 600, TS_A + 1200, TS_B + 1200]
        vols = [VOL_A, VOL_B] * 3

        ohlc, ts, vol = app._agg_ohlc(bars, stamps, vols, 2)

        assert len(ohlc) == 3
        assert ts == [TS_A, TS_A + 600, TS_A + 1200]
        assert all(v == 350.0 for v in vol)

    def test_drops_a_trailing_unpaired_bar(self):
        # Documented behaviour: an odd final bar is a half-formed 10m candle,
        # so it is left out rather than drawn as if it were complete.
        ohlc, ts, vol = app._agg_ohlc(
            [BAR_A, BAR_B, BAR_A], [TS_A, TS_B, TS_A + 600], [VOL_A, VOL_B, VOL_A], 2
        )
        assert len(ohlc) == 1
        assert len(ts) == 1
        assert len(vol) == 1

    def test_empty_input_yields_empty_output(self):
        assert app._agg_ohlc([], [], [], 2) == ([], [], [])

    def test_single_bar_yields_nothing(self):
        assert app._agg_ohlc([BAR_A], [TS_A], [VOL_A], 2) == ([], [], [])

    def test_tolerates_short_timestamp_and_volume_arrays(self):
        # Some upstream payloads omit volume; the fold must not raise.
        ohlc, ts, vol = app._agg_ohlc([BAR_A, BAR_B], [], [], 2)
        assert ohlc == [[10.0, 15.0, 8.0, 14.0]]
        assert ts == [0]
        assert vol == [0]


class TestIntradayTimeframes:
    def test_every_stock_timeframe_maps_to_a_range_interval_and_factor(self):
        for tf, (rng, interval, factor) in app.INTRADAY_TF["stock"].items():
            assert isinstance(rng, str) and rng, tf
            assert isinstance(interval, str) and interval, tf
            assert isinstance(factor, int) and factor >= 1, tf

    def test_every_crypto_timeframe_maps_to_a_granularity_and_factor(self):
        for tf, (gran, factor) in app.INTRADAY_TF["crypto"].items():
            assert isinstance(gran, int) and gran > 0, tf
            assert isinstance(factor, int) and factor >= 1, tf

    def test_stock_and_crypto_offer_the_same_timeframes(self):
        assert set(app.INTRADAY_TF["stock"]) == set(app.INTRADAY_TF["crypto"])

    def test_every_advertised_timeframe_is_actually_fetchable(self):
        # TIMEFRAMES drives the buttons; a name there with no fetch spec would
        # silently fall back to "wide" and show the wrong chart.
        for tf in app.TIMEFRAMES:
            assert tf in app.INTRADAY_TF["stock"], tf
            assert tf in app.INTRADAY_TF["crypto"], tf

    def test_the_requested_minute_and_period_charts_are_all_offered(self):
        for tf in ("1m", "5m", "10m", "15m", "30m", "1D", "1W"):
            assert tf in app.TIMEFRAMES, tf

    def test_intervals_a_venue_lacks_are_folded_from_the_next_one_down(self):
        # Yahoo has no 10m; Coinbase has no 10m, no 30m, and no weekly.
        assert app.INTRADAY_TF["stock"]["10m"][1:] == ("5m", 2)
        assert app.INTRADAY_TF["crypto"]["10m"] == (300, 2)
        assert app.INTRADAY_TF["crypto"]["30m"] == (900, 2)
        assert app.INTRADAY_TF["crypto"]["1W"] == (86400, 7)

    def test_natively_published_intervals_are_not_folded(self):
        for tf in ("1m", "5m", "15m", "30m", "1h", "1D", "1W"):
            assert app.INTRADAY_TF["stock"][tf][2] == 1, tf
        for tf in ("1m", "5m", "15m", "1h", "1D"):
            assert app.INTRADAY_TF["crypto"][tf][1] == 1, tf

    def test_no_stock_timeframe_asks_for_a_single_day(self):
        # A one-day range holds only the current session. At 09:32 ET that was
        # three candles, and on a weekend it is none — the chart looks broken
        # through no fault of the renderer.
        for tf, (rng, _interval, _factor) in app.INTRADAY_TF["stock"].items():
            assert rng != "1d", f"{tf} would be empty before the session fills"


def _yahoo_payload(count: int):
    """A Yahoo chart response carrying `count` clean bars."""
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [TS_A + i * 300 for i in range(count)],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0] * count,
                                "high": [12.0] * count,
                                "low": [9.0] * count,
                                "close": [11.0] * count,
                                "volume": [100] * count,
                            }
                        ]
                    },
                }
            ]
        }
    }


class TestFetchIntraday:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        app._cache.clear()
        yield
        app._cache.clear()

    def test_returns_parallel_ohlc_and_timestamp_arrays(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(6))

        out = app.fetch_intraday("stock", "AAPL", "5m")

        assert out["symbol"] == "AAPL"
        assert out["tf"] == "5m"
        assert len(out["ohlc"]) == 6
        # `ts` must line up index-for-index with `ohlc` or the chart misplots.
        assert len(out["ts"]) == len(out["ohlc"])
        assert len(out["volume"]) == len(out["ohlc"])
        assert out["last"] == out["ohlc"][-1][3]

    def test_ten_minute_timeframe_halves_the_bar_count(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(6))

        out = app.fetch_intraday("stock", "AAPL", "10m")

        assert out["tf"] == "10m"
        assert len(out["ohlc"]) == 3
        assert len(out["ts"]) == 3

    def test_unknown_timeframe_falls_back_to_wide(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(4))

        out = app.fetch_intraday("stock", "AAPL", "not-a-timeframe")

        assert out["tf"] == "wide"

    @pytest.mark.parametrize("asked,expected", [
        ("1D", "1D"), ("1d", "1D"), (" 1d ", "1D"),
        ("1W", "1W"), ("1w", "1W"),
        ("1M", "1m"), ("15M", "15m"),
    ])
    def test_timeframes_resolve_regardless_of_case(self, monkeypatch, asked, expected):
        # The route handler lowercases query params, which turned "1D" into
        # "1d" — not a key — so daily and weekly silently served a 15-minute
        # chart under a daily label.
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(8))

        out = app.fetch_intraday("stock", "AAPL", asked)

        assert out["tf"] == expected

    def test_daily_and_weekly_do_not_collapse_onto_the_same_request(self, monkeypatch):
        seen = []

        def spy(url, *a, **k):
            seen.append(url)
            return _yahoo_payload(8)

        monkeypatch.setattr(app, "_get_json", spy)
        app.fetch_intraday("stock", "AAPL", "1D")
        app.fetch_intraday("stock", "AAPL", "1W")

        assert len(seen) == 2
        assert "interval=1d" in seen[0], seen[0]
        assert "interval=1wk" in seen[1], seen[1]

    def test_a_long_range_is_trimmed_to_the_recent_tape(self, monkeypatch):
        # Five days of 1m bars is ~1,950 candles. Ship the recent slice.
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(1950))

        out = app.fetch_intraday("stock", "AAPL", "1m")

        assert len(out["ohlc"]) == app.MAX_INTRADAY_BARS
        # The arrays must stay aligned after trimming or the chart misplots.
        assert len(out["ts"]) == len(out["ohlc"])
        assert len(out["volume"]) == len(out["ohlc"])

    def test_trimming_keeps_the_newest_bars_not_the_oldest(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(1950))

        out = app.fetch_intraday("stock", "AAPL", "1m")

        # _yahoo_payload stamps bar i at TS_A + i*300; the last one must survive.
        assert out["ts"][-1] == TS_A + 1949 * 300

    def test_a_short_response_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(12))

        out = app.fetch_intraday("stock", "AAPL", "5m")

        assert len(out["ohlc"]) == 12

    def test_upstream_failure_degrades_to_empty_rather_than_raising(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("upstream down")

        monkeypatch.setattr(app, "_get_json", boom)

        out = app.fetch_intraday("stock", "AAPL", "5m")

        assert out["ohlc"] == []
        assert out["ts"] == []
        assert out["last"] is None

    def test_repeated_calls_do_not_grow_the_cache_without_bound(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(2))

        # Distinct symbols were the memory-growth vector before the cache
        # gained a ceiling.
        for i in range(app.MAX_CACHE_ENTRIES * 2):
            app.fetch_intraday("stock", f"SYM{i}"[:12], "5m")

        assert len(app._cache) <= app.MAX_CACHE_ENTRIES
