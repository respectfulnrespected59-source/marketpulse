"""The lesson compiler: authored lesson + frozen tape -> exact chart steps.

A lesson is narration that describes a chart, so the compiler's whole job is
to make it impossible for the two to disagree: every bar reference must exist
in the tape, every number spoken is computed from the tape, nothing is drawn
where the viewer can't see it yet, and nothing promises money.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "classes"))

import class_catalog  # noqa: E402
import lesson_compiler as lc  # noqa: E402

pytestmark = pytest.mark.unit

DAY = 86_400
T0 = 1_760_000_000 - (1_760_000_000 % DAY)


def tape(closes):
    """A daily tape whose bar i closes at closes[i] (high/low 1% around it)."""
    return {"symbol": "BTC", "kind": "crypto", "tf": "1D",
            "ts": [T0 + i * DAY for i in range(len(closes))],
            "ohlc": [[c, round(c * 1.01, 2), round(c * 0.99, 2), c] for c in closes],
            "volume": [1.0] * len(closes)}


def lesson(steps, **over):
    base = {"id": "dca-01", "class": "dca", "title": "Same dollars", "free": True, "tape": "t",
            "practice": {"symbol": "btc", "kind": "crypto", "tf": "1D"}, "vars": {}, "steps": steps}
    base.update(over)
    return base


def step(say="Watch the chart.", who="T", do=()):
    return {"who": who, "say": say, "do": list(do)}


FLAT = tape([100.0] * 10)


# ------------------------------------------------------------------ bar references
def test_negative_bar_counts_from_the_end():
    out = lc.compile_lesson(lesson([step(do=[{"op": "seek", "bar": -1}])]), FLAT)
    assert out["steps"][0]["do"] == [{"op": "seek", "ts": FLAT["ts"][-1]}]


def test_a_bar_outside_the_tape_is_an_error():
    with pytest.raises(lc.LessonError, match="bar 10"):
        lc.compile_lesson(lesson([step(do=[{"op": "seek", "bar": 10}])]), FLAT)


def test_mark_prices_come_from_the_tape():
    t = tape([100.0, 120.0, 90.0])
    out = lc.compile_lesson(lesson([step(do=[{"op": "seek", "bar": -1},
                                             {"op": "mark", "bar": 1, "at": "high"}])]), t)
    assert out["steps"][0]["do"][1] == {"op": "mark", "ts": t["ts"][1], "price": 121.2, "dir": "mark"}


# ------------------------------------------------------------------ computed values
def test_dca_plan_buys_on_schedule_and_averages_by_coins_not_prices():
    t = tape([100.0, 50.0, 100.0, 50.0, 100.0])
    plan = lc.compute_vars({"plan": {"fn": "dca", "every": 2, "start": 0}}, t)["plan"]
    assert [b["bar"] for b in plan.buys] == [0, 2, 4]
    assert plan.n == 3
    # Same dollars at 100, 100, 100 -> average 100; now a plan that also buys the dips:
    dips = lc.compute_vars({"p": {"fn": "dca", "every": 1, "start": 0}}, t)["p"]
    assert dips.mean == pytest.approx(80.0)
    assert dips.avg == pytest.approx(5 / (3 / 100 + 2 / 50))     # harmonic: total $ / total coins
    assert dips.avg < dips.mean


@pytest.mark.parametrize("right,strike,premium,be", [("put", 350, 1.64, 348.36), ("call", 350, 2.5, 352.5)])
def test_breakeven_is_strike_minus_or_plus_premium(right, strike, premium, be):
    v = lc.compute_vars({"b": {"fn": "breakeven", "right": right, "strike": strike, "premium": premium}}, FLAT)
    assert v["b"].value == pytest.approx(be)


def test_narration_numbers_are_filled_from_the_tape():
    t = tape([100.0, 50.0])
    src = lesson([step(say="Your average cost is ${p.avg:,.2f} after {p.n} buys.",
                       do=[{"op": "seek", "bar": -1}])],
                 vars={"p": {"fn": "dca", "every": 1, "start": 0}})
    assert lc.compile_lesson(src, t)["steps"][0]["say"] == "Your average cost is $66.67 after 2 buys."


def test_a_narration_placeholder_with_no_value_is_an_error():
    with pytest.raises(lc.LessonError, match="nope"):
        lc.compile_lesson(lesson([step(say="It is {nope}.")]), FLAT)


def test_buys_macro_drops_only_the_buys_revealed_in_that_step():
    t = tape([100.0] * 9)
    src = lesson([step(do=[{"op": "seek", "bar": 0}, {"op": "buys", "var": "p"}]),
                  step(do=[{"op": "play", "to": 5}, {"op": "buys", "var": "p"}]),
                  step(do=[{"op": "play", "to": 8}, {"op": "buys", "var": "p"}])],
                 vars={"p": {"fn": "dca", "every": 3, "start": 0}})
    out = lc.compile_lesson(src, t)
    marked = [[o["ts"] for o in s["do"] if o["op"] == "mark"] for s in out["steps"]]
    assert marked == [[t["ts"][0]], [t["ts"][3]], [t["ts"][6]]]


# ------------------------------------------------------------------ what the viewer can see
def test_drawing_past_the_steps_cursor_is_an_error():
    # Bars after the cursor are hidden, so a mark there would silently not appear.
    with pytest.raises(lc.LessonError, match="not revealed"):
        lc.compile_lesson(lesson([step(do=[{"op": "seek", "bar": 2}, {"op": "mark", "bar": 5}])]), FLAT)


def test_a_level_far_off_the_chart_is_an_error():
    with pytest.raises(lc.LessonError, match="off the chart"):
        lc.compile_lesson(lesson([step(do=[{"op": "level", "price": 130.0, "title": "x"}])]), FLAT)


def test_a_level_on_the_chart_compiles():
    out = lc.compile_lesson(lesson([step(do=[{"op": "level", "price": 101.0, "title": "Avg"}])]), FLAT)
    assert out["steps"][0]["do"] == [{"op": "level", "price": 101.0, "title": "Avg"}]


def test_a_frame_must_run_forwards():
    with pytest.raises(lc.LessonError, match="frame"):
        lc.compile_lesson(lesson([step(do=[{"op": "frame", "from": 5, "to": 2}])]), FLAT)


@pytest.mark.parametrize("bad", [{"op": "explode"}, {"op": "mark"}, {"op": "line", "a": {"bar": 0}}])
def test_unknown_or_incomplete_ops_are_errors(bad):
    with pytest.raises(lc.LessonError):
        lc.compile_lesson(lesson([step(do=[bad])]), FLAT)


# ------------------------------------------------------------------ the lesson itself
@pytest.mark.parametrize("field,value", [("id", "DCA-1"), ("who", "X"), ("say", ""), ("free", "yes")])
def test_malformed_lessons_are_errors(field, value):
    src = lesson([step()])
    if field in ("who", "say"):
        src["steps"][0][field] = value
    else:
        src[field] = value
    with pytest.raises(lc.LessonError):
        lc.compile_lesson(src, FLAT)


@pytest.mark.parametrize("line", [
    "This setup is a guarantee.", "Price will go up from here.", "You'll make money on this.",
    "Aim for 20% a month.", "It's risk-free.", "You can't lose.",
])
def test_the_honesty_lint_refuses_promises(line):
    with pytest.raises(lc.LessonError, match="honesty"):
        lc.compile_lesson(lesson([step(say=line)]), FLAT)


def test_the_honesty_lint_leaves_plain_teaching_alone():
    ok = "Price returned to the line, and the trade would lose if it closed above it."
    assert lc.compile_lesson(lesson([step(say=ok)]), FLAT)["steps"][0]["say"] == ok


def test_state_at_folds_marks_levels_and_clear():
    t = tape([100.0] * 9)
    src = lesson([step(do=[{"op": "seek", "bar": 2}, {"op": "mark", "bar": 1}]),
                  step(do=[{"op": "play", "to": 6}, {"op": "level", "price": 100.5, "title": "L"}]),
                  step(do=[{"op": "clear"}, {"op": "mark", "bar": 6}])])
    out = lc.compile_lesson(src, t)
    last = lc.state_at(out, 2)
    assert last["cursor_ts"] == t["ts"][6]
    assert [m["ts"] for m in last["marks"]] == [t["ts"][6]] and last["levels"] == []
    assert lc.state_at(out, 1)["levels"] == [{"price": 100.5, "title": "L"}]


# ------------------------------------------------------------------ end to end
def test_a_built_catalogue_is_what_the_server_serves(tmp_path):
    src = lesson([step(say="One.", do=[{"op": "seek", "bar": -1}]), step(say="Two.", who="Q")])
    fake_bake = lambda text, who: (b"ID3" + text.encode(), 1200)  # noqa: E731
    lc.build_all([src], {"t": FLAT}, {"dca": {"title": "DCA", "tagline": "Stop timing the market"}},
                 tmp_path, bake=fake_bake)
    m = class_catalog.load_manifest(tmp_path)
    assert class_catalog.public_catalog(m)[0]["lessons"] == [
        {"id": "dca-01", "title": "Same dollars", "free": True, "steps": 2}]
    body = class_catalog.lesson_body(m, "dca-01")
    assert [s["durMs"] for s in body["steps"]] == [1200, 1200]
    assert body["tape"]["ts"] == FLAT["ts"] and body["practice"]["symbol"] == "btc"
    assert class_catalog.audio_path(m, "dca-01", 1).read_bytes() == b"ID3Two."


def test_speech_fixes_change_the_voice_not_the_caption(tmp_path):
    heard = []
    lc.build_all([lesson([step(say="That line is your breakeven.")])], {"t": FLAT},
                 {"dca": {"title": "DCA"}}, tmp_path, bake=lambda text, who: heard.append(text) or (b"ID3", 900))
    assert heard == ["That line is your break even."]
    body = class_catalog.lesson_body(class_catalog.load_manifest(tmp_path), "dca-01")
    assert body["steps"][0]["say"] == "That line is your breakeven."


def test_stepping_one_at_a_time_matches_jumping_straight_there():
    t = tape([100.0] * 9)
    src = lesson([step(do=[{"op": "seek", "bar": 2}, {"op": "mark", "bar": 1}]),
                  step(do=[{"op": "play", "to": 6}, {"op": "line", "a": {"bar": 2}, "b": {"bar": 5}}]),
                  step(do=[{"op": "level", "price": 100.5, "title": "L"}])])
    out = lc.compile_lesson(src, t)
    for i in range(len(out["steps"])):
        again = [lc.state_at(out, j) for j in range(i + 1)][-1]      # step forward to i
        assert again == lc.state_at(out, i)                          # == jump straight to i
    assert lc.state_at(out, -1)["marks"] == [] and lc.state_at(out, -1)["cursor_ts"] == t["ts"][-1]


# ------------------------------------------------------------------ review regressions
def test_buys_after_rewinding_from_the_end_include_the_first_buy():
    # The real DCA-01 bug: open on the last bar, rewind to bar 0, drop buys -> bar 0 must be marked.
    t = tape([100.0] * 9)
    src = lesson([step(do=[{"op": "seek", "bar": -1}]),
                  step(do=[{"op": "seek", "bar": 0}, {"op": "buys", "var": "p"}]),
                  step(do=[{"op": "play", "to": -1}, {"op": "buys", "var": "p"}])],
                 vars={"p": {"fn": "dca", "every": 3, "start": 0}})
    marks = [o["ts"] for s in lc.compile_lesson(src, t)["steps"] for o in s["do"] if o["op"] == "mark"]
    assert marks == [t["ts"][0], t["ts"][3], t["ts"][6]]          # every buy exactly once


def test_clear_lets_buys_be_drawn_again():
    t = tape([100.0] * 4)
    src = lesson([step(do=[{"op": "seek", "bar": -1}, {"op": "buys", "var": "p"}]),
                  step(do=[{"op": "clear"}, {"op": "buys", "var": "p"}])],
                 vars={"p": {"fn": "dca", "every": 2, "start": 0}})
    out = lc.compile_lesson(src, t)
    assert [len([o for o in s["do"] if o["op"] == "mark"]) for s in out["steps"]] == [2, 2]


def test_play_backwards_is_an_error():
    with pytest.raises(lc.LessonError, match="backwards"):
        lc.compile_lesson(lesson([step(do=[{"op": "seek", "bar": 5}]), step(do=[{"op": "play", "to": 2}])]), FLAT)


def test_a_line_ending_past_the_cursor_is_an_error():
    with pytest.raises(lc.LessonError, match="not revealed"):
        lc.compile_lesson(lesson([step(do=[{"op": "seek", "bar": 3},
                                           {"op": "line", "a": {"bar": 1}, "b": {"bar": 7}}])]), FLAT)


def test_a_mark_at_an_explicit_price_off_the_chart_is_an_error():
    with pytest.raises(lc.LessonError, match="off the chart"):
        lc.compile_lesson(lesson([step(do=[{"op": "mark", "bar": 1, "price": 500.0}])]), FLAT)


def test_buys_needs_a_dca_plan():
    with pytest.raises(lc.LessonError, match="dca var"):
        lc.compile_lesson(lesson([step(do=[{"op": "buys", "var": "tape"}])]), FLAT)


@pytest.mark.parametrize("say", ["{tape.__class__}", "{tape._x}", "{p[0]}"])
def test_placeholders_cannot_reach_python_internals(say):
    with pytest.raises(lc.LessonError):
        lc.compile_lesson(lesson([step(say=say)], vars={"p": {"fn": "dca", "every": 1}}), FLAT)


@pytest.mark.parametrize("line", ["You’ll make it back.", "You can’t lose here.",
                                  "Double your money.", "There's no risk.", "It will definitely go up."])
def test_the_lint_sees_through_curly_apostrophes_and_new_phrasings(line):
    with pytest.raises(lc.LessonError, match="honesty"):
        lc.compile_lesson(lesson([step(say=line)]), FLAT)


@pytest.mark.parametrize("where", ["title", "level", "mark"])
def test_the_lint_covers_titles_and_chart_labels(where):
    bad = "Guaranteed gains"
    ops = {"level": [{"op": "level", "price": 100.0, "title": bad}],
           "mark": [{"op": "mark", "bar": 1, "dir": bad}], "title": []}[where]
    src = lesson([step(do=ops)])
    if where == "title":
        src["title"] = bad
    with pytest.raises(lc.LessonError, match="honesty"):
        lc.compile_lesson(src, FLAT)


@pytest.mark.parametrize("bad", [
    {"ts": [], "ohlc": []}, {"ts": [1, 2], "ohlc": [[1, 1, 1, 1]]}, {"ts": [2, 1], "ohlc": [[1, 1, 1, 1]] * 2},
    {"ts": [1, 2], "ohlc": [[1, 1, 1, None], [1, 1, 1, 1]]}, {"ohlc": []},
])
def test_a_broken_tape_is_an_error_not_a_crash(bad):
    with pytest.raises(lc.LessonError):
        lc.compile_lesson(lesson([step()]), bad)


def test_every_true_is_not_a_cadence():
    with pytest.raises(lc.LessonError):
        lc.compute_vars({"p": {"fn": "dca", "every": True}}, FLAT)


@pytest.mark.parametrize("field,value", [("class", "opt"), ("title", "  "), ("steps", [])])
def test_more_malformed_headers(field, value):
    src = lesson([step()])
    src[field] = value
    with pytest.raises(lc.LessonError):
        lc.compile_lesson(src, FLAT)


# ------------------------------------------------------------------ the build as a whole
def fake_bake(log=None):
    def bake(text, who):
        if log is not None:
            log.append(text)
        return b"ID3" + text.encode(), 1000
    return bake


META = {"dca": {"title": "DCA"}}


def test_nothing_is_written_when_any_lesson_fails(tmp_path):
    good, bad = lesson([step(say="Fine.")]), lesson([step(say="You'll make money.")], id="dca-02")
    with pytest.raises(lc.LessonError):
        lc.build_all([good, bad], {"t": FLAT}, META, tmp_path, bake=fake_bake())
    assert not any(tmp_path.rglob("*.json")) and not any(tmp_path.rglob("*.mp3"))


@pytest.mark.parametrize("case", ["duplicate", "unknown_class", "missing_tape", "empty"])
def test_build_level_checks(tmp_path, case):
    a = lesson([step()])
    sources = {"duplicate": [a, dict(a)],
               "unknown_class": [lesson([step()], id="opt-01", **{"class": "opt"})],
               "missing_tape": [lesson([step()], tape="nope")], "empty": []}[case]
    with pytest.raises(lc.LessonError):
        lc.build_all(sources, {"t": FLAT}, META, tmp_path, bake=fake_bake())


def test_a_rebuild_reuses_takes_and_rebakes_only_changed_lines(tmp_path):
    log = []
    lc.build_all([lesson([step(say="One."), step(say="Two.")])], {"t": FLAT}, META, tmp_path, bake=fake_bake(log))
    lc.build_all([lesson([step(say="One."), step(say="Two!")])], {"t": FLAT}, META, tmp_path, bake=fake_bake(log))
    assert log == ["One.", "Two.", "Two!"]
    assert len(list((tmp_path / "audio").glob("*.mp3"))) == 2          # the old "Two." take was pruned


def test_a_line_shared_by_two_lessons_is_one_file_and_survives_pruning(tmp_path):
    a, b = lesson([step(say="Same line.")]), lesson([step(say="Same line.")], id="dca-02")
    lc.build_all([a, b], {"t": FLAT}, META, tmp_path, bake=fake_bake())
    m = class_catalog.load_manifest(tmp_path)
    assert class_catalog.audio_path(m, "dca-01", 0) == class_catalog.audio_path(m, "dca-02", 0)
    assert class_catalog.audio_path(m, "dca-01", 0).is_file()


def test_a_new_voice_key_rebakes_everything(tmp_path):
    log = []
    lc.build_all([lesson([step(say="One.")])], {"t": FLAT}, META, tmp_path, bake=fake_bake(log), voice_key="a")
    lc.build_all([lesson([step(say="One.")])], {"t": FLAT}, META, tmp_path, bake=fake_bake(log), voice_key="b")
    assert log == ["One.", "One."]
