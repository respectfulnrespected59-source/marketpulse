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
import pathlib
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = "https://marketpulse-22bi.onrender.com"
STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"

# Served from the site root, not /static/. Listed explicitly rather than
# globbed: an audit that silently changes its own scope is not an audit.
WATCHED = [
    "app.js", "chart.js", "chart-tools.js", "wizards.js", "panels.js",
    "home.js", "learn.js", "paper.js", "quickfill.js", "styles.css",
    "index.html", "sw.js",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit what the live host actually serves.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    args = parser.parse_args()
    host = args.host.rstrip("/")

    print(f"System 3* audit -> {host}")
    print("(bypasses git; asks the running host what it serves)\n")

    drift = audit_assets(host) + audit_markers(host)

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
