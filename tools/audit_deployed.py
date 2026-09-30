"""System 3* audit channel: ask the RUNNING system what it is actually running.

Stafford Beer's point, and the reason this file exists: the normal reporting
channel is variety-attenuated and will tell you what you want to hear. On
2026-08-01 `git log` said merged, CI said green, and `git status` said clean
and up to date with origin -- all true, and all irrelevant, because Render has
`autoDeploy: false` and was serving a build four commits old. A reported bug in
the replay dial got chased through source that was not running anywhere.

So this is deliberately NOT a git check. It bypasses the reporting line and
interrogates the live host directly, the way an auditor walks the floor instead
of reading the floor's own report.

    python tools/audit_deployed.py
    python tools/audit_deployed.py --host https://marketpulse-22bi.onrender.com

Exit 0 = live matches local. Exit 1 = DRIFT (the algedonic signal).

Compares LINE COUNTS, not bytes: the local checkout is CRLF and the served file
is LF, so an identical file still shows about one byte of gap per line.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = "https://marketpulse-22bi.onrender.com"
# The build refuses a shorter lesson in a class with paid lessons
# (tools/classes/lesson_compiler.py; a test pins the two numbers together).
MIN_PAID_CLASS_LESSON_S = 480
STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"

# Served from the site root, not /static/. Listed explicitly rather than
# globbed: an audit that silently changes its own scope is not an audit.
WATCHED = [
    "app.js", "chart.js", "chart-tools.js", "wizards.js", "panels.js",
    "home.js", "learn.js", "paper.js", "quickfill.js", "styles.css",
    "index.html", "sw.js",
    "landing.html", "landing/landing.js", "landing/landing.css", "brand.css",
    "license.js", "desk.js",
    # The Lightweight Charts engine, the /chart page and quick search (09-27).
    "chart.css", "chart-draw.js", "chart-engine.js", "chart-options.js", "chart-page.js", "palette.js",
    "vendor/lightweight-charts.standalone.production.js",
    # The landing's live chart, the shared chart theme and the Market Map (09-27).
    "chart-theme.js", "landing/hero-chart.js", "market-map.js", "market-map.css",
    # MarketPulse Classes (09-29).
    "lesson-engine.js", "lesson-player.js", "classes-ui.js", "classes.css",
]

# A line-count match is strong but not proof. These are strings whose presence
# or absence proves a specific shipped behaviour.
#   marker -> (file, must_be_present)
MARKERS = {
    "_syncCursorRange": ("chart.js", True),
    "function goLive": ("chart.js", True),
    "ctr.hidden = !replay.on": ("chart.js", False),   # the OLD locked dial
    "dv-scale": ("wizards.js", True),                 # DCA scale explainer
    "onChange: dcaScheduleRerun": ("wizards.js", True),
    "function forwardToApp": ("landing/landing.js", True),  # installed app -> /app
    "api/markets?kind=": ("home.js", False),
    "@keyframes mp-mol": ("brand.css", True),  # the heartbeat -> melanin loop
    "/api/desk/ping": ("desk.js", True),       # desk shows only where a local desk answers
    "/api/desk/session": ("desk.js", False),   # the old token hand-out must never come back
    ".tab[hidden]": ("styles.css", True),      # else the hidden Trade tab shows on the hosted site
    "LightweightCharts": ("chart-engine.js", True),   # the chart draws with the vendored engine
    "_userOverlaySVG": ("chart.js", False),           # the old SVG renderer must be gone
    "function bootChartPage": ("chart-page.js", True),
    'href="chart.css"': ("index.html", True),
    "function openPalette": ("palette.js", True),
    "function pcChartOptions": ("chart-theme.js", True),     # one look for app + landing
    "window.HeroChart": ("landing/hero-chart.js", True),
    'id="heroChart"': ("landing.html", True),                # the landing actually hosts it
    "window.MarketMap": ("market-map.js", True),
    'id="homeMap"': ("index.html", True),
    'data-view="classes"': ("index.html", True),              # the Classes tab ships
    "function lessonStateAt": ("lesson-engine.js", True),
    "if (lessonView) return { marks: lessonView.marks": ("chart-tools.js", True),  # lessons never touch user drawings
}

TIMEOUT_S = 60


def fetch(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"  ! could not fetch {url}: {exc}")
        return None


def read_local(name: str) -> str | None:
    path = STATIC_DIR / name
    if not path.exists():
        print(f"  ! no local file {path}")
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def line_count(text: str) -> int:
    return text.count("\n")


def audit_assets(host: str) -> list[str]:
    drift: list[str] = []
    print("--- shell assets: local vs served (line counts) ---")
    for name in WATCHED:
        local, served = read_local(name), fetch(f"{host}/{name}")
        if local is None or served is None:
            drift.append(f"{name}: could not compare")
            continue
        local_n, served_n = line_count(local), line_count(served)
        ok = local_n == served_n
        print(f"  {'OK   ' if ok else 'DRIFT'}  {name:<16} local={local_n:<6} live={served_n}")
        if not ok:
            drift.append(f"{name}: {local_n} local lines vs {served_n} live")
    return drift


def audit_markers(host: str) -> list[str]:
    drift: list[str] = []
    print("\n--- feature markers on the LIVE host ---")
    cache: dict[str, str | None] = {}
    for marker, (fname, want) in MARKERS.items():
        if fname not in cache:
            cache[fname] = fetch(f"{host}/{fname}")
        body = cache[fname]
        if body is None:
            drift.append(f"marker {marker!r}: {fname} unreachable")
            continue
        present = marker in body
        ok = present == want
        state = "present" if present else "absent"
        expect = "expected" if want else "expected GONE"
        print(f"  {'OK   ' if ok else 'DRIFT'}  {fname:<12} {marker!r} {state} ({expect})")
        if not ok:
            drift.append(f"marker {marker!r} in {fname}: {state}, wanted {expect}")
    return drift


def audit_no_desk(host: str) -> list[str]:
    """The hosted site must have NO Trade desk: it can place real orders.
    Asks the running host, not the code, and goes red if the desk answers."""
    print("\n--- the hosted site must not offer the Trade desk ---")
    try:
        with urllib.request.urlopen(f"{host}/api/desk/ping", timeout=TIMEOUT_S) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        print(f"  ! could not reach {host}: {exc}")
        return ["desk check: host unreachable"]
    ok = status == 404
    print(f"  {'OK   ' if ok else 'DRIFT'}  /api/desk/ping -> {status} (expected 404)")
    return [] if ok else [f"/api/desk/ping answered {status} on the HOSTED site: the desk must be local-only"]


def _get(url: str, headers: dict | None = None) -> tuple[int, str]:
    """(status, body) for a URL; HTTP errors are answers, not failures."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError) as exc:
        print(f"  ! could not reach {url}: {exc}")
        return 0, ""


# The owner's rule (docs/CLASSES_PLAN.md): lesson 1 of every class is free, the rest
# need the pass; the setup class is free throughout. The audit holds the server to
# THIS, not to the server's own "free" flags, so a flag flipped by a bug goes red.
FREE_CLASSES = frozenset({"setup"})


def _should_be_paid(lesson_id: str) -> bool:
    cls, _, num = lesson_id.partition("-")
    return cls not in FREE_CLASSES and num != "01"


def _probe_paid(host: str, lesson_id: str, get) -> list[str]:
    problems = []
    for route in (f"/api/classes/lesson?id={lesson_id}", f"/api/classes/audio?id={lesson_id}&step=0"):
        for label, headers in (("no key", None), ("a garbage key", {"X-MP-License-Key": "not-a-real-key-0000"})):
            code, _ = get(f"{host}{route}", headers)
            ok = code == 402
            print(f"  {'OK   ' if ok else 'DRIFT'}  {route} with {label} -> {code} (expected 402)")
            if not ok:
                problems.append(f"PAID {route} answered {code} with {label}")
    return problems


def _audit_lengths(classes: list) -> list[str]:
    """A class we charge for must be full-length lessons, and the catalogue must
    SAY how long each runs. On 2026-09-30 ten lessons of about 90 seconds were
    live behind a $19/mo pass and every other check on this page was green:
    nothing anywhere measured a lesson's length."""
    problems = []
    for c in classes:
        lessons = c.get("lessons", [])
        if all(l.get("free") for l in lessons):
            continue                          # a class given away may be as short as it likes
        for l in lessons:
            secs = l.get("seconds")
            known = isinstance(secs, int) and not isinstance(secs, bool) and secs > 0
            ok = known and secs >= MIN_PAID_CLASS_LESSON_S
            clock = f"{secs // 60}:{secs % 60:02d}" if known else "unknown"
            print(f"  {'OK   ' if ok else 'DRIFT'}  {l['id']} runs {clock} "
                  f"(a class for sale needs {MIN_PAID_CLASS_LESSON_S // 60}:00+)")
            if not known:
                problems.append(f"{l['id']} is in a class for sale but the catalogue does not say how long it runs")
            elif not ok:
                problems.append(f"{l['id']} runs {clock}: every lesson of a class for sale must run "
                                f"{MIN_PAID_CLASS_LESSON_S // 60}:00 or more")
    return problems


def audit_classes_gate(host: str, get=None) -> list[str]:
    """Paid lessons AND their audio must be refused without a valid license, the
    catalogue must not call a paid lesson free, and the compiled files must not be
    reachable as plain files. Asks the running host."""
    get = get or _get
    print("\n--- Classes: paid lessons stay behind the license ---")
    code, body = get(f"{host}/api/classes", None)
    if code != 200:
        return [f"/api/classes answered {code}"]
    try:
        classes = json.loads(body).get("classes", [])
        lessons = [l for c in classes for l in c.get("lessons", [])]
        ids = [(l["id"], bool(l.get("free"))) for l in lessons]
    except (ValueError, AttributeError, KeyError, TypeError):
        return ["/api/classes did not return a catalogue"]
    problems = [f"catalogue marks {lid} FREE but the plan says it is paid"
                for lid, free in ids if free and _should_be_paid(lid)]
    problems += _audit_lengths(classes)
    # Lessons have been published since 2026-09-29, so an empty catalogue means the
    # deploy-time pull failed (expired MP_CLASSES_TOKEN, renamed repo) and the site
    # is quietly selling a pass with nothing behind it.
    print(f"  {'OK   ' if ids else 'DRIFT'}  live catalogue lists {len(ids)} lesson(s) (expected 1+)")
    if not ids:
        problems.append("the live catalogue has NO lessons: the private lesson pull failed "
                        "(check MP_CLASSES_TOKEN on Render; it expires 2027-09-29)")
    raw, _ = get(f"{host}/classes/build/catalog.json", None)
    print(f"  {'OK   ' if raw == 404 else 'DRIFT'}  /classes/build/catalog.json -> {raw} (expected 404)")
    if raw != 404:
        problems.append(f"compiled lesson files are reachable as plain files ({raw})")
    paid = [lid for lid, _ in ids if _should_be_paid(lid)]
    if not paid:
        print("  (no paid lessons published yet: nothing behind the gate to ask for)")
        return problems
    return problems + _probe_paid(host, paid[0], get)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit what the live host actually serves.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    args = parser.parse_args()
    host = args.host.rstrip("/")

    print(f"System 3* audit -> {host}")
    print("(bypasses git; asks the running host what it serves)\n")

    drift = audit_assets(host) + audit_markers(host) + audit_no_desk(host) + audit_classes_gate(host)

    print()
    if drift:
        print("=" * 64)
        print("ALGEDONIC: the live host is NOT running local HEAD.")
        for item in drift:
            print(f"  - {item}")
        print("\nautoDeploy is false by design -- merging does not deploy.")
        print("Deploy: dashboard.render.com -> Manual Deploy -> Deploy latest commit")
        print("=" * 64)
        return 1

    print("Live host matches local HEAD on every watched asset and marker.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
