"""The Market Map and the landing page's live chart.

Server side: every market row carries `dollar_vol`, the figure the map sizes its
tiles by, taken from data already fetched (no extra upstream call) and left
empty rather than invented when the source doesn't give one.

Page side: the landing loads the SAME pinned chart engine as the app (checked by
the browser with SRI), the shared theme before the hero chart, the map on both
pages, and the service worker can install all of it. Behaviour is verified in a
real browser; this file keeps the wiring honest.
"""

import base64
import hashlib
import os
import re

import pytest

import app

pytestmark = pytest.mark.unit

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
VENDOR_JS = "vendor/lightweight-charts.standalone.production.js"


def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


def _daily(closes, volumes, meta=None):
    return {"chart": {"result": [{
        "meta": meta or {},
        "timestamp": list(range(len(closes))),
        "indicators": {"quote": [{"close": closes, "volume": volumes}]},
    }]}}


@pytest.fixture
def offline(monkeypatch):
    # Only the daily chart call matters here; the side lookups are not under test.
    monkeypatch.setattr(app, "_weekly_squeeze", lambda symbol: None)
    monkeypatch.setattr(app, "_decision_guides", lambda symbol, closes: None)
    return monkeypatch


# ------------------------------------------------------------------ dollar volume
class TestDollars:
    @pytest.mark.parametrize("value,expected", [
        (1234.4, 1234), (1e10, 10_000_000_000), ("2500", 2500),
    ])
    def test_positive_amounts_become_whole_dollars(self, value, expected):
        assert app._dollars(value) == expected

    @pytest.mark.parametrize("value", [None, "", "abc", 0, -5, float("inf"), float("nan")])
    def test_anything_unusable_stays_missing(self, value):
        assert app._dollars(value) is None


class TestStockRows:
    def test_dollar_volume_is_price_times_the_sessions_shares(self, offline):
        offline.setattr(app, "_get_json", lambda *a, **k: _daily(
            [100.0, 110.0], [5, 7], meta={"regularMarketVolume": 2_000_000}))
        row = app.fetch_one_stock("ZZTEST")
        assert row["dollar_vol"] == 110 * 2_000_000

    def test_falls_back_to_the_last_bars_volume(self, offline):
        offline.setattr(app, "_get_json", lambda *a, **k: _daily([100.0, 110.0], [5, 3_000]))
        assert app.fetch_one_stock("ZZTEST")["dollar_vol"] == 110 * 3_000

    def test_no_volume_anywhere_means_no_number(self, offline):
        offline.setattr(app, "_get_json", lambda *a, **k: _daily([100.0, 110.0], [None, None]))
        row = app.fetch_one_stock("ZZTEST")
        assert row["price"] == 110 and row["dollar_vol"] is None


class TestCryptoRows:
    def test_coingecko_volume_is_already_dollars(self, monkeypatch):
        coin = {"id": "zz-coin", "symbol": "zz", "name": "ZZ Coin", "current_price": 2.5,
                "price_change_percentage_24h": 1.234, "total_volume": 987654321.7,
                "sparkline_in_7d": {"price": [1.0, 2.0, 2.5]}}
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: [coin])
        row = app._crypto_from_coingecko(["zz-coin"])[0]
        assert row["dollar_vol"] == 987654322

    def test_missing_coingecko_volume_stays_missing(self, monkeypatch):
        coin = {"id": "zz-coin", "symbol": "zz", "name": "ZZ", "current_price": 2.5,
                "sparkline_in_7d": {"price": [1.0, 2.5]}}
        monkeypatch.setattr(app, "_get_json", lambda *a, **k: [coin])
        assert app._crypto_from_coingecko(["zz-coin"])[0]["dollar_vol"] is None


# ------------------------------------------------------------------ landing wiring
def _scripts(html):
    return re.findall(r'<script[^>]*\ssrc="([^"]+)"', html)


def test_landing_loads_the_pinned_engine_with_sri():
    with open(os.path.join(STATIC, VENDOR_JS), "rb") as fh:
        digest = base64.b64encode(hashlib.sha384(fh.read()).digest()).decode()
    tag = re.search(r'<script defer src="/' + re.escape(VENDOR_JS) + r'"\s+integrity="([^"]+)"',
                    _read("landing.html"))
    assert tag and tag.group(1) == f"sha384-{digest}"


def test_landing_loads_the_theme_before_the_hero_chart():
    order = [s.lstrip("/") for s in _scripts(_read("landing.html"))]
    assert order.index(VENDOR_JS) < order.index("chart-theme.js") < order.index("landing/hero-chart.js")
    assert "market-map.js" in order


def test_both_pages_load_the_market_map():
    for page in ("landing.html", "index.html"):
        html = _read(page)
        assert re.search(r'href="/?market-map\.css"', html), page
        assert re.search(r'src="/?market-map\.js"', html), page


def test_the_shell_can_install_everything_the_landing_loads():
    block = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\];", _read("sw.js"), re.S).group(1)
    shell = set(re.findall(r'"([^"]+)"', block))
    html = _read("landing.html")
    refs = _scripts(html) + re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    for ref in refs:
        assert "/" + ref.lstrip("/") in shell, ref


def test_the_hero_chart_leaves_the_mouse_wheel_to_the_page():
    # A landing chart that zooms when you try to scroll past it is a trap.
    src = _read("landing/hero-chart.js")
    assert re.search(r"handleScroll\s*=\s*\{\s*mouseWheel:\s*false", src)
    assert re.search(r"handleScale\s*=\s*\{\s*mouseWheel:\s*false", src)


def test_the_map_escapes_what_it_prints():
    # Names and symbols come from third-party feeds and land in innerHTML.
    src = _read("market-map.js")
    for field in ("r.symbol", "r.name", "sig"):
        for m in re.finditer(r"\+\s*" + re.escape(field) + r"\s*\+", src):
            raise AssertionError(f"unescaped {field} at offset {m.start()}")
    assert "function esc(" in src


# ------------------------------------------------------------------ live cadence
class TestIntradayFreshness:
    def test_coins_refresh_every_few_seconds(self):
        # What makes the landing chart visibly move; one fetch serves every viewer.
        assert app._intraday_ttl("crypto", "5m") == app.CRYPTO_LIVE_TTL == 5

    def test_stocks_keep_yahoos_pace(self):
        assert app._intraday_ttl("stock", "5m") == app.QUOTE_TTL
        assert app._intraday_ttl("stock", "1m") == 20

    @pytest.mark.parametrize("kind", ["stock", "crypto"])
    @pytest.mark.parametrize("tf", ["1D", "1W"])
    def test_daily_and_weekly_bars_stay_cached(self, kind, tf):
        assert app._intraday_ttl(kind, tf) == 300


def test_the_hero_never_polls_faster_than_the_server_refreshes():
    # Polling under the cache TTL only re-downloads the same candle.
    src = _read("landing/hero-chart.js")
    m = re.search(r"POLL_MS\s*=\s*\{\s*crypto:\s*(\d+),\s*stock:\s*(\d+)\s*\}", src)
    assert m, "POLL_MS not found"
    assert int(m.group(1)) >= app._intraday_ttl("crypto", "5m") * 1000
    assert int(m.group(2)) >= app._intraday_ttl("stock", "5m") * 1000


def test_the_hero_clock_rolls_every_second():
    assert re.search(r"CLOCK_MS\s*=\s*1000\b", _read("landing/hero-chart.js"))
    assert 'id="heroClock"' in _read("landing.html")


# ------------------------------------------------------------------ live trade -> forming candle
class TestApplyLiveTrade:
    BARS = [[10.0, 12.0, 9.0, 11.0], [11.0, 11.5, 10.5, 11.2]]
    TS = [1_000_000, 1_000_300]
    VOL = [5.0, 3.0]

    def test_a_trade_inside_the_bar_moves_its_close_and_stretches_the_range(self):
        ohlc, ts, vol = app._apply_live_trade(self.BARS, self.TS, self.VOL, 12.4, 300, 1_000_450)
        assert ohlc[-1] == [11.0, 12.4, 10.5, 12.4]
        assert ts == self.TS and vol == self.VOL and len(ohlc) == 2

    def test_a_trade_after_the_bar_opens_the_next_bucket(self):
        ohlc, ts, vol = app._apply_live_trade(self.BARS, self.TS, self.VOL, 10.9, 300, 1_000_300 + 650)
        assert ohlc[-1] == [10.9, 10.9, 10.9, 10.9]
        assert ts[-1] == 1_000_300 + 600 and vol[-1] == 0.0 and len(ohlc) == 3

    @pytest.mark.parametrize("price,now", [(None, 1_000_450), (12.0, 999_000)])
    def test_no_price_or_a_clock_behind_the_tape_changes_nothing(self, price, now):
        out = app._apply_live_trade(self.BARS, self.TS, self.VOL, price, 300, now)
        assert out == (self.BARS, self.TS, self.VOL)

    def test_the_inputs_are_never_mutated(self):
        bars = [list(b) for b in self.BARS]
        app._apply_live_trade(bars, list(self.TS), list(self.VOL), 99.0, 300, 1_000_450)
        assert bars == self.BARS


class TestCryptoTapeIsLive:
    @pytest.fixture(autouse=True)
    def fresh(self, monkeypatch):
        app._cache.clear()
        yield
        app._cache.clear()

    def _fake(self, now_bucket, ticker):
        candles = [[now_bucket, 99.0, 101.0, 100.0, 100.5, 7.0],
                   [now_bucket - 300, 98.0, 100.0, 99.0, 99.5, 4.0]]   # newest-first, like Coinbase
        def get(url, **kw):
            return {"price": str(ticker)} if url.endswith("/ticker") else candles
        return get

    def test_the_forming_candle_carries_the_latest_trade(self, monkeypatch):
        bucket = int(app.time.time()) // 300 * 300
        monkeypatch.setattr(app, "_get_json", self._fake(bucket, 103.25))
        d = app.fetch_intraday("crypto", "btc", "5m")
        assert d["ohlc"][-1] == [100.0, 103.25, 99.0, 103.25] and d["last"] == 103.25

    def test_a_folded_timeframe_is_left_alone(self, monkeypatch):
        bucket = int(app.time.time()) // 300 * 300
        monkeypatch.setattr(app, "_get_json", self._fake(bucket, 103.25))
        d = app.fetch_intraday("crypto", "btc", "10m")
        assert 103.25 not in [c for bar in d["ohlc"] for c in bar]


def test_one_ticker_call_serves_every_timeframe(monkeypatch):
    app._cache.clear()
    calls = []
    def get(url, **kw):
        calls.append(url)
        return {"price": "101.5"}
    monkeypatch.setattr(app, "_get_json", get)
    assert app._coinbase_last_trade("ZZ-USD") == 101.5
    assert app._coinbase_last_trade("ZZ-USD") == 101.5
    assert len(calls) == 1
    app._cache.clear()
