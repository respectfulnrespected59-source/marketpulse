"""MarketPulse Classes: the compiled-lesson manifest the server serves from.

Lessons are compiled by tools/classes/build.py into classes/build/ — OUTSIDE
static/, because everything under static/ is public. Only the /api/classes/*
routes in app.py read them, after the license gate. The classes/ directory is
git-ignored: this repo is public, so lesson content must never be committed.

The manifest (catalog.json) is the only source of file paths this module will
ever open for a lesson. Request input never becomes a path: it is matched
against manifest ids, and every manifest entry is validated on load — a
suspicious entry is dropped, never trusted. A missing or corrupt build is an
empty catalogue, not an error page. The manifest is read once at startup, so
new lessons go live on the next restart (a deploy restarts the process).

This file ships in both buyer-pack editions; it holds no lesson content.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

LESSON_ID_RE = re.compile(r"[a-z]{2,8}-\d{2}")
CLASS_ID_RE = re.compile(r"[a-z]{2,8}")
LESSON_FILE_RE = re.compile(r"[a-z]{2,8}-\d{2}\.json")
AUDIO_FILE_RE = re.compile(r"[0-9a-f]{12,64}\.mp3")
MAX_TITLE = 120
MAX_AUDIO_BYTES = 5 * 1024 * 1024   # one narration step is ~100 KB; anything huge is a build mistake
MAX_LESSON_SECONDS = 4 * 3600       # a running time past this is a build mistake, shown as unknown


@dataclass(frozen=True)
class Lesson:
    id: str
    class_id: str
    title: str
    free: bool
    file: str
    audio: tuple[str, ...]
    seconds: int = 0                # running time; 0 = unknown (a build from before it was recorded)


@dataclass(frozen=True)
class ClassInfo:
    id: str
    title: str
    tagline: str
    lessons: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    root: Path
    classes: tuple[ClassInfo, ...]
    lessons: dict[str, Lesson]


def _text(value: object, limit: int = MAX_TITLE) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _audio_ok(root: Path, name: object) -> bool:
    if not (isinstance(name, str) and AUDIO_FILE_RE.fullmatch(name)):
        return False
    path = root / "audio" / name
    try:
        return path.is_file() and path.stat().st_size <= MAX_AUDIO_BYTES
    except OSError:
        return False


def _seconds(value: object) -> int:
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_LESSON_SECONDS
    return value if ok else 0


def _lesson(raw: dict, class_id: str, root: Path) -> Lesson | None:
    """A manifest entry, or None if anything about it is off."""
    lid, file, audio = raw.get("id"), raw.get("file"), raw.get("audio")
    if not (isinstance(lid, str) and LESSON_ID_RE.fullmatch(lid)):
        return None
    if not (isinstance(file, str) and LESSON_FILE_RE.fullmatch(file) and (root / file).is_file()):
        return None
    if not (isinstance(audio, list) and audio and all(_audio_ok(root, a) for a in audio)):
        return None
    return Lesson(lid, class_id, _text(raw.get("title")), raw.get("free") is True, file, tuple(audio),
                  _seconds(raw.get("seconds")))


def load_manifest(root: str | Path) -> Manifest:
    root = Path(root)
    try:
        data = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        raw_classes = data.get("classes") if isinstance(data, dict) else None
    except (OSError, ValueError):
        raw_classes = None
    infos: list[ClassInfo] = []
    lessons: dict[str, Lesson] = {}
    for c in raw_classes if isinstance(raw_classes, list) else []:
        cid = c.get("id") if isinstance(c, dict) else None
        if not (isinstance(cid, str) and CLASS_ID_RE.fullmatch(cid)):
            continue
        raw_lessons = c.get("lessons")
        ids = []
        for raw in raw_lessons if isinstance(raw_lessons, list) else []:
            lsn = _lesson(raw, cid, root) if isinstance(raw, dict) else None
            if lsn and lsn.id not in lessons:
                lessons[lsn.id] = lsn
                ids.append(lsn.id)
        infos.append(ClassInfo(cid, _text(c.get("title")), _text(c.get("tagline")), tuple(ids)))
    return Manifest(root, tuple(infos), lessons)


def public_catalog(m: Manifest) -> list[dict]:
    """What anyone may see: titles, which lessons are free, how many steps and
    how long each runs. No narration, no audio names, no chart data."""
    return [{"id": c.id, "title": c.title, "tagline": c.tagline,
             "lessons": [{"id": lid, "title": m.lessons[lid].title, "free": m.lessons[lid].free,
                          "steps": len(m.lessons[lid].audio), "seconds": m.lessons[lid].seconds}
                         for lid in c.lessons]}
            for c in m.classes]


def find(m: Manifest, lesson_id: object) -> Lesson | None:
    if not isinstance(lesson_id, str) or not LESSON_ID_RE.fullmatch(lesson_id):
        return None
    return m.lessons.get(lesson_id)


def lesson_body(m: Manifest, lesson_id: object) -> dict | None:
    lsn = find(m, lesson_id)
    if not lsn:
        return None
    try:
        body = json.loads((m.root / lsn.file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def audio_path(m: Manifest, lesson_id: object, step: object) -> Path | None:
    lsn = find(m, lesson_id)
    if not lsn or not isinstance(step, int) or isinstance(step, bool) or not 0 <= step < len(lsn.audio):
        return None
    return m.root / "audio" / lsn.audio[step]
