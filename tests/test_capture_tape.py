"""Long lesson tapes: years of daily bars, so one lesson can start the same plan
at a top, at a bottom and in a quiet year on a single chart.

The network is faked: what matters here is that pages are stitched into one
clean, gap-free, oldest-first tape in the shape the chart renders.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "classes"))

import capture_tape as ct  # noqa: E402
import lesson_compiler as lc  # noqa: E402

pytestmark = pytest.mark.unit

DAY = 86_400
NOW = 1_790_000_000
TODAY = NOW // DAY * DAY


def coinbase(missing=()):
    """A fake exchange: one candle a day, newest first, 300 a page like the real one."""
    calls = []

    def get_json(url):
        calls.append(url)
        q = dict(part.split("=") for part in url.split("?")[1].split("&"))
        start, end = ct._from_iso(q["start"]), ct._from_iso(q["end"])
        days = [t for t in range(start, end + 1, DAY) if t <= TODAY and t not in missing]
        assert len(days) <= ct.COINBASE_PAGE, "asked the exchange for more than one page"
        # Coinbase row: [time, low, high, open, close, volume]
        return [[t, 90.0, 110.0, 100.0, 105.0, 7.0] for t in reversed(days)]

    app = SimpleNamespace(_get_json=get_json, coinbase_product=lambda s: f"{s.upper()}-USD",
                          COINBASE_API="https://exchange.test", _px=lambda v: round(float(v), 2),
                          is_regular_bar=lambda t, off: True)
    return app, calls


def test_crypto_history_stitches_pages_into_one_oldest_first_tape():
    app, calls = coinbase()
    tape = ct.capture_history(app, "btc", "crypto", years=2, now=NOW, pause=0)
    assert len(calls) >= 3                                         # two years is more than one page
    assert tape["ts"] == sorted(tape["ts"]) and len(tape["ts"]) == 2 * 365
    assert all(b - a == DAY for a, b in zip(tape["ts"], tape["ts"][1:]))
    assert tape["ohlc"][0] == [100.0, 110.0, 90.0, 105.0]          # open, high, low, close
    assert (tape["symbol"], tape["kind"], tape["tf"]) == ("BTC", "crypto", "1D")
    lc.check_tape(tape)                                            # the compiler accepts it


def test_crypto_history_leaves_out_the_day_still_forming():
    app, _ = coinbase()
    tape = ct.capture_history(app, "btc", "crypto", years=1, now=NOW, pause=0)
    assert tape["ts"][-1] == TODAY - DAY


def test_a_hole_in_the_history_is_refused_not_frozen():
    # A missing day would silently shift every "buy every 30 bars" after it.
    app, _ = coinbase(missing={TODAY - 40 * DAY})
    with pytest.raises(SystemExit, match="gap"):
        ct.capture_history(app, "btc", "crypto", years=1, now=NOW, pause=0)


def test_stock_history_asks_for_the_years_and_skips_empty_bars():
    seen = []

    def get_json(url):
        seen.append(url)
        times = [TODAY - (40 - i) * DAY for i in range(40)]
        close = [100.0 + i for i in range(40)]
        close[5] = None                                            # a halted day comes back empty
        return {"chart": {"result": [{"timestamp": times, "meta": {"gmtoffset": -14400},
                                      "indicators": {"quote": [{"open": close, "high": close, "low": close,
                                                                "close": close, "volume": [1] * 40}]}}]}}

    app = SimpleNamespace(_get_json=get_json, _px=lambda v: round(float(v), 2),
                          is_regular_bar=lambda t, off: True)
    tape = ct.capture_history(app, "spy", "stock", years=5, now=NOW, pause=0)
    assert "range=5y" in seen[0] and "interval=1d" in seen[0]
    assert len(tape["ts"]) == 39 and tape["gmtoffset"] == -14400 and tape["symbol"] == "SPY"
    lc.check_tape(tape)


@pytest.mark.parametrize("years", [0, 11, True, 2.5, "5"])
def test_years_must_be_a_sensible_whole_number(years):
    app, _ = coinbase()
    with pytest.raises(SystemExit, match="years"):
        ct.capture_history(app, "btc", "crypto", years=years, now=NOW, pause=0)


def test_too_little_history_is_refused():
    app = SimpleNamespace(_get_json=lambda url: [], coinbase_product=lambda s: "BTC-USD",
                          COINBASE_API="https://exchange.test", _px=float, is_regular_bar=lambda t, off: True)
    with pytest.raises(SystemExit, match="bars"):
        ct.capture_history(app, "btc", "crypto", years=1, now=NOW, pause=0)


# ------------------------------------------------------------------ review regressions (09-30)
def test_a_crypto_history_that_stops_early_is_refused():
    # An empty newest page would freeze a tape that ends weeks ago and call it current.
    app, _ = coinbase(missing={TODAY - k * DAY for k in range(1, 20)})
    with pytest.raises(SystemExit, match="ends"):
        ct.capture_history(app, "btc", "crypto", years=1, now=NOW, pause=0)


def test_a_coin_younger_than_the_years_asked_for_is_refused():
    # A coin listed eight months ago would quietly become a shorter tape than the lesson was written for.
    app, _ = coinbase(missing={TODAY - k * DAY for k in range(250, 366)})
    with pytest.raises(SystemExit, match="starts"):
        ct.capture_history(app, "btc", "crypto", years=1, now=NOW, pause=0)


def stock_app(last_bar_ts):
    times = [last_bar_ts - (39 - i) * DAY for i in range(40)]
    close = [100.0 + i for i in range(40)]
    payload = {"chart": {"result": [{"timestamp": times, "meta": {"gmtoffset": -14400},
                                     "indicators": {"quote": [{"open": close, "high": close, "low": close,
                                                               "close": close, "volume": [1] * 40}]}}]}}
    return SimpleNamespace(_get_json=lambda url: payload, _px=lambda v: round(float(v), 2),
                           is_regular_bar=lambda t, off: True), times


def test_a_stock_history_leaves_out_todays_bar_because_it_may_still_be_forming():
    # Yahoo's last daily bar during market hours is a live tick, not a close.
    open_today = TODAY + 13 * 3600 + 30 * 60                      # 09:30 New York, as UTC seconds
    app, times = stock_app(open_today)
    tape = ct.capture_history(app, "spy", "stock", years=5, now=open_today + 3600, pause=0)
    assert tape["ts"][-1] == times[-2] and len(tape["ts"]) == 39


def test_a_stock_history_keeps_yesterdays_finished_bar():
    app, times = stock_app(TODAY - DAY + 13 * 3600 + 30 * 60)
    tape = ct.capture_history(app, "spy", "stock", years=5, now=TODAY + 10 * 3600, pause=0)
    assert tape["ts"][-1] == times[-1] and len(tape["ts"]) == 40
