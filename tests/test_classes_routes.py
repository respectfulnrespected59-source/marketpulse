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
    # ...but the rule must be anchored: the lesson BUILDER lives in tools/classes/ and must ship.
    builder = subprocess.run(["git", "-C", str(root), "check-ignore", "--no-index", "tools/classes/build.py"],
                             capture_output=True, text=True)
    assert builder.returncode == 1, "tools/classes/ is being ignored by the lessons rule"


# ------------------------------------------------------------------ the deploy audit
def _audit():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(app.__file__).resolve().parent / "tools"))
    import audit_deployed
    return audit_deployed


@pytest.fixture(autouse=True)
def dca_is_a_paid_class(request, monkeypatch):
    """The gate checks need a class the plan charges for. The real plan (2026-09-30) charges
    for none, so these tests name one; tests with real_plan in their name get the plan as shipped."""
    if "real_plan" not in request.node.name:
        monkeypatch.setattr(_audit(), "PAID_CLASSES", frozenset({"dca"}))


CATALOG = json.dumps({"classes": [{"id": "dca", "lessons": [{"id": "dca-01", "free": True, "seconds": 540},
                                                            {"id": "dca-02", "free": False, "seconds": 560}]}]})
PAID = ["/api/classes/lesson?id=dca-02", "/api/classes/audio?id=dca-02&step=0"]


def fake_host(over=None):
    """A host that refuses every paid probe; `over` makes one answer leak."""
    over = over or {}

    def get(url, headers=None):
        path = url[1:]
        key = "keyed" if headers else "bare"
        if (path, key) in over:
            return over[(path, key)]
        if path == "/api/classes":
            return over.get(path, (200, CATALOG))
        if path == "/classes/build/catalog.json":
            return over.get(path, (404, ""))
        return (402, "")
    return get


def test_the_audit_passes_a_host_that_refuses_paid_lessons():
    assert _audit().audit_classes_gate("h", get=fake_host()) == []


@pytest.mark.parametrize("leak", [(PAID[0], "bare"), (PAID[1], "bare"), (PAID[0], "keyed"), (PAID[1], "keyed")])
def test_the_audit_goes_red_when_any_paid_route_answers(leak):
    # Lesson AND audio, with no key AND a garbage key: every one must be able to fail.
    assert _audit().audit_classes_gate("h", get=fake_host({leak: (200, "{}")})) != []


def test_the_audit_goes_red_when_raw_files_are_reachable():
    assert _audit().audit_classes_gate("h", get=fake_host({"/classes/build/catalog.json": (200, "{}")})) != []


def test_the_audit_does_not_trust_the_servers_own_free_flag():
    lying = json.dumps({"classes": [{"id": "dca", "lessons": [{"id": "dca-01", "free": True},
                                                               {"id": "dca-02", "free": True}]}]})
    assert _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, lying)})) != []


def test_the_buy_link_must_be_https(monkeypatch):
    import importlib
    import config
    for value, want in (("javascript:alert(1)", None), ("http://x.test", None),
                        ("https://quantummelaninmedia.gumroad.com/l/classes", "https://quantummelaninmedia.gumroad.com/l/classes")):
        monkeypatch.setenv("MP_CLASSES_URL", value)
        assert importlib.reload(config).CLASSES_URL == want
    monkeypatch.delenv("MP_CLASSES_URL")
    importlib.reload(config)


def test_the_audit_goes_red_when_the_live_catalogue_is_empty():
    # An expired pull token deploys fine and silently empties the Classes tab.
    empty = json.dumps({"classes": [{"id": "dca", "lessons": []}]})
    problems = _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, empty)}))
    assert any("NO lessons" in p for p in problems)


# ------------------------------------------------------------------ a class for sale is a full class
def _catalog(*lessons, cls="dca"):
    return json.dumps({"classes": [{"id": cls, "lessons": [
        {"id": lid, "free": free, **({} if secs is None else {"seconds": secs})} for lid, free, secs in lessons]}]})


def test_the_audit_goes_red_when_a_class_for_sale_has_a_short_lesson():
    # The real miss (09-30): lessons of ~90 s were live behind a $19/mo pass and every check was green.
    short = _catalog(("dca-01", True, 88), ("dca-02", False, 560))
    problems = _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, short)}))
    assert any("dca-01" in p and "1:28" in p for p in problems)


@pytest.mark.parametrize("secs", [None, 0, "540", True])
def test_the_audit_goes_red_when_a_paid_class_does_not_say_how_long_a_lesson_runs(secs):
    unknown = _catalog(("dca-01", True, 540), ("dca-02", False, secs))
    problems = _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, unknown)}))
    assert any("dca-02" in p for p in problems)


def test_the_audit_lets_an_all_free_class_be_short():
    free = json.dumps({"classes": [
        {"id": "setup", "lessons": [{"id": "setup-01", "free": True, "seconds": 80}]},
        {"id": "dca", "lessons": [{"id": "dca-01", "free": True, "seconds": 540},
                                  {"id": "dca-02", "free": False, "seconds": 560}]}]})
    assert _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, free)})) == []


def test_the_audit_holds_the_para_sail_class_to_its_five_minutes():
    # The owner asked for ~5-minute Para-Sail lessons (09-30); the old DCA class they replace is gone.
    def cat(secs):
        return json.dumps({"classes": [{"id": "parasail", "lessons": [
            {"id": "parasail-01", "free": True, "seconds": secs}]}]})
    short = _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, cat(250))}))
    assert any("parasail-01" in p and "4:10" in p and "5:00" in p for p in short)
    assert _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, cat(355))})) == []


def test_the_audit_and_the_build_agree_on_the_minimum_length():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(app.__file__).resolve().parent / "tools" / "classes"))
    import lesson_compiler
    assert _audit().MIN_PAID_CLASS_LESSON_S == lesson_compiler.MIN_PAID_CLASS_LESSON_S


def test_the_hourly_budgets_fit_full_length_lessons():
    # A lesson load is the lesson plus one clip per step. Sized for ~13-request loads, the old
    # budgets shut a paying student out on the seventh 64-step lesson of the hour.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(app.__file__).resolve().parent / "tools" / "classes"))
    import lesson_compiler
    load = lesson_compiler.MAX_LESSON_STEPS + 1              # the build refuses a longer lesson
    assert app.CLASSES_PER_KEY_PER_HOUR // load >= 20          # a whole class, rewatched, per key
    assert app.CLASSES_PER_CLIENT_PER_HOUR // load >= 40       # a classroom behind one address
    assert app.CLASSES_PER_KEY_PER_HOUR <= app.CLASSES_PER_CLIENT_PER_HOUR


# ------------------------------------------------------------------ the classes are free (owner, 2026-09-30)
ALL_FREE = json.dumps({"classes": [
    {"id": "setup", "lessons": [{"id": "setup-01", "free": True, "seconds": 80}]},
    {"id": "dca", "lessons": [{"id": "dca-01", "free": True, "seconds": 598},
                              {"id": "dca-02", "free": True, "seconds": 590}]}]})


def test_the_real_plan_charges_for_no_class():
    assert _audit().PAID_CLASSES == frozenset()


def test_the_real_plan_passes_a_host_where_every_lesson_is_free():
    assert _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, ALL_FREE)})) == []


def test_the_real_plan_goes_red_when_a_lesson_is_still_locked():
    # A deploy that pulled the old lessons would show a PASS badge on a class we give away.
    problems = _audit().audit_classes_gate("h", get=fake_host())       # CATALOG marks dca-02 paid
    assert any("dca-02" in p and "free" in p for p in problems)


def test_the_real_plan_still_wants_full_length_lessons_in_a_free_class():
    # Free is not a licence to be short: the Para-Sail class is held to 5:00 whether or not it is sold.
    short = json.loads(ALL_FREE)
    short["classes"].append({"id": "parasail", "lessons": [{"id": "parasail-01", "free": True, "seconds": 88}]})
    problems = _audit().audit_classes_gate("h", get=fake_host({"/api/classes": (200, json.dumps(short))}))
    assert any("parasail-01" in p and "1:28" in p for p in problems)
    assert not any("setup-01" in p for p in problems)                  # not yet rebuilt: not yet held to it
