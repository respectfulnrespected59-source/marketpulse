"""The public landing page at / and the app at /app.

Pins the routing split (landing is the front door, the app moved to /app
without breaking installed PWAs) and the honesty rules the landing copy must
keep: no guarantees, a risk disclosure, no em dashes, valid CSS math.
"""

import json
import os
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app

pytestmark = pytest.mark.unit

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(base, path):
    with urllib.request.urlopen(f"{base}{path}", timeout=5) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read().decode("utf-8")


# ------------------------------------------------------------------ routing
def test_root_serves_the_landing_not_the_app(server):
    status, ctype, body = get(server, "/")
    assert status == 200 and ctype.startswith("text/html")
    assert 'id="landing"' in body
    assert 'id="tabs"' not in body


def test_app_path_serves_the_app(server):
    status, ctype, body = get(server, "/app")
    assert status == 200 and ctype.startswith("text/html")
    assert 'id="tabs"' in body


def test_app_path_with_trailing_slash_serves_the_app(server):
    _, _, body = get(server, "/app/")
    assert 'id="tabs"' in body


def test_static_guard_refuses_a_sibling_dir_sharing_the_prefix(server, tmp_path, monkeypatch):
    # "static" is a string prefix of "static-evil"; startswith(STATIC) alone let
    # /../static-evil/x through. The guard must compare whole path components.
    root = tmp_path / "static"
    root.mkdir()
    evil = tmp_path / "static-evil"
    evil.mkdir()
    (evil / "secret.txt").write_text("leak", encoding="utf-8")
    monkeypatch.setattr(app, "STATIC", str(root))
    try:
        status, _, body = get(server, "/../static-evil/secret.txt")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, ""
    assert status == 404 and "leak" not in body


def test_landing_forwards_installed_and_deep_links_to_the_app():
    js = _read("landing/landing.js")
    # An installed PWA from before the move opens "/?src=pwa"; old shortcuts
    # open "/?view=dca". Both must land in the app, not the marketing page.
    assert "display-mode: standalone" in js
    assert "view" in js and "src" in js
    assert "/app" in js


def test_manifest_starts_the_installed_app_at_app():
    man = json.loads(_read("manifest.webmanifest"))
    assert man["start_url"].startswith("/app")
    assert all(s["url"].startswith("/app") for s in man["shortcuts"])


def test_service_worker_caches_both_pages():
    sw = _read("sw.js")
    assert '"/app"' in sw
    assert '"/landing/landing.css"' in sw and '"/landing/landing.js"' in sw


def test_every_client_asks_markets_by_type_not_kind():
    # /api/markets reads ?type=. The cockpit once asked ?kind=stocks, got crypto
    # back twice, and told users "0 of 24 names qualify" while the landing, reading
    # stocks, showed 8 strong reads. Same engine, contradicting itself one click apart.
    for name in os.listdir(STATIC):
        if name.endswith(".js"):
            assert "api/markets?kind=" not in _read(name), name
    assert "api/markets?kind=" not in _read("landing/landing.js")


# ------------------------------------------------------------------ honesty rules
def test_landing_has_a_risk_disclosure():
    html = _read("landing.html")
    assert "Risk disclosure" in html
    assert "not financial advice" in html.lower()


def test_landing_never_promises_returns():
    html = _read("landing.html").lower()
    # "guarantee" may only appear negated ("no guarantees", "never guarantee").
    for m in re.finditer(r"guarantee", html):
        window = html[max(0, m.start() - 40):m.start()]
        assert re.search(r"\b(no|never|not|can't|cannot|nobody)\b", window), window


def test_landing_copy_has_no_em_dashes():
    for name in ("landing.html", "landing/landing.js"):
        assert "—" not in _read(name), name


def test_landing_css_math_is_valid():
    # clamp(2.5rem,1.2rem+5.2vw,5rem) is INVALID: calc operators need spaces.
    # The browser silently drops the whole declaration.
    css = _read("landing/landing.css")
    for fn in re.findall(r"(?:clamp|calc)\(([^;{}]*)\)", css):
        assert not re.search(r"[\w%)]\+[\w(.]", fn), fn
        assert not re.search(r"[\d%)]-[\d(.]", fn), fn


def test_landing_shows_placeholders_not_fake_zeros_before_data():
    # A number that renders 0 before the engine answers is also a claim.
    html = _read("landing.html")
    for m in re.finditer(r'data-live="[^"]+"[^>]*>([^<]*)<', html):
        assert m.group(1).strip() in ("", "…", "..."), m.group(0)


def test_static_guard_refuses_another_drive_without_crashing(server):
    # On Windows commonpath() raises for paths on different drives; that must
    # be a plain 404, not a handler crash.
    try:
        status, _, _ = get(server, "/D:/windows/win.ini")
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 404
