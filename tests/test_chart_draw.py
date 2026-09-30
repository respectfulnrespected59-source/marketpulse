"""The drawing layer's per-mark guide lines (static/chart-draw.js).

Every mark gets a faint dotted line across the chart at its price: useful for the few levels a trader
places, a wall of lines for a lesson plan's buys and sales (the Para-Sail lesson draws 103). Past a
handful of marks the rings stay and the guides go. The JS runs in Node's vm with a recording canvas.
"""
import json
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")

HARNESS = r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const marks = JSON.parse(process.argv[2]);
const calls = { guides: 0, rings: 0 };
const canvas = {
  _dash: [], _stack: [],                      // save/restore carry the dash, as a real canvas does
  save() { this._stack.push(this._dash); }, restore() { this._dash = this._stack.pop() || []; },
  beginPath() {}, moveTo() {}, lineTo() {}, fill() {}, fillRect() {}, strokeRect() {},
  translate() {}, rotate() {}, fillText() {},
  setLineDash(d) { this._dash = d; },
  arc() { calls.rings++; },
  stroke() { if (this._dash && this._dash.length) calls.guides++; },
};
const ctx = {
  Math, Number, String, JSON, Array, Object, Set,
  pc: { colors: { buy: "#2fd180", sell: "#ff5d6c" } },
  pcIdxOfTs: (ts) => ts, pcXY: (i, price) => ({ x: i * 10, y: price }),
  pcDrawSource: () => ({ marks, lines: [] }),
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(process.argv[1], "static", "chart-draw.js"), "utf8"), ctx);
vm.runInContext("_pdUserLayer", ctx)(canvas, { width: 800, height: 400 });
process.stdout.write(JSON.stringify(calls));
"""


def paint(n, dir_="buy"):
    if NODE is None:
        pytest.skip("node is not installed")
    marks = [{"ts": i, "price": 100 + i, "dir": dir_} for i in range(n)]
    res = subprocess.run([NODE, "-e", HARNESS, ROOT, json.dumps(marks)], capture_output=True, text=True,
                         encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_a_few_marks_each_get_a_guide_line():
    assert paint(3, "mark") == {"guides": 3, "rings": 3}


def test_a_lessons_twelve_buys_keep_their_guides():
    # DCA lesson 1 draws its 12 buys with guides; that picture must not change.
    assert paint(12) == {"guides": 12, "rings": 12}


def test_a_plan_with_many_fills_draws_rings_without_a_wall_of_lines():
    assert paint(103) == {"guides": 0, "rings": 103}
