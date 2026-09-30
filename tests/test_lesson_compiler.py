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
        {"id": "dca-01", "title": "Same dollars", "free": True, "steps": 2, "seconds": 3}]
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


# ------------------------------------------------------------------ teaching the app itself
def test_a_spotlight_names_a_real_app_tool():
    out = lc.compile_lesson(lesson([step(do=[{"op": "spot", "tool": "fit", "label": "Fit shows the whole year"}])]), FLAT)
    assert out["steps"][0]["do"] == [{"op": "spot", "tool": "fit", "label": "Fit shows the whole year"}]
    assert lc.state_at(out, 0)["marks"] == []           # a spotlight is not a drawing: it never folds forward


@pytest.mark.parametrize("bad", [{"op": "spot", "tool": "#ltcFit"}, {"op": "spot", "tool": "hack"},
                                 {"op": "spot", "tool": "fit", "label": "Guaranteed winner"}])
def test_a_spotlight_must_be_a_known_tool_with_an_honest_label(bad):
    with pytest.raises(lc.LessonError):
        lc.compile_lesson(lesson([step(do=[bad])]), FLAT)


# ------------------------------------------------------------------ the app's own DCA engine
def test_wizard_numbers_are_the_dca_wizards_own():
    # A lesson must quote what the DCA Wizard would show the student, costs included.
    sys.path.insert(0, str(ROOT))
    import dca
    t = tape([100.0, 80.0, 60.0, 90.0, 120.0, 110.0] * 12)
    w = lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}}, t)["w"]
    dates = [str(x) for x in t["ts"]]
    closes = [row[3] for row in t["ohlc"]]
    per = dca.per_period_amount(100, "weekly")
    plain = dca.simulate_dca(dates, closes, "crypto", per, "weekly", "plain")
    tilt = dca.simulate_dca(dates, closes, "crypto", per, "weekly", "tilt")
    lump = dca.simulate_lump(dates, closes, "crypto", plain["invested"])
    assert w.plain_avg == pytest.approx(plain["avg_cost"]) and w.plain_ret == pytest.approx(plain["return_pct"])
    assert w.tilt_ret == pytest.approx(tilt["return_pct"]) and w.lump_ret == pytest.approx(lump["return_pct"])
    assert w.periods == plain["periods"] and w.tilt_helped == (tilt["return_pct"] > plain["return_pct"])


def test_dca_at_is_the_running_average_at_that_bar():
    t = tape([100.0, 50.0, 100.0, 50.0, 100.0])
    at = lc.compute_vars({"a": {"fn": "dca_at", "every": 1, "start": 0, "bar": 1}}, t)["a"]
    assert at.n == 2 and at.avg == pytest.approx(2 / (1 / 100 + 1 / 50)) and at.price == 50.0
    assert at.gap_pct == pytest.approx((50.0 / at.avg - 1) * 100)


def test_the_dca_tab_can_be_spotlighted():
    out = lc.compile_lesson(lesson([step(do=[{"op": "spot", "tool": "dca_tab", "label": "Run your own plan"}])]), FLAT)
    assert out["steps"][0]["do"][0]["tool"] == "dca_tab"


def test_dca_at_says_when_and_how_far_below():
    t = tape([100.0, 50.0])
    at = lc.compute_vars({"a": {"fn": "dca_at", "every": 1, "start": 0, "bar": 1}}, t)["a"]
    assert at.gap_abs == pytest.approx(-at.gap_pct) and at.date == lc._date(t["ts"][1])


def test_speech_says_letters_and_index_names_the_caption_keeps():
    assert lc.speech("The DCA class on the S&P 500.") == "The D C A class on the S and P five hundred."
    assert lc.speech("DCAs") == "DCAs"            # whole word only


def test_speech_spells_the_chart_acronyms():
    assert lc.speech("SPY with the EMA and the TTM squeeze.") == "S P Y with the E M A and the T T M squeeze."
    assert lc.speech("SPYX EMAs TTMs") == "SPYX EMAs TTMs"   # whole word only


def test_every_spotlight_tool_has_a_control_to_ring():
    """A tool the compiler accepts but the player can't find rings thin air: the
    step plays, the student hears "tap here", and nothing is highlighted."""
    import re
    player = (ROOT / "static" / "lesson-player.js").read_text(encoding="utf-8")
    block = re.search(r"LESSON_TOOL_SELECTORS = new Map\(Object\.entries\(\{(.*?)\}\)\);", player, re.S)
    assert block, "LESSON_TOOL_SELECTORS not found in lesson-player.js"
    keys = set(re.findall(r"([a-z_]+):\s*['\"]", block.group(1)))
    assert lc.TOOLS - keys == set(), f"tools with no selector: {sorted(lc.TOOLS - keys)}"
    assert keys - lc.TOOLS == set(), f"selectors the compiler would refuse: {sorted(keys - lc.TOOLS)}"


# ------------------------------------------------------------------ windows on a long tape
def test_a_dca_plan_can_stop_at_an_end_bar():
    # A multi-year tape holds several stories; a plan covers one window of it.
    t = tape([100.0] * 10)
    plan = lc.compute_vars({"p": {"fn": "dca", "every": 2, "start": 2, "end": 6}}, t)["p"]
    assert [b["bar"] for b in plan.buys] == [2, 4, 6] and plan.n == 3


def test_a_dca_window_knows_its_own_first_and_last_bar():
    t = tape([100.0, 50.0, 100.0, 200.0, 400.0])
    plan = lc.compute_vars({"p": {"fn": "dca", "every": 1, "start": 1, "end": 3}}, t)["p"]
    assert (plan.first_price, plan.last_price) == (50.0, 200.0)
    assert (plan.first_date, plan.last_date) == (lc._date(t["ts"][1]), lc._date(t["ts"][3]))
    assert plan.avg == pytest.approx(3 / (1 / 50 + 1 / 100 + 1 / 200))
    assert plan.gap_pct == pytest.approx((200.0 / plan.avg - 1) * 100)      # where price ended vs your line


def test_a_dca_window_that_ends_before_it_starts_is_an_error():
    with pytest.raises(lc.LessonError, match="end"):
        lc.compute_vars({"p": {"fn": "dca", "every": 1, "start": 5, "end": 2}}, FLAT)


def test_a_wizard_window_is_the_wizard_run_on_just_those_bars():
    closes = [100.0, 80.0, 60.0, 90.0, 120.0, 110.0] * 12
    whole = tape(closes)
    part = {**whole, **{k: whole[k][6:42] for k in ("ts", "ohlc", "volume")}}     # the same days, cut out
    spec = {"fn": "wizard", "monthly": 100, "cadence": "weekly"}
    win = lc.compute_vars({"w": {**spec, "start": 6, "end": 41}}, whole)["w"]
    alone = lc.compute_vars({"w": spec}, part)["w"]
    bars = ("tilt_min_bar", "tilt_max_bar")                      # bar numbers are the long tape's own
    assert {k: v for k, v in vars(win).items() if k not in bars} ==            {k: v for k, v in vars(alone).items() if k not in bars}
    assert all(getattr(win, k) == getattr(alone, k) + 6 for k in bars if hasattr(alone, k))
    assert [hasattr(win, k) for k in bars] == [hasattr(alone, k) for k in bars]
    assert win.periods < lc.compute_vars({"w": spec}, whole)["w"].periods     # it really is the window


def test_a_wizard_window_outside_the_tape_is_an_error():
    with pytest.raises(lc.LessonError, match="outside the tape"):
        lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "start": 0, "end": 99}}, FLAT)


# ------------------------------------------------------------------ a class we sell is a full class
def long_bake(ms):
    return lambda text, who: (b"ID3" + text.encode(), ms)


def test_a_short_lesson_in_a_class_with_paid_lessons_stops_the_build(tmp_path):
    # The real miss (09-30): ten lessons of ~90 s went on sale as a $19/mo class.
    free, paid = lesson([step(say="One.")]), lesson([step(say="Two.")], id="dca-02", free=False)
    with pytest.raises(lc.LessonError, match=r"dca-01 runs 0:01.*8:00"):
        lc.build_all([free, paid], {"t": FLAT}, META, tmp_path, bake=fake_bake())
    assert not (tmp_path / "catalog.json").exists() and not list(tmp_path.glob("dca-*.json"))


def test_a_full_length_paid_class_builds(tmp_path):
    free, paid = lesson([step(say="One.")]), lesson([step(say="Two.")], id="dca-02", free=False)
    lc.build_all([free, paid], {"t": FLAT}, META, tmp_path, bake=long_bake(lc.MIN_PAID_CLASS_LESSON_S * 1000))
    assert (tmp_path / "catalog.json").is_file()


def test_a_class_that_is_all_free_may_be_short(tmp_path):
    lc.build_all([lesson([step()])], {"t": FLAT}, META, tmp_path, bake=fake_bake())
    assert (tmp_path / "catalog.json").is_file()


def test_a_lessons_running_time_counts_the_breath_between_steps():
    built = {"steps": [{"durMs": 1000}, {"durMs": 2000}, {"durMs": 3000}]}
    assert lc.lesson_seconds(built) == pytest.approx((6000 + 2 * lc.STEP_GAP_MS) / 1000)


def test_the_step_gap_is_the_players_own():
    import re
    player = (ROOT / "static" / "lesson-player.js").read_text(encoding="utf-8")
    gap = re.search(r"const LESSON_GAP_MS = (\d+);", player)
    assert gap and int(gap.group(1)) == lc.STEP_GAP_MS


def test_the_catalogue_says_how_long_each_lesson_runs(tmp_path):
    src = lesson([step(say="One."), step(say="Two.")])
    lc.build_all([src], {"t": FLAT}, META, tmp_path, bake=long_bake(60_000))
    shown = class_catalog.public_catalog(class_catalog.load_manifest(tmp_path))[0]["lessons"][0]
    assert shown["seconds"] == round(lc.lesson_seconds({"steps": [{"durMs": 60_000}] * 2}))


@pytest.mark.parametrize("bad", [-5, "600", True, None, 1.5e9])
def test_a_nonsense_running_time_in_the_manifest_reads_as_unknown(tmp_path, bad):
    lc.build_all([lesson([step()])], {"t": FLAT}, META, tmp_path, bake=fake_bake())
    cat = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    cat["classes"][0]["lessons"][0]["seconds"] = bad
    (tmp_path / "catalog.json").write_text(json.dumps(cat), encoding="utf-8")
    assert class_catalog.public_catalog(class_catalog.load_manifest(tmp_path))[0]["lessons"][0]["seconds"] == 0


# ------------------------------------------------------------------ the stories a long lesson tells
def test_a_bar_var_reads_one_candle_and_what_100_dollars_buys_there():
    t = tape([100.0, 50.0])
    b = lc.compute_vars({"b": {"fn": "bar", "bar": 1}}, t)["b"]
    assert (b.close, b.high, b.low) == (50.0, 50.5, 49.5) and b.date == lc._date(t["ts"][1])
    assert b.per_100 == pytest.approx(2.0) and b.bar == 1


def test_underwater_finds_the_worst_day_and_the_day_price_came_back():
    # Running averages: 100, 66.67, 60, 66.67, 76.92 -> below the line on bars 1 and 2, worst on bar 1.
    t = tape([100.0, 50.0, 50.0, 100.0, 200.0])
    u = lc.compute_vars({"u": {"fn": "underwater", "every": 1, "start": 0}}, t)["u"]
    assert u.worst_bar == 1 and u.worst_gap == pytest.approx(25.0) and u.worst_n == 2
    assert u.worst_avg == pytest.approx(2 / (1 / 100 + 1 / 50)) and u.worst_price == 50.0
    assert (u.days_below, u.days, u.back_bar, u.back_date) == (2, 5, 3, lc._date(t["ts"][3]))
    # The all-at-once buyer at bar 0 paid 100: under water on the same two bars here.
    assert (u.lump_days_below, u.lump_back_bar, u.lump_worst) == (2, 3, pytest.approx(50.0))


def test_a_plan_still_under_water_at_the_end_has_no_comeback_to_narrate():
    t = tape([100.0, 50.0, 40.0])
    src = lesson([step(say="Back above the line on {u.back_date}.")],
                 vars={"u": {"fn": "underwater", "every": 1, "start": 0}})
    with pytest.raises(lc.LessonError, match="placeholder"):
        lc.compile_lesson(src, t)                       # a date that never happened can't be spoken
    u = lc.compute_vars({"u": {"fn": "underwater", "every": 1, "start": 0}}, t)["u"]
    assert u.days_below == 2 and not hasattr(u, "back_bar") and not hasattr(u, "lump_back_bar")


def test_a_plan_never_below_its_line_has_no_worst_day_to_narrate():
    u = lc.compute_vars({"u": {"fn": "underwater", "every": 1, "start": 0}}, tape([100.0, 110.0, 120.0]))["u"]
    assert u.days_below == 0 and not hasattr(u, "worst_bar")


def test_rolling_counts_how_often_each_plan_won_across_every_window():
    closes = [100.0 + 3 * i for i in range(60)] + [277.0 - 4 * i for i in range(60)]     # up, then down
    t = tape(closes)
    spec = {"monthly": 100, "cadence": "weekly"}
    r = lc.compute_vars({"r": {"fn": "rolling", **spec, "span": 28, "step": 7}}, t)["r"]
    each = [lc.compute_vars({"w": {"fn": "wizard", **spec, "start": s, "end": s + 28}}, t)["w"]
            for s in range(0, len(closes) - 28, 7)]
    assert r.windows == len(each) and r.lump_won == sum(w.lump_won for w in each)
    assert 0 < r.lump_won < r.windows                            # it won going up, lost going down
    assert r.dca_won == r.windows - r.lump_won and r.tilt_helped == sum(w.tilt_helped for w in each)
    assert r.plain_worst == pytest.approx(min(w.plain_ret for w in each))
    assert r.lump_best == pytest.approx(max(w.lump_ret for w in each))


@pytest.mark.parametrize("bad", [{"span": 0}, {"step": 0}, {"span": 500}, {"span": True}])
def test_rolling_needs_a_window_that_fits_the_tape(bad):
    spec = {"fn": "rolling", "monthly": 100, "cadence": "weekly", "span": 5, "step": 1, **bad}
    with pytest.raises(lc.LessonError, match="rolling"):
        lc.compute_vars({"r": spec}, FLAT)


def test_shift_shows_how_little_the_starting_day_moves_the_average():
    closes = [100.0, 80.0, 60.0, 90.0, 120.0, 110.0] * 10
    t = tape(closes)
    s = lc.compute_vars({"s": {"fn": "shift", "every": 6, "start": 0, "end": 53, "days": 6}}, t)["s"]
    avgs = [lc.compute_vars({"p": {"fn": "dca", "every": 6, "start": k, "end": 53}}, t)["p"].avg for k in range(6)]
    assert (s.lo_avg, s.hi_avg) == (pytest.approx(min(avgs)), pytest.approx(max(avgs)))
    assert s.spread_pct == pytest.approx((max(avgs) / min(avgs) - 1) * 100)
    assert (s.price_lo, s.price_hi) == (60.0, 120.0)


def test_a_drawing_can_sit_on_a_computed_bar_so_chart_and_narration_cannot_drift():
    t = tape([100.0, 50.0, 50.0, 100.0, 200.0])
    src = lesson([step(say="The worst day was {u.worst_date}.",
                       do=[{"op": "seek", "bar": -1}, {"op": "mark", "bar": "u.worst_bar", "dir": "low"}])],
                 vars={"u": {"fn": "underwater", "every": 1, "start": 0}})
    assert lc.compile_lesson(src, t)["steps"][0]["do"][1]["ts"] == t["ts"][1]


@pytest.mark.parametrize("ref", ["u.worst_gap", "u.nope", "nope.bar", "u.worst_date"])
def test_a_computed_bar_must_be_a_whole_bar_number(ref):
    t = tape([100.0, 50.0, 50.0, 100.0, 200.0])
    src = lesson([step(do=[{"op": "seek", "bar": ref}])], vars={"u": {"fn": "underwater", "every": 1, "start": 0}})
    with pytest.raises(lc.LessonError):
        lc.compile_lesson(src, t)


# ------------------------------------------------------------------ words that follow the data
def test_a_plan_names_its_cheapest_and_priciest_buy():
    t = tape([100.0, 50.0, 200.0, 80.0])
    p = lc.compute_vars({"p": {"fn": "dca", "every": 1, "start": 0}}, t)["p"]
    assert (p.cheapest_bar, p.cheapest_price, p.cheapest_date) == (1, 50.0, lc._date(t["ts"][1]))
    assert (p.priciest_bar, p.priciest_price) == (2, 200.0)
    assert p.coin_ratio == pytest.approx(4.0)            # the same dollars bought 4x the coin at the low


def test_up_and_down_are_chosen_by_the_numbers_not_the_author():
    rising, falling = tape([100.0 + i for i in range(60)]), tape([200.0 - i for i in range(60)])
    spec = {"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}, "p": {"fn": "dca", "every": 7}}
    up, down = lc.compute_vars(spec, rising), lc.compute_vars(spec, falling)
    assert (up["w"].lump_dir, down["w"].lump_dir) == ("up", "down")
    assert (up["w"].plain_dir, down["w"].plain_dir) == ("up", "down")
    assert down["w"].lump_abs == pytest.approx(-down["w"].lump_ret) and up["w"].plain_abs == pytest.approx(up["w"].plain_ret)
    assert down["w"].tilt_abs == pytest.approx(abs(down["w"].tilt_ret)) and down["w"].tilt_dir == "down"
    assert (up["p"].side, down["p"].side) == ("above", "below")
    assert down["p"].gap_abs == pytest.approx(-down["p"].gap_pct)


def test_the_wizard_says_which_plan_finished_ahead():
    rising, falling = tape([100.0 + i for i in range(60)]), tape([200.0 - i for i in range(60)])
    spec = {"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}}
    assert lc.compute_vars(spec, rising)["w"].winner == "all at once"
    assert lc.compute_vars(spec, falling)["w"].winner == "the schedule"
    w = lc.compute_vars(spec, rising)["w"]
    assert w.lead == pytest.approx(abs(w.lump_ret - w.plain_ret))


def test_dca_at_says_which_side_of_the_line_price_sat():
    at = lc.compute_vars({"a": {"fn": "dca_at", "every": 1, "start": 0, "bar": 1}}, tape([100.0, 50.0]))["a"]
    assert at.side == "below"


def test_rolling_ranges_are_spoken_as_a_gain_or_a_loss_never_a_minus_sign():
    closes = [100.0 + 3 * i for i in range(60)] + [277.0 - 4 * i for i in range(60)]
    r = lc.compute_vars({"r": {"fn": "rolling", "monthly": 100, "cadence": "weekly", "span": 28, "step": 7}},
                        tape(closes))["r"]
    assert r.lump_worst < 0 < r.lump_best
    assert r.lump_worst_say == f"a loss of {abs(r.lump_worst):.0f} percent"
    assert r.lump_best_say == f"a gain of {r.lump_best:.0f} percent"
    assert r.plain_worst_say.startswith("a loss of ") and r.plain_best_say.startswith("a gain of ")


def test_underwater_also_knows_the_first_day_price_touched_the_line_again():
    # Line: 100, 66.67, 60, 63.16, 61.22, 65.45 -> below on bars 1-2, above on 3, below again on 4, back for good on 5.
    t = tape([100.0, 50.0, 50.0, 75.0, 55.0, 120.0])
    u = lc.compute_vars({"u": {"fn": "underwater", "every": 1, "start": 0}}, t)["u"]
    assert (u.first_back_bar, u.back_bar) == (3, 5) and u.first_back_date == lc._date(t["ts"][3])
    assert u.lump_first_back_bar == 5 == u.lump_back_bar            # the all-at-once buyer paid 100


def test_dca_at_says_how_far_price_must_rise_to_reach_each_buyers_price():
    t = tape([100.0, 50.0, 25.0])
    at = lc.compute_vars({"a": {"fn": "dca_at", "every": 1, "start": 0, "bar": 2}}, t)["a"]
    avg = 3 / (1 / 100 + 1 / 50 + 1 / 25)
    assert at.need_pct == pytest.approx((avg / 25 - 1) * 100)       # back to your average cost
    assert at.lump_need_pct == pytest.approx(300.0)                 # back to the day-one price
    assert at.lump_gap_abs == pytest.approx(75.0) and at.lump_side == "below" and at.lump_price == 100.0


def test_underwater_names_the_longest_unbroken_stretch_below_the_line():
    # Below on bar 1, above on 2, below on 3-5, above from 6: the long stretch is bars 3..5, over on bar 6.
    t = tape([100.0, 50.0, 90.0, 40.0, 40.0, 40.0, 150.0])
    u = lc.compute_vars({"u": {"fn": "underwater", "every": 1, "start": 0}}, t)["u"]
    assert (u.longest_days, u.longest_from_bar, u.longest_to_bar, u.longest_after_bar) == (3, 3, 5, 6)
    assert (u.longest_from_date, u.longest_after_date) == (lc._date(t["ts"][3]), lc._date(t["ts"][6]))


def test_a_longest_stretch_that_runs_to_the_end_has_no_day_after():
    u = lc.compute_vars({"u": {"fn": "underwater", "every": 1, "start": 0}}, tape([100.0, 50.0, 40.0]))["u"]
    assert u.longest_days == 2 and not hasattr(u, "longest_after_bar")


# ------------------------------------------------------------------ costs and where the tilt leaned
def test_the_wizard_reports_what_each_buy_costs_in_fees():
    sys.path.insert(0, str(ROOT))
    import backtest
    t = tape([100.0 + i for i in range(60)])
    spec = {"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}}
    for kind in ("crypto", "stock"):
        w = lc.compute_vars(spec, dict(t, kind=kind))["w"]
        assert w.cost_pct == pytest.approx(sum(backtest.cost_model(kind)) * 100)
    assert lc.compute_vars(spec, t)["w"].cost_pct > lc.compute_vars(spec, dict(t, kind="stock"))["w"].cost_pct


def test_the_wizard_shows_which_buys_the_tilt_boosted_and_which_it_trimmed():
    sys.path.insert(0, str(ROOT))
    import dca
    closes = [100.0 + 20 * ((i // 25) % 2) + (i % 25) * (1 if (i // 25) % 2 == 0 else -1) for i in range(400)]
    t = tape(closes)
    w = lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}}, t)["w"]
    buys = dca.simulate_dca([str(x) for x in t["ts"]], closes, "crypto", dca.per_period_amount(100, "weekly"),
                            "weekly", "tilt")["contributions"]
    more, less = [b for b in buys if b["tilt"] > 1], [b for b in buys if b["tilt"] < 1]
    assert more and less, "the fixture must tilt both ways"
    assert (w.tilt_more, w.tilt_less, w.tilt_even) == (len(more), len(less), len(buys) - len(more) - len(less))
    assert w.tilt_more_price == pytest.approx(sum(b["price"] for b in more) / len(more))
    assert w.tilt_less_price == pytest.approx(sum(b["price"] for b in less) / len(less))
    small = min(buys, key=lambda b: (b["tilt"], b["price"]))
    big = max(buys, key=lambda b: (b["tilt"], b["price"]))
    assert (w.tilt_min_mult, w.tilt_min_price, w.tilt_min_amount) == (small["tilt"], small["price"], small["amount"])
    assert (w.tilt_max_mult, w.tilt_max_price, w.tilt_max_amount) == (big["tilt"], big["price"], big["amount"])
    assert t["ts"][w.tilt_min_bar] == int(small["date"]) and w.tilt_min_date == lc._date(int(small["date"]))
    assert t["ts"][w.tilt_max_bar] == int(big["date"])


def test_a_tilt_window_sits_on_the_right_bars_of_the_long_tape():
    closes = [100.0 + 20 * ((i // 25) % 2) + (i % 25) * (1 if (i // 25) % 2 == 0 else -1) for i in range(400)]
    t = tape(closes)
    w = lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly", "start": 100, "end": 399}}, t)["w"]
    # The fixture repeats every 50 bars, so a price match alone would pass for bar - 100 too:
    # the DATE must be the long tape's own day.
    assert 100 <= w.tilt_min_bar <= 399 and closes[w.tilt_min_bar] == w.tilt_min_price
    assert w.tilt_min_date == lc._date(t["ts"][w.tilt_min_bar])
    alone = lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}},
                            {**t, **{k: t[k][100:] for k in ("ts", "ohlc", "volume")}})["w"]
    assert w.tilt_min_bar == alone.tilt_min_bar + 100


# ------------------------------------------------------------------ review regressions (09-30)
def test_a_buy_day_sits_on_the_line_not_below_it():
    # 1/(1/p) is not always exactly p: float dust must not put the word "below" in a lesson.
    t = tape([11.571428571428571, 12.0])
    at = lc.compute_vars({"a": {"fn": "dca_at", "every": 7, "start": 0, "bar": 0}}, t)["a"]
    assert at.side == "above" and at.gap_abs < 1e-9
    assert lc.compute_vars({"p": {"fn": "dca", "every": 7, "start": 0, "end": 0}}, t)["p"].side == "above"


@pytest.mark.parametrize("extra", [{"start": 2}, {"end": 8}])
def test_rolling_covers_the_whole_tape_and_refuses_a_window_it_would_ignore(extra):
    spec = {"fn": "rolling", "monthly": 100, "cadence": "weekly", "span": 5, "step": 1, **extra}
    with pytest.raises(lc.LessonError, match="rolling"):
        lc.compute_vars({"r": spec}, FLAT)


def test_a_tilt_identical_to_plain_has_no_lead_to_narrate():
    # Inside the indicator warm-up every tilted buy is the plain amount: nothing is "behind".
    w = lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}},
                        tape([100.0 + (i % 7) for i in range(40)]))["w"]
    assert w.tilt_ret == w.plain_ret
    assert not hasattr(w, "tilt_word") and not hasattr(w, "tilt_lead")
    assert (w.tilt_more, w.tilt_less) == (0, 0)
    assert not hasattr(w, "tilt_min_bar") and not hasattr(w, "tilt_max_bar")    # nothing was trimmed or boosted


def test_plans_that_tie_have_no_winner_to_narrate():
    w = lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}}, tape([100.0] * 60))["w"]
    assert w.lump_ret == w.plain_ret and not hasattr(w, "winner") and not hasattr(w, "lead")
    r = lc.compute_vars({"r": {"fn": "rolling", "monthly": 100, "cadence": "weekly", "span": 28, "step": 7}},
                        tape([100.0] * 60))["r"]
    assert (r.lump_won, r.dca_won, r.ties) == (0, 0, r.windows)


def test_the_climb_back_is_only_stated_when_there_is_one():
    at = lc.compute_vars({"a": {"fn": "dca_at", "every": 1, "start": 0, "bar": 1}}, tape([100.0, 150.0]))["a"]
    assert not hasattr(at, "need_pct") and not hasattr(at, "lump_need_pct")
    u = lc.compute_vars({"u": {"fn": "underwater", "every": 1, "start": 0}}, tape([100.0, 110.0, 120.0]))["u"]
    assert not hasattr(u, "lump_worst")                        # the all-at-once buyer was never under water


@pytest.mark.parametrize("ref", ["u.days_below", "u.days", "u.worst_n"])
def test_a_computed_bar_must_be_named_as_a_bar(ref):
    # A typo like u.days instead of u.worst_bar is a whole number too: it must not seek "bar 5".
    t = tape([100.0, 50.0, 50.0, 100.0, 200.0])
    src = lesson([step(do=[{"op": "seek", "bar": ref}])], vars={"u": {"fn": "underwater", "every": 1, "start": 0}})
    with pytest.raises(lc.LessonError, match="bar"):
        lc.compile_lesson(src, t)


@pytest.mark.parametrize("monthly", [0.001, float("nan"), float("inf")])
def test_a_wizard_budget_too_small_or_not_a_number_is_a_lesson_error(monthly):
    with pytest.raises(lc.LessonError, match="wizard"):
        lc.compute_vars({"w": {"fn": "wizard", "monthly": monthly, "cadence": "weekly"}}, tape([100.0] * 60))


def test_a_rolling_range_that_rounds_to_nothing_is_not_called_a_loss():
    assert lc._pct_say(-0.4) == "no change" and lc._pct_say(0.4) == "no change"
    assert lc._pct_say(-0.6) == "a loss of 1 percent" and lc._pct_say(12.4) == "a gain of 12 percent"


def test_the_tilt_says_how_many_buys_share_its_smallest_size():
    sys.path.insert(0, str(ROOT))
    import dca
    closes = [100.0 + 20 * ((i // 25) % 2) + (i % 25) * (1 if (i // 25) % 2 == 0 else -1) for i in range(400)]
    t = tape(closes)
    w = lc.compute_vars({"w": {"fn": "wizard", "monthly": 100, "cadence": "weekly"}}, t)["w"]
    buys = dca.simulate_dca([str(x) for x in t["ts"]], closes, "crypto", dca.per_period_amount(100, "weekly"),
                            "weekly", "tilt")["contributions"]
    assert w.tilt_min_count == sum(b["tilt"] == w.tilt_min_mult for b in buys)
    assert w.tilt_max_count == sum(b["tilt"] == w.tilt_max_mult for b in buys)


# ------------------------------------------------------------------ the frame is what the viewer sees
def test_the_cursor_must_stay_inside_the_frame():
    # The player shows the framed bars only: a cursor outside them plays to an empty chart.
    for bar in (8, 0):
        with pytest.raises(lc.LessonError, match="frame"):
            lc.compile_lesson(lesson([step(do=[{"op": "frame", "from": 2, "to": 5}, {"op": "seek", "bar": bar}])]), FLAT)


def test_a_later_step_cannot_walk_out_of_the_frame():
    src = lesson([step(do=[{"op": "frame", "from": 2, "to": 5}, {"op": "seek", "bar": 3}]),
                  step(do=[{"op": "play", "to": 8}])])
    with pytest.raises(lc.LessonError, match="step 1.*frame"):
        lc.compile_lesson(src, FLAT)


def test_a_drawing_outside_the_framed_bars_is_an_error():
    # Found by LOOKING (09-30): a "2022 low" mark compiled fine and sat off the left edge of the screen.
    src = lesson([step(do=[{"op": "frame", "from": 4, "to": 9}, {"op": "seek", "bar": 9}, {"op": "mark", "bar": 1}])])
    with pytest.raises(lc.LessonError, match="frame"):
        lc.compile_lesson(src, FLAT)


def test_a_drawing_is_checked_against_the_frame_its_own_step_ends_on():
    # Like the cursor: the step's FINAL frame is what is on screen when the drawing shows.
    src = lesson([step(do=[{"op": "seek", "bar": 9}, {"op": "mark", "bar": 5}, {"op": "frame", "from": 4, "to": 9}])])
    assert lc.compile_lesson(src, FLAT)["steps"][0]["do"][1]["ts"] == FLAT["ts"][5]
    src = lesson([step(do=[{"op": "seek", "bar": 9}, {"op": "mark", "bar": 1}, {"op": "frame", "from": 4, "to": 9}])])
    with pytest.raises(lc.LessonError, match="frame"):
        lc.compile_lesson(src, FLAT)


def test_a_lesson_cannot_outgrow_the_servers_request_budget():
    # The player fetches one narration clip per step before it starts. The hourly budgets in
    # app.py are sized for MAX_LESSON_STEPS, so a longer lesson must be a decision, not a drift.
    lc.compile_lesson(lesson([step()] * lc.MAX_LESSON_STEPS), FLAT)
    with pytest.raises(lc.LessonError, match="steps"):
        lc.compile_lesson(lesson([step()] * (lc.MAX_LESSON_STEPS + 1)), FLAT)


# ------------------------------------------------------------------ a full-length class, sold or free
FULL = {"dca": {"title": "DCA", "min_minutes": 8}}


def test_a_free_class_declared_full_length_is_held_to_it(tmp_path):
    # The owner made the classes free (09-30). Free is not a licence to be short.
    with pytest.raises(lc.LessonError, match=r"dca-01 runs 0:01.*8:00"):
        lc.build_all([lesson([step()])], {"t": FLAT}, FULL, tmp_path, bake=fake_bake())
    assert not (tmp_path / "catalog.json").exists()
    # A new line, so the short take above is not reused: the same words would keep their length.
    lc.build_all([lesson([step(say="A full lesson.")])], {"t": FLAT}, FULL, tmp_path, bake=long_bake(480_000))
    assert (tmp_path / "catalog.json").is_file()


def test_a_declared_length_cannot_undercut_the_floor_of_a_class_for_sale(tmp_path):
    meta = {"dca": {"title": "DCA", "min_minutes": 1}}
    free, paid = lesson([step(say="One.")]), lesson([step(say="Two.")], id="dca-02", free=False)
    with pytest.raises(lc.LessonError, match="8:00"):
        lc.build_all([free, paid], {"t": FLAT}, meta, tmp_path, bake=long_bake(100_000))


@pytest.mark.parametrize("bad", [-1, "8", True, float("nan"), 600])
def test_a_nonsense_declared_length_stops_the_build(tmp_path, bad):
    with pytest.raises(lc.LessonError, match="min_minutes"):
        lc.build_all([lesson([step()])], {"t": FLAT}, {"dca": {"title": "DCA", "min_minutes": bad}}, tmp_path,
                     bake=fake_bake())


# ------------------------------------------------------------------ the Para-Sail strategy (owner 2026-09-30)
# Shop the low: buy one fill when the close sits within `zone` of the lowest close of the last `low_days`
# calendar days, at most once every `gap_days`. Para-sail: once the open position is up `sail_at` on what it
# cost, sell `sell` of it — once per wave; the next buy re-arms it. Cap: never more than `cap` of your own
# money in (money in minus money taken out). hold: never sell (BTC is held, not para-sailed).
def _side():
    sys.path.insert(0, str(ROOT))
    import backtest
    return sum(backtest.cost_model("crypto"))


ZONE_TAPE = tape([100.0, 110.0, 120.0, 104.0, 130.0, 99.0, 106.0])
SAIL_TAPE = tape([100.0, 120.0, 150.0, 160.0, 170.0, 90.0, 95.0, 200.0])
PS = {"fn": "parasail", "low_days": 3, "zone": 0.08, "gap_days": 1, "fill": 100, "cap": 10_000}


def test_parasail_buys_only_inside_the_zone_of_the_trailing_low():
    p = lc.compute_vars({"p": PS}, ZONE_TAPE)["p"]
    # bar 3: low of the last 3 days is 104, the close IS the low -> buy; bar 4's 130 sits far above it.
    assert [b["bar"] for b in p.buys] == [0, 3, 5, 6]
    assert all(b["price"] == ZONE_TAPE["ohlc"][b["bar"]][3] for b in p.buys)


def test_parasail_fills_at_most_once_every_gap_days():
    flat = tape([100.0] * 20)
    p = lc.compute_vars({"p": {**PS, "gap_days": 7}}, flat)["p"]
    assert [b["bar"] for b in p.buys] == [0, 7, 14]


def test_parasail_sells_half_at_plus_40_once_per_wave_and_the_next_buy_rearms_it():
    p = lc.compute_vars({"p": PS}, SAIL_TAPE)["p"]
    assert [b["bar"] for b in p.buys] == [0, 5, 6]
    # bar 2 (150) is the first +40 %; 160 and 170 are higher but the wave already sailed; 200 comes after re-arming.
    assert [s["bar"] for s in p.sails] == [2, 7]
    assert p.n_sails == 2 and p.first_sail_bar == 2 and p.first_sail_price == 150.0


def test_parasail_counts_profit_after_costs_against_the_most_money_ever_in():
    s = _side()
    p = lc.compute_vars({"p": PS}, SAIL_TAPE)["p"]
    units = 100 * (1 - s) / 100                          # bar 0 buy
    sold1 = units / 2 * 150 * (1 - s)                    # bar 2 sail: half out
    units /= 2
    units += 100 * (1 - s) / 90 + 100 * (1 - s) / 95     # bars 5 and 6
    sold2 = units / 2 * 200 * (1 - s)                    # bar 7 sail
    units /= 2
    net_path = [100, 100 - sold1, 200 - sold1, 300 - sold1, 300 - sold1 - sold2]
    assert p.invested == 300
    assert p.peak == pytest.approx(max(net_path))
    assert p.proceeds == pytest.approx(sold1 + sold2)
    assert p.value == pytest.approx(units * 200)
    assert p.profit == pytest.approx(units * 200 - (300 - sold1 - sold2))
    assert p.roi == pytest.approx(p.profit / p.peak * 100)
    assert p.profit_word == "profit" and p.profit_abs == pytest.approx(p.profit)


def test_parasail_reports_the_same_buys_held_without_selling():
    s = _side()
    p = lc.compute_vars({"p": PS}, SAIL_TAPE)["p"]
    held = sum(100 * (1 - s) / px for px in (100, 90, 95)) * 200
    assert p.hold_value == pytest.approx(held)
    assert p.hold_profit == pytest.approx(held - 300)
    assert p.hold_roi == pytest.approx((held - 300) / 300 * 100)


def test_hold_mode_never_sells_btc_is_held():
    p = lc.compute_vars({"p": {**PS, "hold": True}}, SAIL_TAPE)["p"]
    assert p.sails == [] and p.n_sails == 0
    assert p.profit == pytest.approx(p.hold_profit)
    assert not hasattr(p, "first_sail_bar")   # a sale that never happened has no value to narrate


def test_the_cap_stops_new_buys_and_names_the_day_it_bit():
    flat = tape([100.0] * 10)
    p = lc.compute_vars({"p": {**PS, "cap": 300}}, flat)["p"]
    assert [b["bar"] for b in p.buys] == [0, 1, 2]
    assert p.cap_bar == 3 and p.cap_date == lc._date(flat["ts"][3])


def test_a_para_sail_frees_room_under_the_cap():
    # cap 150: the bar-2 sale takes ~$75 back out, so bar 5's fill fits (~$125 in); bar 6's would make ~$225.
    p = lc.compute_vars({"p": {**PS, "cap": 150}}, SAIL_TAPE)["p"]
    assert [b["bar"] for b in p.buys] == [0, 5]
    assert p.cap_bar == 6
    # Held, nothing comes back out: bar 5 would make $200, so the cap bites there instead.
    held = lc.compute_vars({"p": {**PS, "cap": 150, "hold": True}}, SAIL_TAPE)["p"]
    assert [b["bar"] for b in held.buys] == [0]
    assert held.cap_bar == 5


@pytest.mark.parametrize("bad", [
    {"zone": 0}, {"zone": 1.5}, {"zone": True}, {"low_days": 0}, {"gap_days": 0}, {"fill": 0},
    {"cap": 50}, {"sail_at": 0}, {"sell": 0}, {"sell": 1.5}, {"hold": "yes"}, {"low_days": 2.5},
])
def test_a_nonsense_parasail_plan_stops_the_build(bad):
    with pytest.raises(lc.LessonError, match="parasail"):
        lc.compute_vars({"p": {**PS, **bad}}, SAIL_TAPE)


def test_sails_op_draws_each_sale_revealed_so_far_once_as_a_sell_mark():
    src = lesson([step(do=[{"op": "seek", "bar": 3}, {"op": "buys", "var": "p"}, {"op": "sails", "var": "p"}]),
                  step(do=[{"op": "play", "to": 7}, {"op": "sails", "var": "p"}])],
                 vars={"p": PS})
    out = lc.compile_lesson(src, SAIL_TAPE)
    first, second = out["steps"][0]["do"], out["steps"][1]["do"]
    assert [m for m in first if m.get("dir") == "buy"] == [
        {"op": "mark", "ts": SAIL_TAPE["ts"][0], "price": 100.0, "dir": "buy"}]
    assert [m for m in first if m.get("dir") == "sell"] == [
        {"op": "mark", "ts": SAIL_TAPE["ts"][2], "price": 150.0, "dir": "sell"}]
    assert [m for m in second if m.get("op") == "mark"] == [
        {"op": "mark", "ts": SAIL_TAPE["ts"][7], "price": 200.0, "dir": "sell"}]


def test_sails_needs_a_parasail_plan():
    src = lesson([step(do=[{"op": "sails", "var": "p"}])], vars={"p": {"fn": "dca", "every": 1}})
    with pytest.raises(lc.LessonError, match="sails needs a parasail var"):
        lc.compile_lesson(src, FLAT)


def test_zone_var_names_the_trailing_low_and_the_top_of_the_zone():
    z = lc.compute_vars({"z": {"fn": "zone", "bar": 3, "low_days": 3, "zone": 0.08}}, ZONE_TAPE)["z"]
    assert z.low == 104.0 and z.low_bar == 3 and z.top == pytest.approx(112.32)
    assert z.close == 104.0 and z.where == "inside"
    up = lc.compute_vars({"z": {"fn": "zone", "bar": 4, "low_days": 3, "zone": 0.08}}, ZONE_TAPE)["z"]
    assert up.where == "above" and up.above_pct == pytest.approx((130 / 112.32 - 1) * 100)


def test_a_para_sail_narration_reads_its_numbers_from_the_tape():
    src = lesson([step(say="{p.n} buys, {p.n_sails} para-sails, first at {p.first_sail_price:,.0f}.")],
                 vars={"p": PS})
    assert lc.compile_lesson(src, SAIL_TAPE)["steps"][0]["say"] == "3 buys, 2 para-sails, first at 150."
