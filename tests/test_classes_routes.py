"""The Classes paywall: /api/classes/* through the real request handler.

Lesson content is the product, so the server — not the UI — decides who gets
it. Pinned here: the catalogue is public but carries no lesson content, a free
lesson needs no key, a paid lesson needs an ACTIVE classes or Pro+ license on
this device (plain Pro is not enough, a Classes key never unlocks Pro), every
failure is closed, and the compiled files can't be fetched around the gate.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app
import class_catalog as classes
import desk_api
import grader
import licensing as lic
from test_licensing import KEY, SECRET, FakeGumroad

pytestmark = pytest.mark.unit

CLASSES_M, PRO_M, PLUS_M = "pid-classes-m", "pid-pro-m2", "pid-plus-m2"
PLANS = lic.parse_plans(json.dumps({
    CLASSES_M: {"tier": "classes", "billing": "monthly"},
    PRO_M: {"tier": "pro", "billing": "monthly"},
    PLUS_M: {"tier": "proplus", "billing": "monthly"},
}))
AUDIO = b"ID3fake-mp3-bytes"


def build_catalog(root):
    """Two lessons in the compiled shape: dca-01 free, dca-02 paid."""
    (root / "audio").mkdir(parents=True)
    for name in ("aaaaaaaaaaaa.mp3", "bbbbbbbbbbbb.mp3", "cccccccccccc.mp3"):
        (root / "audio" / name).write_bytes(AUDIO)
    for lid, audio in (("dca-01", ["aaaaaaaaaaaa.mp3"]), ("dca-02", ["bbbbbbbbbbbb.mp3", "cccccccccccc.mp3"])):
        (root / f"{lid}.json").write_text(json.dumps(
            {"id": lid, "steps": [{"who": "T", "say": f"step of {lid}", "audio": a} for a in audio]}))
    (root / "catalog.json").write_text(json.dumps({"classes": [{
        "id": "dca", "title": "DCA", "tagline": "Stop timing the market", "lessons": [
            {"id": "dca-01", "title": "Same dollars", "free": True, "file": "dca-01.json",
             "audio": ["aaaaaaaaaaaa.mp3"]},
            {"id": "dca-02", "title": "Lump sum vs DCA", "free": False, "file": "dca-02.json",
             "audio": ["bbbbbbbbbbbb.mp3", "cccccccccccc.mp3"]},
        ]}]}))


@pytest.fixture
def server(tmp_path, monkeypatch):
    build_catalog(tmp_path)
    monkeypatch.setattr(app, "_CLASSES", classes.load_manifest(tmp_path))
    monkeypatch.setattr(app, "_LICENSE_PLANS", PLANS)
    monkeypatch.setattr(app, "_license_secret", lambda: SECRET)
    monkeypatch.setattr(app, "_LICENSE_CACHE", lic.StatusCache())
    monkeypatch.setattr(app, "_CLASSES_LIMITER", grader.GradeLimiter(per_client=1000, window_s=3600,
                                                                      daily_cap=10**9))
    monkeypatch.setattr(app, "_CLASSES_KEY_LIMITER", grader.GradeLimiter(per_client=1000, window_s=3600,
                                                                          daily_cap=10**9))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def owner(monkeypatch, product, **purchase):
    g = FakeGumroad(owner=product, purchase_fields=purchase or None)
    monkeypatch.setattr(app, "_LICENSE_POST", g.post)
    return g


def headers_for(product, tier, device="dev-1"):
    tok = lic.issue_token(SECRET, KEY, device, tier, product, lic.time.time())
    return {"X-MP-License-Key": KEY, "X-MP-License-Token": tok, "X-MP-Device": device}


def get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


# ------------------------------------------------------------------ catalogue
def test_catalogue_is_public_and_carries_no_lesson_content(server):
    status, raw, _ = get(server, "/api/classes")
    out = json.loads(raw)
    assert status == 200
    lessons = out["classes"][0]["lessons"]
    assert [(l["id"], l["free"], l["steps"]) for l in lessons] == [("dca-01", True, 1), ("dca-02", False, 2)]
    assert b"step of" not in raw and b".mp3" not in raw
    assert out["access"] == {"entitled": False, "tier": None}


def test_catalogue_reports_access_for_an_entitled_device(server, monkeypatch):
    owner(monkeypatch, CLASSES_M)
    out = json.loads(get(server, "/api/classes", headers_for(CLASSES_M, "classes"))[1])
    assert out["access"] == {"entitled": True, "tier": "classes"}


# ------------------------------------------------------------------ lessons
def test_free_lesson_needs_no_key(server):
    status, raw, _ = get(server, "/api/classes/lesson?id=dca-01")
    assert status == 200 and json.loads(raw)["id"] == "dca-01"


def test_paid_lesson_without_a_key_is_402_and_says_how_to_unlock(server):
    status, raw, _ = get(server, "/api/classes/lesson?id=dca-02")
    out = json.loads(raw)
    assert status == 402 and out["locked"] is True and "upgrade" in out
    assert b"step of" not in raw


@pytest.mark.parametrize("product,tier,code", [
    (CLASSES_M, "classes", 200),   # the $19 pass
    (PLUS_M, "proplus", 200),      # Pro+ includes classes
    (PRO_M, "pro", 402),           # plain Pro does not
])
def test_paid_lesson_follows_the_tier(server, monkeypatch, product, tier, code):
    owner(monkeypatch, product)
    assert get(server, "/api/classes/lesson?id=dca-02", headers_for(product, tier))[0] == code


def test_forged_token_is_refused(server, monkeypatch):
    owner(monkeypatch, CLASSES_M)
    h = {"X-MP-License-Key": KEY, "X-MP-License-Token": "abc.def", "X-MP-Device": "dev-1"}
    assert get(server, "/api/classes/lesson?id=dca-02", h)[0] == 402


def test_token_for_another_device_is_refused(server, monkeypatch):
    owner(monkeypatch, CLASSES_M)
    h = headers_for(CLASSES_M, "classes", device="dev-1")
    h["X-MP-Device"] = "dev-2"
    assert get(server, "/api/classes/lesson?id=dca-02", h)[0] == 402


def test_refunded_or_ended_pass_is_refused(server, monkeypatch):
    owner(monkeypatch, CLASSES_M, refunded=True)
    assert get(server, "/api/classes/lesson?id=dca-02", headers_for(CLASSES_M, "classes"))[0] == 402


def test_licensing_off_means_paid_lessons_stay_locked(server, monkeypatch):
    owner(monkeypatch, CLASSES_M)
    monkeypatch.setattr(app, "_license_secret", lambda: None)
    assert get(server, "/api/classes/lesson?id=dca-02", headers_for(CLASSES_M, "classes"))[0] == 402
    assert get(server, "/api/classes/lesson?id=dca-01")[0] == 200


@pytest.mark.parametrize("lid", ["../catalog", "dca-99", "DCA-01", "dca-1", "", "dca-01%00"])
def test_unknown_or_malformed_ids_are_404(server, lid):
    assert get(server, f"/api/classes/lesson?id={lid}")[0] == 404


# ------------------------------------------------------------------ audio
def test_free_step_audio_streams_as_mp3(server):
    status, raw, ctype = get(server, "/api/classes/audio?id=dca-01&step=0")
    assert status == 200 and raw == AUDIO and ctype == "audio/mpeg"


def test_paid_step_audio_is_gated_like_the_lesson(server, monkeypatch):
    assert get(server, "/api/classes/audio?id=dca-02&step=1")[0] == 402
    owner(monkeypatch, CLASSES_M)
    assert get(server, "/api/classes/audio?id=dca-02&step=1", headers_for(CLASSES_M, "classes"))[0] == 200


@pytest.mark.parametrize("step", ["2", "-1", "x", "", "1.5", "%C2%B2", "99999"])
def test_audio_step_out_of_range_is_404(server, step):
    assert get(server, f"/api/classes/audio?id=dca-01&step={step}")[0] == 404


# ------------------------------------------------------------------ around the gate
@pytest.mark.parametrize("path", ["/classes/build/catalog.json", "/classes/build/dca-02.json",
                                  "/../classes/build/dca-02.json", "/static/../classes/build/dca-02.json"])
def test_compiled_content_is_not_reachable_as_a_static_file(server, path):
    assert get(server, path)[0] == 404


def test_lessons_are_rate_limited_per_client(server, monkeypatch):
    monkeypatch.setattr(app, "_CLASSES_LIMITER", grader.GradeLimiter(per_client=3, window_s=3600,
                                                                      daily_cap=10**9))
    codes = [get(server, "/api/classes/lesson?id=dca-01")[0] for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_the_classes_limiters_have_no_exhaustible_daily_cap():
    # Same reasoning as the license limiter: a global cap is a lockout lever.
    assert app._CLASSES_LIMITER._daily_cap >= 10**9 and app._CLASSES_KEY_LIMITER._daily_cap >= 10**9


def test_a_classes_key_never_unlocks_live_trading(monkeypatch):
    monkeypatch.setattr(desk_api.pilot, "active", lambda now=None: False)
    monkeypatch.setitem(desk_api._GRANT, "until", 0)
    plus = lic.Entitlement(True, "active", tier="proplus", billing="monthly", product_id=PLUS_M)
    assert desk_api.live_permission({}, lambda h: plus)[0] is True      # control: the gate CAN open
    monkeypatch.setitem(desk_api._GRANT, "until", 0)
    cls = lic.Entitlement(True, "active", tier="classes", billing="monthly", product_id=CLASSES_M)
    assert desk_api.live_permission({}, lambda h: cls)[0] is False
    assert desk_api._GRANT["until"] == 0                                   # and it granted nothing


def test_one_key_is_rate_limited_on_paid_lessons(server, monkeypatch):
    owner(monkeypatch, CLASSES_M)
    monkeypatch.setattr(app, "_CLASSES_KEY_LIMITER", grader.GradeLimiter(per_client=2, window_s=3600,
                                                                          daily_cap=10**9))
    h = headers_for(CLASSES_M, "classes")
    codes = [get(server, "/api/classes/lesson?id=dca-02", h)[0] for _ in range(3)]
    assert codes == [200, 200, 429]
    assert get(server, "/api/classes", h)[0] == 429          # the catalogue check spends the same budget


def test_lesson_content_is_never_committed_to_this_public_repo():
    import pathlib
    import subprocess
    root = pathlib.Path(app.__file__).resolve().parent
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "classes/"],
                             capture_output=True, text=True, check=True).stdout.split()
    assert tracked == [], f"paid lesson files are tracked in git: {tracked[:5]}"
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "--no-index",
                              "classes/build/catalog.json", "classes/src/dca/01.json"],
                             capture_output=True, text=True)
    assert ignored.returncode == 0 and ignored.stdout.count("classes/") == 2
