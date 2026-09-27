"""The /api/desk/* routes through the real request handler, attacked the way a
hostile web page would: wrong Host (DNS rebinding), cross-site Origin, fetch
metadata, a missing or wrong token, a CORS preflight, and the hosted site.
Alpaca is the FakeAlpaca from test_money_core, so nothing touches the network.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

import agent_config as config
import app
import broker
import credentials
import desk_api
import pilot
import store
from test_money_core import FakeAlpaca, LIVE_KEY, PAPER_KEY, SECRET

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    for var in ("MP_ALPACA_KEY_ID", "MP_ALPACA_SECRET", "MP_ALPACA_PAPER", "MP_OWNER_PILOT", "RENDER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(desk_api, "_GRANT", {"until": 0.0})
    yield


@pytest.fixture
def alpaca(monkeypatch):
    fake = FakeAlpaca(market_open=True)
    monkeypatch.setattr(broker, "_TRANSPORT", fake)
    return fake


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def raw(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = None if body is None else json.dumps(body)
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    text = resp.read().decode()
    conn.close()
    return resp.status, text


def good(port):
    """What the app's own page sends: same host, same origin, the token."""
    host = f"127.0.0.1:{port}"
    return {"Host": host, "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin",
            desk_api.TOKEN_HEADER: desk_api._TOKEN}


def call(port, method, path, body=None, **override):
    headers = {**good(port), **override}
    headers = {k: v for k, v in headers.items() if v is not None}
    if method == "GET":
        headers.pop("Origin", None)            # browsers omit Origin on same-origin GETs
    status, text = raw(port, method, path, body if method == "POST" else None, headers)
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def connect(mode="paper"):
    credentials.save(credentials.Credentials(PAPER_KEY if mode == "paper" else LIVE_KEY, SECRET, mode))


def add(pid, side="buy", symbol="BTC/USD", kind="crypto"):
    store.add_proposal({"id": pid, "ts": time.time(), "kind": kind, "symbol": symbol, "side": side,
                        "notional": "20" if side == "buy" else None, "ref_price": 100.0,
                        "status": "pending", "reasons": ["<img src=x onerror=alert(1)>"]})


# ------------------------------------------------------------------ who may ask
def test_the_page_gets_a_session_token(server):
    status, out = call(server, "GET", "/api/desk/session")
    assert status == 200 and out["token"] == desk_api._TOKEN


def test_dns_rebinding_host_is_refused_even_with_the_token(server):
    status, _ = call(server, "GET", "/api/desk/session", Host=f"evil.example:{server}")
    assert status == 403
    status, _ = call(server, "GET", "/api/desk/state", Host=f"evil.example:{server}")
    assert status == 403


def test_a_host_on_another_port_is_refused(server):
    status, _ = call(server, "GET", "/api/desk/session", Host="127.0.0.1:1")
    assert status == 403


def test_localhost_name_is_accepted(server):
    host = f"localhost:{server}"
    status, _ = call(server, "GET", "/api/desk/state", Host=host)
    assert status == 200


def test_cross_site_fetch_metadata_is_refused(server):
    status, _ = call(server, "GET", "/api/desk/session", **{"Sec-Fetch-Site": "cross-site"})
    assert status == 403
    status, _ = call(server, "POST", "/api/desk/halt", {}, **{"Sec-Fetch-Site": "same-site"})
    assert status == 403


def test_post_without_origin_or_from_another_origin_is_refused(server):
    assert call(server, "POST", "/api/desk/halt", {}, Origin=None)[0] == 403
    assert call(server, "POST", "/api/desk/halt", {}, Origin="https://evil.example")[0] == 403
    assert call(server, "POST", "/api/desk/halt", {}, Origin="null")[0] == 403
    assert store.is_halted() is False


def test_missing_or_wrong_token_is_refused(server):
    assert call(server, "GET", "/api/desk/state", **{desk_api.TOKEN_HEADER: None})[0] == 401
    assert call(server, "POST", "/api/desk/halt", {}, **{desk_api.TOKEN_HEADER: "guess"})[0] == 401
    assert store.is_halted() is False


def test_cors_preflight_is_never_granted(server):
    status, _ = raw(server, "OPTIONS", "/api/desk/approve",
                    headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
                             "Access-Control-Request-Headers": desk_api.TOKEN_HEADER})
    assert status >= 400


def test_the_hosted_site_has_no_desk_at_all(server, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert call(server, "GET", "/api/desk/session")[0] == 404
    assert call(server, "POST", "/api/desk/halt", {})[0] == 404
    assert store.is_halted() is False


def test_a_public_bind_has_no_desk():
    assert desk_api.enabled(("0.0.0.0", 8000)) is False
    assert desk_api.enabled(("127.0.0.1", 8000)) is True


# ------------------------------------------------------------------ keys
def test_keys_are_verified_saved_and_never_read_back(server, alpaca):
    status, out = call(server, "POST", "/api/desk/keys",
                       {"key_id": PAPER_KEY, "secret": SECRET, "mode": "paper"})
    assert status == 200 and out["connected"]["key_id_last4"] == PAPER_KEY[-4:]
    status, text = raw(server, "GET", "/api/desk/state", headers={
        k: v for k, v in good(server).items() if k != "Origin"})
    assert status == 200 and SECRET not in text and PAPER_KEY not in text


def test_paper_keys_offered_as_live_are_refused_and_not_saved(server, alpaca):
    status, out = call(server, "POST", "/api/desk/keys",
                       {"key_id": PAPER_KEY, "secret": SECRET, "mode": "live"})
    assert status == 400 and "LIVE" in out["message"]
    assert credentials.load() is None


def test_malformed_keys_are_refused(server, alpaca):
    assert call(server, "POST", "/api/desk/keys", {"key_id": "x", "secret": SECRET, "mode": "paper"})[0] == 400
    assert call(server, "POST", "/api/desk/keys", {"key_id": PAPER_KEY, "secret": 5, "mode": "paper"})[0] == 400
    assert credentials.load() is None


def test_disconnect_deletes_the_keys(server, alpaca):
    connect()
    assert call(server, "POST", "/api/desk/disconnect", {})[0] == 200
    assert credentials.load() is None


# ------------------------------------------------------------------ trading
def test_state_shows_the_account_caps_and_pending(server, alpaca):
    connect()
    add("p1")
    status, out = call(server, "GET", "/api/desk/state")
    assert status == 200
    assert out["mode"] == "paper" and out["account"]["equity"] == "1000"
    assert [p["id"] for p in out["pending"]] == ["p1"]
    assert out["live"]["permitted"] is False


def test_approve_through_the_desk_sends_one_paper_order(server, alpaca):
    connect()
    add("p1")
    status, out = call(server, "POST", "/api/desk/approve", {"id": "p1"})
    assert status == 200 and out["status"] == "submitted"
    status, out = call(server, "POST", "/api/desk/approve", {"id": "p1"})
    assert out["status"] == "submitted" and out["ok"] is False
    assert len(alpaca.orders) == 1


def test_live_approve_is_blocked_without_permission(server, alpaca):
    connect("live")
    add("p1")
    status, out = call(server, "POST", "/api/desk/approve", {"id": "p1"})
    assert out["status"] == "blocked" and alpaca.orders == []


def test_live_approve_works_during_the_owner_pilot_and_is_capped(server, alpaca, monkeypatch):
    monkeypatch.setenv("MP_OWNER_PILOT", "1")
    pilot.start()
    connect("live")
    add("p1")
    status, out = call(server, "POST", "/api/desk/approve", {"id": "p1"})
    assert out["status"] == "submitted" and alpaca.orders[0]["notional"] == "20"
    store.add_proposal({"id": "big", "ts": time.time(), "kind": "crypto", "symbol": "BTC/USD",
                        "side": "buy", "notional": "26", "ref_price": 100.0, "status": "pending"})
    status, out = call(server, "POST", "/api/desk/approve", {"id": "big"})
    assert out["status"] == "blocked" and len(alpaca.orders) == 1


def test_a_verified_pro_license_permits_live_and_arms_the_loop(server, alpaca, monkeypatch):
    class Ent:
        active, tier = True, "pro"
    monkeypatch.setattr(app, "license_entitlement", lambda headers: Ent())
    connect("live")
    add("p1")
    assert desk_api.loop_live_permitted() is False
    status, out = call(server, "POST", "/api/desk/approve", {"id": "p1"})
    assert out["status"] == "submitted"
    assert desk_api.loop_live_permitted() is True


def test_only_an_active_pro_tier_license_permits_live():
    class Ent:
        def __init__(self, active, tier):
            self.active, self.tier = active, tier
    assert desk_api.live_permission({}, lambda h: Ent(True, "free"))[0] is False
    assert desk_api.live_permission({}, lambda h: Ent(True, ""))[0] is False
    assert desk_api.live_permission({}, lambda h: Ent(False, "pro"))[0] is False
    assert desk_api.live_permission({}, lambda h: Ent(True, "proplus"))[0] is True


def test_a_crashing_license_check_means_not_permitted(monkeypatch):
    def boom(headers):
        raise RuntimeError("gumroad down")
    assert desk_api.live_permission({}, boom)[0] is False


def test_bad_ids_are_refused(server, alpaca):
    connect()
    assert call(server, "POST", "/api/desk/approve", {"id": "../../x"})[0] == 400
    assert call(server, "POST", "/api/desk/approve", {"id": 7})[0] == 400


def test_reject_halt_resume_and_auto_exits(server, alpaca):
    connect()
    add("p1")
    assert call(server, "POST", "/api/desk/reject", {"id": "p1"})[1]["status"] == "rejected"
    call(server, "POST", "/api/desk/halt", {"reason": "testing"})
    assert store.is_halted() is True
    add("p2")
    assert call(server, "POST", "/api/desk/approve", {"id": "p2"})[1]["status"] == "blocked"
    call(server, "POST", "/api/desk/resume", {})
    assert store.is_halted() is False
    assert call(server, "POST", "/api/desk/auto", {"on": "yes"})[0] == 400
    assert call(server, "POST", "/api/desk/auto", {"on": True})[1]["settings"] == {"auto_exits": True}


def test_an_internal_error_never_leaks_detail(server, alpaca, monkeypatch):
    connect()
    monkeypatch.setattr(desk_api.desk, "report", lambda days: 1 / 0)
    status, out = call(server, "GET", "/api/desk/state")
    assert status == 500 and "ZeroDivision" not in json.dumps(out)
