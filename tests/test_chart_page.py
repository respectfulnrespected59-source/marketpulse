"""The live chart on TradingView Lightweight Charts, its /chart page, and quick search.

Pins what a browser needs from the server and the shell: the /chart route, the
vendored engine (exact build, license beside it), a service worker whose shell
list only names files that exist (one 404 fails the whole install), the script
order the engine depends on, and the URL validation on the chart page.
Interaction is verified in a real browser; this file keeps the wiring honest.
"""

import hashlib
import os
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
VENDOR_JS = "vendor/lightweight-charts.standalone.production.js"
# sha256 of the unmodified v5.2.1 standalone build (see the license file header).
VENDOR_SHA256 = "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf"


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
        return resp.status, resp.headers.get("Content-Type"), resp.read()


# ------------------------------------------------------------------ routing
@pytest.mark.parametrize("path", ["/chart", "/chart/", "/chart?symbol=NVDA&kind=stock&tf=5m"])
def test_chart_page_serves_the_app_shell(server, path):
    status, ctype, body = get(server, path)
    assert status == 200 and ctype.startswith("text/html")
    html = body.decode("utf-8")
    assert 'id="liveTradeChart"' in html and 'id="tabs"' in html


def test_the_vendored_engine_is_served_as_javascript(server):
    status, ctype, body = get(server, "/" + VENDOR_JS)
    assert status == 200 and ctype == "text/javascript"
    assert b"window.LightweightCharts" in body


def test_the_engine_license_is_served_as_text(server):
    status, ctype, body = get(server, "/vendor/LIGHTWEIGHT-CHARTS-LICENSE.txt")
    assert status == 200 and ctype.startswith("text/plain")
    assert b"Apache License" in body


# ------------------------------------------------------------------ vendor
def test_vendored_engine_is_the_exact_pinned_build():
    # An edited or swapped library would break the attribution the license asks
    # for and invalidate everything verified against 5.2.1.
    with open(os.path.join(STATIC, VENDOR_JS), "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == VENDOR_SHA256


def test_the_browser_checks_the_engine_it_loads():
    # Subresource Integrity: a tampered or truncated file on the host refuses to
    # run instead of running. Updating the vendored build means updating this too.
    import base64
    with open(os.path.join(STATIC, VENDOR_JS), "rb") as fh:
        digest = base64.b64encode(hashlib.sha384(fh.read()).digest()).decode()
    tag = re.search(r'<script src="' + re.escape(VENDOR_JS) + r'"\s+integrity="([^"]+)"', _read("index.html"))
    assert tag and tag.group(1) == f"sha384-{digest}"


def test_vendored_files_are_exempt_from_line_ending_conversion():
    with open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8") as fh:
        assert re.search(r"^static/vendor/\*\* -text$", fh.read(), re.M)


def test_engine_keeps_the_tradingview_attribution_on():
    assert re.search(r"attributionLogo:\s*true", _read("chart-engine.js"))


# ------------------------------------------------------------------ PWA shell
def _shell_assets():
    block = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\];", _read("sw.js"), re.S).group(1)
    return re.findall(r'"([^"]+)"', block)


def test_every_shell_asset_exists(server):
    # cache.addAll() rejects the whole install if ANY entry 404s, which would
    # quietly leave every installed copy of the app without offline support.
    for asset in _shell_assets():
        status, _, _ = get(server, asset)
        assert status == 200, asset


def test_shell_caches_the_chart_page_and_its_files():
    assets = set(_shell_assets())
    for needed in ("/chart", "/chart.css", "/chart-draw.js", "/chart-engine.js",
                   "/chart-page.js", "/palette.js", "/" + VENDOR_JS):
        assert needed in assets, needed


def test_every_script_and_stylesheet_the_app_loads_is_in_the_shell():
    html = _read("index.html")
    assets = set(_shell_assets())
    local = re.findall(r'<script src="([^"]+)"', html) + re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    for ref in local:
        assert "/" + ref.lstrip("/") in assets, ref


# ------------------------------------------------------------------ load order
def test_scripts_load_in_the_order_the_engine_needs():
    order = re.findall(r'<script src="([^"]+)"', _read("index.html"))
    pos = {name: order.index(name) for name in order}
    # the library, then the drawing layer, then the engine, then the chart state
    assert pos[VENDOR_JS] < pos["chart-draw.js"] < pos["chart-engine.js"] < pos["chart.js"]
    # tools and the page module read chart.js globals; app.js calls into all of them
    assert pos["chart.js"] < pos["chart-tools.js"] < pos["chart-page.js"] < pos["app.js"]
    assert pos["palette.js"] < pos["app.js"]


def test_chart_mode_is_flagged_before_first_paint():
    head = _read("index.html").split("</head>", 1)[0]
    assert 'classList.add("mode-chart")' in head


def test_the_chart_container_is_never_wiped_with_innerhtml():
    # Lightweight Charts owns #liveTradeChart; clearing it by innerHTML (what the
    # SVG renderer used to do) would destroy its canvas for good.
    for name in ("chart.js", "chart-tools.js", "chart-engine.js", "chart-page.js"):
        assert "svg.innerHTML" not in _read(name), name


def test_the_old_svg_renderer_is_gone():
    for name in ("chart.js", "chart-tools.js"):
        src = _read(name)
        for dead in ("_userOverlaySVG", "candlesInRect", "liveLast.geom", "chartView ="):
            assert dead not in src, (name, dead)


# ------------------------------------------------------------------ URL input
def _js_regex(name, const, tail):
    m = re.search(re.escape(const) + r"\s*=\s*/(.+?)/" + tail, _read(name))
    assert m, (name, const)
    return re.compile(m.group(1))


def _symbol_re():
    return _js_regex("chart-page.js", "const CHART_SYMBOL_RE", ";")


@pytest.mark.parametrize("sym", ["NVDA", "BRK-B", "NPN.JO", "^GSPC", "avalanche-2", "btc"])
def test_chart_page_accepts_real_tickers_and_coin_ids(sym):
    assert _symbol_re().fullmatch(sym)


@pytest.mark.parametrize("sym", ["<script>", "NV DA", "a" * 33, "", "x/../y", '"onload'])
def test_chart_page_rejects_anything_else_in_the_url(sym):
    assert not _symbol_re().fullmatch(sym)


@pytest.mark.parametrize("path,is_chart", [("/chart", True), ("/chart/", True),
                                           ("/charts", False), ("/app", False), ("/chart/x", False)])
def test_only_the_chart_path_boots_chart_mode(path, is_chart):
    pattern = _js_regex("chart-page.js", "const CHART_PAGE", r"\.test")
    assert bool(pattern.search(path)) is is_chart
