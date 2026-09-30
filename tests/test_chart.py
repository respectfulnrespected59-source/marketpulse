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

    def test_overlay_is_computed_on_the_same_bars_the_chart_draws(self, monkeypatch):
        # The bug this exists for: overlays were computed on daily bars (and a
        # weekly squeeze for stocks) no matter which timeframe was on screen,
        # with no tf in the cache key. A 1m chart carried daily EMA lines that
        # never moved when you switched timeframe.
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(120))

        chart = app.fetch_intraday("stock", "AAPL", "5m")
        overlay = app.chart_overlay("stock", "AAPL", "5m")

        assert overlay["tf"] == "5m"
        chart_stamps = set(chart["ts"])
        for period, pairs in overlay["emas"].items():
            assert pairs, period
            # Every EMA point must sit on a candle the chart actually plotted.
            for stamp, _value in pairs:
                assert stamp in chart_stamps, f"EMA{period} point off-chart"

    def test_each_timeframe_gets_its_own_overlay(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(120))

        five = app.chart_overlay("stock", "AAPL", "5m")
        daily = app.chart_overlay("stock", "AAPL", "1D")

        # Different timeframes must not share a cached overlay.
        assert five["tf"] == "5m"
        assert daily["tf"] == "1D"

    def test_ema_periods_are_configurable(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(120))

        overlay = app.chart_overlay("stock", "AAPL", "5m", ema_periods=(9, 20))

        assert overlay["periods"] == [9, 20]
        assert set(overlay["emas"]) == {"9", "20"}

    def test_ema_alignment_starts_at_the_right_bar(self, monkeypatch):
        # ema_series(closes, p) has len-p+1 values; value i belongs to bar p-1+i.
        # Off-by-one here shifts every line sideways against the candles.
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(60))

        chart = app.fetch_intraday("stock", "AAPL", "5m")
        overlay = app.chart_overlay("stock", "AAPL", "5m", ema_periods=(14,))

        first_stamp = overlay["emas"]["14"][0][0]
        assert first_stamp == chart["ts"][13]

    def test_squeeze_can_be_switched_off(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(120))

        on = app.chart_overlay("stock", "AAPL", "5m", want_squeeze=True)
        off = app.chart_overlay("stock", "AAPL", "5m", want_squeeze=False)

        assert off["squeeze"] is None
        assert on["squeeze"] is not None
        # And it names the grain it was measured on, rather than implying one.
        assert on["squeeze"]["grain"] == "5m"

    def test_overlay_survives_an_empty_chart(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("upstream down")

        monkeypatch.setattr(app, "_get_json", boom)

        overlay = app.chart_overlay("stock", "AAPL", "5m")

        assert overlay["squeeze"] is None
        assert all(pairs == [] for pairs in overlay["emas"].values())

    def test_repeated_calls_do_not_grow_the_cache_without_bound(self, monkeypatch):
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: _yahoo_payload(2))

        # Distinct symbols were the memory-growth vector before the cache
        # gained a ceiling.
        for i in range(app.MAX_CACHE_ENTRIES * 2):
            app.fetch_intraday("stock", f"SYM{i}"[:12], "5m")

        assert len(app._cache) <= app.MAX_CACHE_ENTRIES


# ------------------------------------------- extended hours (pre / post)
#
# Overnight structure sets up the open, so the chart should be able to SHOW it.
# But a 4am bar with two hundred shares traded must never move an indicator:
# thin tape reads as compression to a squeeze and as exhaustion to RSI, and
# both are artefacts of nobody trading rather than of anything happening.
#
# So the split is deliberate: draw the extended bars, compute on the regular
# ones. Off by default, because turning it on changes every reading.

class TestExtendedHours:
    def test_a_regular_hours_bar_is_recognised(self):
        # 09:30 exchange-local, the first regular bar of the session
        assert app.is_regular_bar(1786973400, -14400) is True

    def test_a_premarket_bar_is_not_regular(self):
        # 04:00 exchange-local
        assert app.is_regular_bar(1786953600, -14400) is False

    def test_an_afterhours_bar_is_not_regular(self):
        # 16:00 exchange-local — the close is the END of the window, exclusive
        assert app.is_regular_bar(1786996800, -14400) is False

    def test_the_last_regular_bar_still_counts(self):
        # 15:55, the final regular five-minute bar
        assert app.is_regular_bar(1786996800 - 300, -14400) is True

    def test_it_uses_the_offset_it_is_given_not_the_server_clock(self):
        # Same instant, different exchange offset -> different verdict. The
        # offset comes from the response so DST is never guessed at.
        ts = 1786973400
        assert app.is_regular_bar(ts, -14400) is True
        assert app.is_regular_bar(ts, -14400 - 3600 * 6) is False

    def test_a_missing_offset_does_not_crash(self):
        assert app.is_regular_bar(1786973400, None) in (True, False)


class TestOverlayIgnoresExtendedBars:
    def _tape(self):
        """Two sessions of 5m bars with pre/post attached, as the client sees."""
        base = 1786953600            # 04:00 ET
        ts, ohlc = [], []
        for i in range(260):
            t = base + i * 300
            ts.append(t)
            px = 100.0 + (i % 7) * 0.5
            ohlc.append([px, px + 0.4, px - 0.4, px])
        return ts, ohlc

    def test_indicators_are_computed_on_regular_bars_only(self, monkeypatch):
        ts, ohlc = self._tape()
        payload = {"symbol": "TSLA", "kind": "stock", "tf": "5m", "ohlc": ohlc,
                   "ts": ts, "volume": [0] * len(ts), "gmtoffset": -14400,
                   "regular": [app.is_regular_bar(t, -14400) for t in ts]}
        monkeypatch.setattr(app, "fetch_intraday", lambda *a, **k: payload)
        # prepost=True is the mode the filter exists for: extended bars are
        # DRAWN, and the indicators must still ignore them.
        out = app.chart_overlay("stock", "TSLA", "5m", prepost=True)

        reg_ts = {t for t, r in zip(ts, payload["regular"]) if r}
        sq = out.get("squeeze_series") or {}
        for pair in (sq.get("bb_upper") or []):
            assert pair[0] in reg_ts, "an indicator value landed on an extended-hours bar"
        for pair in (out.get("emas", {}).get("14") or []):
            assert pair[0] in reg_ts

    def test_the_payload_still_reports_which_bars_were_extended(self, monkeypatch):
        ts, ohlc = self._tape()
        payload = {"symbol": "TSLA", "kind": "stock", "tf": "5m", "ohlc": ohlc,
                   "ts": ts, "volume": [0] * len(ts), "gmtoffset": -14400,
                   "regular": [app.is_regular_bar(t, -14400) for t in ts]}
        monkeypatch.setattr(app, "fetch_intraday", lambda *a, **k: payload)
        # The chart needs the flags to style overnight candles differently.
        assert any(payload["regular"]) and not all(payload["regular"])


# ------------------------------------------------------------------ the monthly chart (owner 2026-09-30)
class TestMonthlyChart:
    """A monthly chart for the Para-Sail monthly low. Its key is "1Mo": the route lowercases every query
    parameter, so a "1M" key would collide with "1m" and serve a one-minute tape under a monthly label."""

    def test_monthly_has_its_own_key_and_1m_still_means_one_minute(self):
        for asked in ("1Mo", "1mo", "1MO", " 1mo "):
            assert app.canonical_tf(asked) == "1Mo", asked
        assert app.canonical_tf("1M") == "1m"
        assert "1Mo" in app.TIMEFRAMES and "1Mo" in app.SLOW_TF

    def test_stock_monthly_is_yahoos_own_monthly_bars_over_ten_years(self, monkeypatch):
        import datetime as dt
        seen = []
        payload = _yahoo_payload(24)
        # real monthly bars sit a month apart (the shared helper spaces bars 5 minutes apart, which the
        # monthly fold would rightly merge into one month)
        payload["chart"]["result"][0]["timestamp"] = [
            int(dt.datetime(2024 + m // 12, m % 12 + 1, 1, 4, tzinfo=dt.timezone.utc).timestamp()) for m in range(24)]

        def spy(url, *a, **k):
            seen.append(url)
            return payload

        monkeypatch.setattr(app, "_get_json", spy)
        out = app.fetch_intraday("stock", "AAPL", "1Mo")
        assert out["tf"] == "1Mo" and len(out["ohlc"]) == 24
        assert "interval=1mo" in seen[0] and "range=10y" in seen[0], seen[0]

    def test_crypto_monthly_pages_five_years_of_days_and_folds_them_by_calendar_month(self, monkeypatch):
        import datetime as dt
        day = 86_400
        now = int(app.time.time())
        pages, days = [], {}

        def fake(url, *a, **k):
            # /candles?granularity=86400&start=...&end=... -> every day in the window, newest first
            q = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
            start = int(dt.datetime.strptime(q["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp())
            end = int(dt.datetime.strptime(q["end"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp())
            pages.append((start, end))
            rows = []
            for t in range(start, end + 1, day):
                i = t // day
                o, c = 100 + i % 50, 100 + (i * 7) % 50
                row = [t, min(o, c) - 1.0, max(o, c) + 1.0, float(o), float(c), 2.0]  # [time, low, high, open, close, vol]
                days[t] = row
                rows.append(row)
            return list(reversed(rows))

        monkeypatch.setattr(app, "_get_json", fake)
        monkeypatch.setattr(app, "coinbase_product", lambda s: "BTC-USD")
        monkeypatch.setattr(app, "_coinbase_last_trade", lambda p: None)
        monkeypatch.setattr(app, "COINBASE_PAGE_PAUSE_S", 0)
        out = app.fetch_intraday("crypto", "bitcoin", "1Mo")

        assert out["tf"] == "1Mo"
        assert len(pages) >= 6                                      # ~5 years at 300 days a page
        assert min(s for s, _ in pages) <= now - (5 * 365 - 2) * day
        # the expected fold, computed from the days the fake handed back
        months = {}
        for t in sorted(days):
            d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
            months.setdefault((d.year, d.month), []).append(days[t])
        want = [[g[0][3], max(r[2] for r in g), min(r[1] for r in g), g[-1][4]] for g in months.values()]
        assert out["ohlc"] == [[app._px(v) for v in bar] for bar in want]
        assert out["ts"] == [g[0][0] for g in months.values()]
        assert out["volume"] == [round(sum(r[5] for r in g), 2) for g in months.values()]
        this_month = dt.datetime.fromtimestamp(now, dt.timezone.utc)
        last = dt.datetime.fromtimestamp(out["ts"][-1], dt.timezone.utc)
        assert (last.year, last.month) == (this_month.year, this_month.month)   # the forming month is kept

    def test_yahoos_extra_today_bar_is_folded_into_its_month(self, monkeypatch):
        # Seen on the real TSLA monthly chart (09-30): Yahoo ends September's bar at the prior close and
        # appends TODAY as its own bar, so the last "monthly" candle was just 9/30's day.
        ts = [1782878400, 1785556800, 1788235200, 1790798400]      # Jul 1, Aug 1, Sep 1 04:00Z; Sep 30 20:00Z
        rows = [(421.46, 432.86, 297.38, 311.21), (310.96, 368.92, 310.43, 367.95),
                (360.90, 386.83, 349.92, 352.84), (351.79, 355.22, 345.88, 354.81)]
        payload = {"chart": {"result": [{"timestamp": ts, "meta": {"gmtoffset": -14400},
                                         "indicators": {"quote": [{
                                             "open": [r[0] for r in rows], "high": [r[1] for r in rows],
                                             "low": [r[2] for r in rows], "close": [r[3] for r in rows],
                                             "volume": [100, 200, 300, 40]}]}}]}}
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: payload)
        out = app.fetch_intraday("stock", "TSLA", "1Mo")
        assert out["ts"] == ts[:3]
        assert out["ohlc"][-1] == [app._px(360.90), app._px(386.83), app._px(345.88), app._px(354.81)]
        assert out["volume"][-1] == 340
        assert out["last"] == app._px(354.81)

    def test_monthly_caches_long(self):
        assert app._intraday_ttl("crypto", "1Mo") >= 1800
        assert app._intraday_ttl("stock", "1Mo") >= 1800


class TestChartButtonsMatchTheServer:
    """static/chart.js keeps its own timeframe lists (buttons, labels, grain, poll pace, default zoom). A
    timeframe the server has but one of those lists lacks draws an unlabelled or never-refreshing button."""

    @staticmethod
    def _keys(js, name):
        import re
        block = re.search(rf"const {name} = \{{(.*?)\}};", js, re.S).group(1)
        return set(re.findall(r'"([0-9]+[A-Za-z]+)":', block))

    def test_every_list_in_chart_js_covers_every_server_timeframe(self):
        import os
        import re
        js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "chart.js"),
                  encoding="utf-8").read()
        order = re.findall(r'"([^"]+)"', re.search(r"const TF_ORDER = \[(.*?)\];", js, re.S).group(1))
        assert order == list(app.TIMEFRAMES)
        for name in ("TF_LABELS", "TF_GRAIN", "TF_POLL_MS", "DEFAULT_VISIBLE"):
            assert set(app.TIMEFRAMES) <= self._keys(js, name), name
