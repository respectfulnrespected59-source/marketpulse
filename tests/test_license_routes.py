"""The /api/license/* routes through the real request handler.

Gumroad is replaced by the FakeGumroad from test_licensing, so the routes'
contract is pinned without touching the network: what they return, that the
key is never echoed back, that activation is rate limited, and that the
whole thing is simply off until plans and a secret are configured.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app
import grader
import licensing as lic
from test_licensing import KEY, PLANS, PRO_LIFE, SECRET, FakeGumroad

pytestmark = pytest.mark.unit


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def gumroad(monkeypatch):
    g = FakeGumroad(owner=PRO_LIFE)
    monkeypatch.setattr(app, "_LICENSE_PLANS", PLANS)
    monkeypatch.setattr(app, "_license_secret", lambda: SECRET)
    monkeypatch.setattr(app, "_LICENSE_POST", g.post)
    monkeypatch.setattr(app, "_LICENSE_CACHE", lic.StatusCache())
    monkeypatch.setattr(app, "_LICENSE_LIMITER", grader.GradeLimiter(per_client=3, window_s=3600, daily_cap=100))
    return g


def call(base, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_licensing_reports_off_when_nothing_is_configured(server, monkeypatch):
    monkeypatch.setattr(app, "_LICENSE_PLANS", {})
    status, body = call(server, "/api/license")
    assert status == 200 and json.loads(body)["enabled"] is False


def test_licensing_lists_plans_when_configured(server, gumroad):
    info = json.loads(call(server, "/api/license")[1])
    assert info["enabled"] is True
    assert {"tier": "proplus", "billing": "lifetime", "devices": 5, "accounts": 3} in info["plans"]


def test_activate_then_status_round_trip(server, gumroad):
    status, raw = call(server, "/api/license/activate", {"key": KEY, "device": "dev-1"})
    out = json.loads(raw)
    assert status == 200 and out["ok"] and out["tier"] == "pro"
    assert KEY not in raw  # the key is never echoed back
    st = json.loads(call(server, "/api/license/status",
                         {"key": KEY, "token": out["token"], "device": "dev-1"})[1])
    assert st["active"] is True and st["tier"] == "pro"
    assert gumroad.uses == 1  # the status check did not take a second seat


def test_refused_activation_is_a_403_with_a_reason(server, gumroad):
    gumroad.purchase["refunded"] = True
    status, raw = call(server, "/api/license/activate", {"key": KEY, "device": "dev-1"})
    assert status == 403 and "refunded" in json.loads(raw)["message"]


def test_one_key_cannot_be_hammered_from_many_spoofed_addresses(server, gumroad, monkeypatch):
    # Rotating CF-Connecting-IP dodges a per-client limit; the per-KEY limit holds.
    monkeypatch.setattr(app, "_LICENSE_LIMITER", grader.GradeLimiter(per_client=100, window_s=3600, daily_cap=10**9))
    codes = []
    for i in range(8):
        req = urllib.request.Request(server + "/api/license/activate", method="POST",
                                     data=json.dumps({"key": "SAME-KEY-0000-1111", "device": f"dev-{i}"}).encode(),
                                     headers={"Content-Type": "application/json", "CF-Connecting-IP": f"10.0.0.{i}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                codes.append(r.status)
        except urllib.error.HTTPError as exc:
            codes.append(exc.code)
    assert 429 in codes and codes.index(429) <= app.LICENSE_PER_KEY_PER_HOUR


def test_the_shared_limiter_has_no_exhaustible_daily_cap():
    # A global daily cap is the lever a spoofing attacker pulls to lock every buyer out.
    assert app._LICENSE_LIMITER._daily_cap >= 10**9


def test_activation_is_rate_limited(server, gumroad):
    codes = [call(server, "/api/license/activate", {"key": "WRONG-KEY-0000-%04d" % i, "device": "dev-1"})[0]
             for i in range(5)]
    assert codes[:3] == [403, 403, 403] and codes[3] == 429


def test_status_with_a_forged_token_is_inactive(server, gumroad):
    st = json.loads(call(server, "/api/license/status",
                         {"key": KEY, "token": "abc.def", "device": "dev-1"})[1])
    assert st["active"] is False


def test_non_string_fields_are_rejected(server, gumroad):
    status, _ = call(server, "/api/license/activate", {"key": ["x"], "device": "dev-1"})
    assert status == 400


def test_the_gate_reads_the_license_headers(gumroad):
    tok = lic.issue_token(SECRET, KEY, "dev-9", "pro", PRO_LIFE, lic.time.time())
    ok = app.license_entitlement({"X-MP-License-Key": KEY, "X-MP-License-Token": tok, "X-MP-Device": "dev-9"})
    assert ok.active and ok.tier == "pro"
    assert not app.license_entitlement({}).active


# ------------------------------------------------------------------ front end
import os  # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def _static(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


def test_the_app_sends_keys_in_the_body_never_the_url():
    js = _static("license.js")
    assert "?key=" not in js and "&key=" not in js and "license_key=" not in js


def test_the_license_is_never_part_of_a_backup():
    # Restoring mp_device + mp_license on another phone would clone this seat.
    home = _static("home.js")
    backup = home.split("const BACKUP_KEYS", 1)[1].split(";", 1)[0]
    assert "mp_license" not in backup and "mp_device" not in backup


def test_the_license_card_starts_hidden():
    assert 'id="licenseCard" hidden' in _static("index.html")


def test_server_text_is_never_inserted_as_html():
    assert "innerHTML" not in _static("license.js")


def test_the_pro_card_shows_only_when_pro_is_for_sale():
    # Licensing switched on for the Classes pass alone must not show a "MarketPulse Pro" key box
    # that no one can buy a key for.
    js = _static("license.js")
    init = js.split("async function init()", 1)[1]
    assert 'p.tier === "pro" || p.tier === "proplus"' in init
    assert init.index("if (!sellsPro && !l) return;") < init.index("card.hidden = false;")



def test_status_tells_the_app_when_gumroad_was_unreachable(server, gumroad):
    out = json.loads(call(server, "/api/license/activate", {"key": KEY, "device": "dev-1"})[1])
    app._LICENSE_CACHE = lic.StatusCache()               # cold cache, like right after a deploy
    gumroad.down = True
    st = json.loads(call(server, "/api/license/status", {"key": KEY, "token": out["token"], "device": "dev-1"})[1])
    assert st["active"] is False and st["unreachable"] is True


def test_the_app_keeps_the_license_when_the_check_could_not_reach_gumroad():
    js = _static("license.js")
    assert "unreachable" in js
