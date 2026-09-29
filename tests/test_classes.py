"""classes.py: the compiled-lesson manifest and who a lesson is for.

The manifest is the ONLY source of file paths the server will open for a
lesson, so every entry is validated on load and anything odd is dropped rather
than trusted: ids must look like `dca-01`, files must be plain names inside the
build directory, audio must be hash-named .mp3 files that exist.
"""

import json

import pytest

import class_catalog as classes
import licensing as lic

pytestmark = pytest.mark.unit


def write(root, lessons, extra_files=()):
    (root / "audio").mkdir(parents=True, exist_ok=True)
    for name in extra_files:
        (root / "audio" / name).write_bytes(b"x")
    for l in lessons:
        f = l.get("file")
        if f and "/" not in f and "\\" not in f and ".." not in f:
            (root / f).write_text(json.dumps({"id": l["id"]}))
    (root / "catalog.json").write_text(json.dumps({"classes": [{"id": "dca", "title": "DCA", "lessons": lessons}]}))


def lesson(lid="dca-01", free=True, audio=("aaaaaaaaaaaa.mp3",), file=None):
    return {"id": lid, "title": "T", "free": free, "file": file or f"{lid}.json", "audio": list(audio)}


def test_missing_build_is_an_empty_catalogue(tmp_path):
    m = classes.load_manifest(tmp_path / "nope")
    assert classes.public_catalog(m) == [] and classes.lesson_body(m, "dca-01") is None


def test_valid_lesson_loads(tmp_path):
    write(tmp_path, [lesson()], ["aaaaaaaaaaaa.mp3"])
    m = classes.load_manifest(tmp_path)
    assert classes.find(m, "dca-01").free is True
    assert classes.lesson_body(m, "dca-01") == {"id": "dca-01"}
    assert classes.audio_path(m, "dca-01", 0).name == "aaaaaaaaaaaa.mp3"


@pytest.mark.parametrize("bad", [
    lesson(lid="../x"), lesson(lid="DCA-01"), lesson(file="../secret.json"),
    lesson(file="sub/dca-01.json"), lesson(audio=("../../app.py",)), lesson(audio=("notahash.mp3",)),
    lesson(audio=("ffffffffffff.mp3",)),   # listed but not on disk
])
def test_suspicious_entries_are_dropped_not_trusted(tmp_path, bad):
    write(tmp_path, [bad], ["aaaaaaaaaaaa.mp3"])
    m = classes.load_manifest(tmp_path)
    listed = [l["id"] for c in classes.public_catalog(m) for l in c["lessons"]]
    assert bad["id"] not in listed
    assert classes.lesson_body(m, bad["id"]) is None


def test_free_flag_must_be_a_real_boolean(tmp_path):
    entry = lesson()
    entry["free"] = "yes"          # truthy string must NOT make a lesson free
    write(tmp_path, [entry], ["aaaaaaaaaaaa.mp3"])
    assert classes.find(classes.load_manifest(tmp_path), "dca-01").free is False


def test_audio_path_rejects_out_of_range_steps(tmp_path):
    write(tmp_path, [lesson()], ["aaaaaaaaaaaa.mp3"])
    m = classes.load_manifest(tmp_path)
    assert classes.audio_path(m, "dca-01", 1) is None and classes.audio_path(m, "dca-01", -1) is None


def test_a_corrupt_catalog_fails_closed_to_empty(tmp_path):
    (tmp_path / "catalog.json").write_text("{not json")
    assert classes.public_catalog(classes.load_manifest(tmp_path)) == []


@pytest.mark.parametrize("tier,active,granted", [
    ("classes", True, True), ("proplus", True, True), ("pro", True, False),
    ("classes", False, False), (None, False, False),
])
def test_who_gets_classes(tier, active, granted):
    assert lic.grants_classes(lic.Entitlement(active, "x", tier=tier)) is granted


def test_classes_tier_has_two_devices_one_account():
    plans = lic.parse_plans(json.dumps({"c": {"tier": "classes", "billing": "monthly"}}))
    assert plans["c"].devices == 2 and plans["c"].accounts == 1


def test_oversized_audio_is_dropped(tmp_path, monkeypatch):
    # Served files are read whole; a huge "narration" file is a build mistake, not a lesson.
    monkeypatch.setattr(classes, "MAX_AUDIO_BYTES", 1)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "aaaaaaaaaaaa.mp3").write_bytes(b"xx")
    (tmp_path / "dca-01.json").write_text("{}")
    (tmp_path / "catalog.json").write_text(json.dumps({"classes": [{"id": "dca", "lessons": [lesson()]}]}))
    assert classes.find(classes.load_manifest(tmp_path), "dca-01") is None


def test_a_lesson_file_must_be_an_object(tmp_path):
    write(tmp_path, [lesson()], ["aaaaaaaaaaaa.mp3"])
    (tmp_path / "dca-01.json").write_text("[1, 2, 3]")
    assert classes.lesson_body(classes.load_manifest(tmp_path), "dca-01") is None


def test_the_shipped_build_path_loads_even_when_absent():
    import app
    classes.load_manifest(app.CLASSES_BUILD)          # must never raise at import or reload


@pytest.mark.parametrize("tier,active,granted", [
    ("pro", True, True), ("proplus", True, True), ("classes", True, False), ("pro", False, False),
])
def test_who_gets_pro(tier, active, granted):
    assert lic.grants_pro(lic.Entitlement(active, "x", tier=tier)) is granted
