"""The lesson player's pure engine (static/lesson-engine.js).

The compiler (tools/classes/lesson_compiler.py) decides what the chart looks
like after each step; the browser must show exactly that. So the JS fold is
tested against the Python fold on the same compiled lesson, step by step —
if they ever drift, the voice and the chart disagree.

Runs in Node's vm, same harness as test_chart_options.py.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
NODE = shutil.which("node")
sys.path.insert(0, os.path.join(ROOT, "tools", "classes"))

import lesson_compiler as lc  # noqa: E402

HARNESS = r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const ctx = { console, Math, Number, String, JSON, Array, Object, Set, isFinite };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(process.argv[1], "lesson-engine.js"), "utf8"), ctx,
                { filename: "lesson-engine.js" });
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(([fn, args]) => {
  try { return { ok: vm.runInContext(fn, ctx)(...args) }; }
  catch (e) { return { err: String(e && e.message || e) }; }
})));
"""


def run_js(cases):
    if not NODE:
        pytest.skip("node is not installed")
    proc = subprocess.run([NODE, "-e", HARNESS, STATIC], input=json.dumps(cases),
                          capture_output=True, text=True, timeout=30, check=True)
    res = json.loads(proc.stdout)
    for r in res:
        assert "err" not in r, r["err"]
    return [r["ok"] for r in res]


DAY = 86_400


def tape(n=12):
    return {"symbol": "BTC", "kind": "crypto", "tf": "1D", "ts": [1_760_000_000 + i * DAY for i in range(n)],
            "ohlc": [[100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i] for i in range(n)]}


def compiled():
    src = {"id": "dca-01", "class": "dca", "title": "T", "free": True, "tape": "t",
           "vars": {"p": {"fn": "dca", "every": 3, "start": 0}},
           "steps": [
               {"who": "Q", "say": "Start.", "do": [{"op": "frame", "from": 0, "to": -1}, {"op": "seek", "bar": -1}]},
               {"who": "T", "say": "Rewind.", "do": [{"op": "seek", "bar": 0}, {"op": "buys", "var": "p"}]},
               {"who": "T", "say": "Play.", "do": [{"op": "play", "to": 7}, {"op": "buys", "var": "p"},
                                                   {"op": "line", "a": {"bar": 1}, "b": {"bar": 6}}]},
               {"who": "T", "say": "Level.", "do": [{"op": "level", "var": "p.avg", "title": "Avg"}]},
               {"who": "Q", "say": "Clear.", "do": [{"op": "clear"}, {"op": "mark", "bar": 2, "dir": "lump"}]},
               {"who": "T", "say": "End.", "do": [{"op": "play", "to": -1}, {"op": "buys", "var": "p"}]},
           ]}
    return lc.compile_lesson(src, tape())


def test_js_fold_matches_the_compiler_at_every_step():
    lesson = compiled()
    idx = list(range(-1, len(lesson["steps"])))
    js = run_js([("lessonStateAt", [lesson, i]) for i in idx])
    for i, got in zip(idx, js):
        assert got == lc.state_at(lesson, i), f"step {i} differs"


def test_play_plan_animates_only_steps_that_play():
    lesson = compiled()
    plans = run_js([("lessonPlayPlan", [lesson, i]) for i in range(len(lesson["steps"]))])
    assert plans[0] == {"fromIdx": 11, "toIdx": 11, "animate": False}     # opens on the last bar
    assert plans[1] == {"fromIdx": 0, "toIdx": 0, "animate": False}       # a seek jumps, it doesn't play
    assert plans[2] == {"fromIdx": 0, "toIdx": 7, "animate": True}
    assert plans[3] == {"fromIdx": 7, "toIdx": 7, "animate": False}
    assert plans[5] == {"fromIdx": 7, "toIdx": 11, "animate": True}


@pytest.mark.parametrize("bars,dur", [(7, 7000), (350, 7200), (1, 500), (60, 400)])
def test_tick_schedule_reaches_the_end_inside_the_line(bars, dur):
    (plan,) = run_js([("lessonTicks", [0, bars, dur])])
    assert plan["tickMs"] >= 40                                   # never a busy loop
    assert plan["ticks"] * plan["barsPerTick"] >= bars            # arrives at the target
    assert plan["ticks"] * plan["tickMs"] <= max(dur * 0.9, 40)   # and before the voice finishes


def test_levels_become_gold_price_lines():
    lesson = compiled()
    lines, = run_js([("(l) => lessonOptLines(lessonStateAt(l, 3))", [lesson])])
    assert lines == [{"price": pytest.approx(lc.state_at(lesson, 3)["levels"][0]["price"]),
                      "kind": "level", "title": "Avg"}]


def test_index_of_ts_is_exact_or_minus_one():
    lesson = compiled()
    ts = lesson["tape"]["ts"]
    got = run_js([("lessonIndexOfTs", [ts, ts[4]]), ("lessonIndexOfTs", [ts, ts[4] + 1]),
                  ("lessonIndexOfTs", [[], 5])])
    assert got == [4, -1, -1]
