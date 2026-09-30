"""GET /api/parasail through the real request handler: the Para-Sail strategy run on a symbol's history.

Pinned: the route runs the SAME engine (parasail.py) with the owner's rules, BTC is held and never
para-sailed unless ?hold=0 says otherwise, the zone word matches the numbers, the route is locked with
the DCA wizard, and a failure upstream never leaks how the server is wired.
"""
import calendar
import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app
import parasail
from safety import BoundedCache

pytestmark = pytest.mark.unit

CLOSES = [100.0] * 10 + [95.0] * 10 + [140.0] * 10 + [150.0] * 10 + [90.0] * 10 + [100.0] * 10
DATES = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(len(CLOSES))]


def ts_of(dates):
    return [calendar.timegm(dt.date.fromisoformat(d).timetuple()) for d in dates]


@pytest.fixture
def history(monkeypatch):
    """Fake the symbol's daily history; record what was asked for."""
    asked = []
    box = {"dates": DATES, "closes": CLOSES}

    def fake(kind, symbol):
        asked.append((kind, symbol))
        return list(box["dates"]), list(box["closes"])

    monkeypatch.setattr(app, "fetch_history", fake)
    monkeypatch.setattr(app, "_cache", BoundedCache(64))
    box["asked"] = asked
    return box


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(base, query):
    try:
        with urllib.request.urlopen(f"{base}/api/parasail?{query}", timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_the_route_runs_the_owners_rules_through_the_same_engine(server, history):
    status, out = get(server, "symbol=ethereum&kind=crypto")
    assert status == 200 and history["asked"] == [("crypto", "ethereum")]
    ref = parasail.simulate(ts_of(DATES), CLOSES, "crypto", parasail.Rules())
    assert out["hold"] is False
    assert (out["n"], out["n_sails"]) == (ref["n"], ref["n_sails"]) and ref["n_sails"] >= 1
    assert out["profit"] == pytest.approx(ref["profit"]) and out["roi"] == pytest.approx(ref["roi"])
    assert out["hold_roi"] == pytest.approx(ref["hold_roi"])
    assert [b["date"] for b in out["buys"]] == [DATES[b["bar"]] for b in ref["buys"]]
    assert [s["date"] for s in out["sails"]] == [DATES[s["bar"]] for s in ref["sails"]]
    assert out["rules"] == {"low_days": 30, "zone_pct": 8.0, "gap_days": 7, "fill": 100.0, "cap": 2000.0,
                            "sail_pct": 40.0, "sell_pct": 50.0}


@pytest.mark.parametrize("symbol", ["bitcoin", "BTC", "btc"])
def test_btc_is_held_never_para_sailed(server, history, symbol):
    status, out = get(server, f"symbol={symbol}&kind=crypto")
    assert status == 200
    assert out["hold"] is True and out["sails"] == [] and out["n_sails"] == 0
    assert out["profit"] == pytest.approx(out["hold_profit"])


def test_hold_can_be_switched_off_or_on_by_the_caller(server, history):
    _, btc = get(server, "symbol=bitcoin&kind=crypto&hold=0")
    _, eth = get(server, "symbol=ethereum&kind=crypto&hold=1")
    assert btc["hold"] is False and btc["n_sails"] >= 1
    assert eth["hold"] is True and eth["sails"] == []


def test_the_zone_word_matches_the_numbers(server, history):
    _, out = get(server, "symbol=ethereum&kind=crypto")
    z = out["zone"]
    # last 30 days: the 90s and the 100s -> low 90, top 97.2; the last close is 100 -> above
    assert (z["low"], z["top"], z["close"], z["where"]) == (90.0, pytest.approx(97.2), 100.0, "above")
    assert z["gap_pct"] == pytest.approx((100 / 97.2 - 1) * 100)
    history["closes"] = CLOSES[:-10] + [96.0] * 10
    _, inside = get(server, "symbol=solana&kind=crypto")
    assert inside["zone"]["where"] == "inside"


def test_too_little_history_says_so(server, history):
    history["dates"], history["closes"] = DATES[:10], CLOSES[:10]
    status, out = get(server, "symbol=ethereum&kind=crypto")
    assert status == 200 and out["error"] == "not enough history"


def test_locked_with_the_dca_wizard(server, history, monkeypatch):
    monkeypatch.setattr(app, "_enabled", lambda feature: False)
    status, out = get(server, "symbol=ethereum&kind=crypto")
    assert status == 402 and out["locked"] is True and history["asked"] == []


def test_a_bad_symbol_is_a_400(server, history):
    status, _ = get(server, "symbol=&kind=crypto")
    assert status == 400 and history["asked"] == []


def test_an_upstream_failure_never_leaks_the_wiring(server, monkeypatch):
    def boom(kind, symbol):
        raise RuntimeError("GET http://internal-host:9999/secret-path failed")

    monkeypatch.setattr(app, "fetch_history", boom)
    monkeypatch.setattr(app, "_cache", BoundedCache(64))
    status, out = get(server, "symbol=ethereum&kind=crypto")
    assert status == 502 and "secret-path" not in json.dumps(out)
