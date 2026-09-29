"""Build every lesson into classes/build/ (the private repo's served output).

Reads   classes/src/classes.json         {"dca": {"title": ..., "tagline": ...}, ...}  (class order)
        classes/src/<class>/<nn>.json     authored lessons
        classes/tapes/<tape_id>.json      frozen charts (capture_tape.py)
Writes  classes/build/                    catalog.json, <lesson>.json, audio/<hash>.mp3

Any lesson that fails validation stops the build with the reason: a broken
lesson never ships half-built. Narration only re-bakes when its words change.

Run:  python tools/classes/build.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lesson_compiler as lc  # noqa: E402

CLASSES = HERE.parents[1] / "classes"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    meta_file = CLASSES / "src" / "classes.json"
    if not meta_file.is_file():
        print(f"no {meta_file}: clone the private lessons repo into classes/ first")
        return 2
    meta = _load(meta_file)
    sources = [_load(p) for cid in meta for p in sorted((CLASSES / "src" / cid).glob("*.json"))]
    tapes = {p.stem: _load(p) for p in sorted((CLASSES / "tapes").glob("*.json"))}
    import voice
    try:
        built = lc.build_all(sources, tapes, meta, CLASSES / "build", bake=voice.bake, voice_key=voice.VOICE_KEY)
    except lc.LessonError as exc:
        print(f"BUILD STOPPED: {exc}")
        return 1
    except (OSError, subprocess.CalledProcessError, KeyError) as exc:
        # Nothing served was touched: lesson files and the catalogue are written after every bake.
        print(f"BUILD STOPPED while recording narration ({type(exc).__name__}: {exc})")
        return 1
    for lesson in built:
        secs = sum(s["durMs"] for s in lesson["steps"]) / 1000
        print(f"  {lesson['id']:<8} {'FREE' if lesson['free'] else 'paid'}  {len(lesson['steps']):>2} steps"
              f"  {secs:5.1f}s  {lesson['title']}")
    print(f"built {len(built)} lesson(s) -> {CLASSES / 'build'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
