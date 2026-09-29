"""Options paper positions on the live chart (static/chart-options.js).

The trader opened a paper put spread and could not see it on the live chart,
so there was no way to watch it go green or red. These pin the pure parts:
which positions belong to the chart on screen, which price lines they draw,
and the live P&L estimate — which must never pretend to be a real quote, must
say nothing rather than guess when an input is missing, and must stay inside
the spread's max profit and max loss.

The JS runs in Node's vm with the same globals the page gives it (options-paper.js
is loaded alongside so the shared helpers are the real ones).
"""
import json
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
NODE = shutil.which("node")

HARNESS = r"""
const fs = require("fs"), vm = require("vm"), path = require("path");
const dir = process.argv[1];
const store = {};
const ctx = {
  console, Math, Number, String, JSON, Date, isFinite, Array, Object, Set,
  localStorage: { getItem: (k) => (k in store ? store[k] : null),
                  setItem: (k, v) => { store[k] = String(v); } },
  $: () => null, document: { querySelector: () => null },
  esc: (s) => String(s).replace(/[&<>"']/g, (c) => "&#" + c.charCodeAt(0) + ";"),
  // Mirrors app.js fmtPrice: it calls toFixed, so a STRING throws there too.
  fmtPrice: (p) => (p == null ? "—" : "$" + p.toFixed(2)),
  setInterval: (fn) => { ctx.__intervals.push(fn); return ctx.__intervals.length; },
  clearInterval: (id) => { ctx.__cleared.push(id); },
  __intervals: [], __cleared: [], __ticks: 0,
};
vm.createContext(ctx);
for (const f of ["options-paper.js", "chart-options.js"]) {
  vm.runInContext(fs.readFileSync(path.join(dir, f), "utf8"), ctx, { filename: f });
}
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map(([fn, args]) => {
  try { return { ok: vm.runInContext(fn, ctx)(...args) }; }
  catch (e) { return { err: String(e && e.message || e) }; }
});
process.stdout.write(JSON.stringify(out));
"""


def run_js(cases):
    """cases: [(js function expression, [args...]), ...] -> list of results."""
    if not NODE:
        pytest.skip("node is not installed")
    proc = subprocess.run([NODE, "-e", HARNESS, STATIC], input=json.dumps(cases),
                          capture_output=True, text=True, timeout=30, check=True)
    res = json.loads(proc.stdout)
    for r in res:
        assert "err" not in r, r["err"]
    return [r["ok"] for r in res]


def one(fn, *args):
    return run_js([(fn, list(args))])[0]


PUT_SPREAD = {
    "id": "op1", "symbol": "TSLA", "expiry": "2026-09-30", "contracts": 3,
    "legs": [{"right": "put", "strike": 250, "side": "long", "qty": 1, "entry": 4.1},
             {"right": "put", "strike": 245, "side": "short", "qty": 1, "entry": 2.0}],
    "entry_debit": 2.1, "cost_usd": 632.0, "max_profit_usd": 870.0,
    "max_loss_usd": 630.0, "breakeven": 247.9,
}
MARK = {"id": "op1", "status": "open", "spot": 252.0, "mark": 1.8, "net_usd": -94.0,
        "dte": 1, "greeks": {"delta": -0.9, "gamma": 0.12, "theta": -0.5}}


def book(open_=None, marks=None):
    return {"open": open_ if open_ is not None else [PUT_SPREAD],
            "marks": marks if marks is not None else {"op1": MARK}}


# ------------------------------------------------------------ which positions
class TestPositionsForChart:
    def test_position_on_the_charted_symbol_is_found_case_insensitively(self):
        got = one("optChartPositions", book(), "tsla")
        assert [e["pos"]["id"] for e in got] == ["op1"]
        assert got[0]["mark"]["net_usd"] == -94.0

    def test_other_symbols_are_not_drawn_on_this_chart(self):
        assert one("optChartPositions", book(), "NVDA") == []

    def test_no_symbol_or_empty_book_draws_nothing(self):
        assert run_js([("optChartPositions", [book(), ""]),
                       ("optChartPositions", [book(open_=[]), "TSLA"]),
                       ("optChartPositions", [{}, "TSLA"])]) == [[], [], []]

    def test_a_position_with_no_mark_yet_still_shows_with_a_null_mark(self):
        got = one("optChartPositions", book(marks={}), "TSLA")
        assert got[0]["mark"] is None

    def test_a_mark_left_over_from_an_old_session_is_not_shown_as_current(self):
        now = 1_800_000_000_000
        fresh = {**book(), "lastMark": now - 5 * 60_000}
        stale = {**book(), "lastMark": now - 31 * 60_000}
        unknown = {**book(), "lastMark": None}
        got = run_js([("optChartPositions", [fresh, "TSLA", now]),
                      ("optChartPositions", [stale, "TSLA", now]),
                      ("optChartPositions", [unknown, "TSLA", now])])
        assert got[0][0]["mark"]["net_usd"] == -94.0
        assert got[1][0]["mark"] is None
        assert got[2][0]["mark"] is None


# ------------------------------------------------------------ price lines
class TestLines:
    def test_breakeven_and_each_strike_become_price_lines(self):
        lines = one("optChartLines", [{"pos": PUT_SPREAD, "mark": MARK}])
        by_kind = {}
        for ln in lines:
            by_kind.setdefault(ln["kind"], []).append(ln)
        assert [l["price"] for l in by_kind["be"]] == [247.9]
        assert sorted(l["price"] for l in by_kind["strike"]) == [245, 250]
        titles = {l["price"]: l["title"] for l in by_kind["strike"]}
        assert titles[250] == "+250P" and titles[245] == "-245P"

    def test_same_strike_across_two_positions_is_one_line(self):
        other = {**PUT_SPREAD, "id": "op2"}
        lines = one("optChartLines", [{"pos": PUT_SPREAD, "mark": None}, {"pos": other, "mark": None}])
        assert sorted(l["price"] for l in lines if l["kind"] == "strike") == [245, 250]

    def test_two_positions_with_the_same_breakeven_draw_one_be_line(self):
        other = {**PUT_SPREAD, "id": "op2"}
        lines = one("optChartLines", [{"pos": PUT_SPREAD, "mark": None}, {"pos": other, "mark": None}])
        assert [l["price"] for l in lines if l["kind"] == "be"] == [247.9]

    def test_unusable_numbers_draw_no_line(self):
        bad = {**PUT_SPREAD, "breakeven": None,
               "legs": [{"right": "put", "strike": "x", "side": "long"}]}
        assert one("optChartLines", [{"pos": bad, "mark": None}]) == []


# ------------------------------------------------------------ live estimate
class TestEstimate:
    def test_moves_from_the_marked_pnl_by_delta_and_gamma(self):
        # spot 252 -> 250: dS=-2; (-0.9*-2 + 0.5*0.12*4) * 100 = 204 -> -94 + 204
        est = one("optChartEstimate", PUT_SPREAD, MARK, 250.0)
        assert est == pytest.approx(110.0)

    def test_no_move_returns_the_marked_pnl(self):
        assert one("optChartEstimate", PUT_SPREAD, MARK, 252.0) == pytest.approx(-94.0)

    def test_never_beyond_max_profit_or_max_loss(self):
        tight = {**PUT_SPREAD, "max_profit_usd": 50.0, "max_loss_usd": 120.0}
        hi, lo = run_js([("optChartEstimate", [tight, MARK, 249.0]),
                         ("optChartEstimate", [tight, MARK, 254.0])])
        assert hi == pytest.approx(50.0)
        assert lo == pytest.approx(-120.0)

    def test_limits_are_net_of_the_commissions_the_server_charged(self):
        # gross - net = $7.80 of open+close commissions: the real floor is
        # -(max_loss + 7.80) and the real ceiling max_profit - 7.80.
        tight = {**PUT_SPREAD, "max_profit_usd": 50.0, "max_loss_usd": 120.0}
        mark = {**MARK, "gross_usd": -86.2}
        hi, lo = run_js([("optChartEstimate", [tight, mark, 249.0]),
                         ("optChartEstimate", [tight, mark, 254.0])])
        assert hi == pytest.approx(42.2)
        assert lo == pytest.approx(-127.8)

    def test_delta_is_not_allowed_to_flip_sign(self):
        # delta -0.9, gamma 0.12 reaches zero 7.5 points up; past that a put
        # spread must stay flat, not start "gaining" as the stock rips.
        # 7.5 up: -0.9*7.5 + 0.06*56.25 = -3.375 -> -337.5; -94 - 337.5
        assert one("optChartEstimate", PUT_SPREAD, MARK, 262.0) == pytest.approx(-431.5)

    def test_too_far_from_the_mark_to_extrapolate_says_nothing(self):
        # > 5% from where the chain was marked: the quadratic is not a price.
        assert run_js([("optChartEstimate", [PUT_SPREAD, MARK, 150.0]),
                       ("optChartEstimate", [PUT_SPREAD, MARK, 400.0])]) == [None, None]

    @pytest.mark.parametrize("mark", [
        None,
        {**MARK, "net_usd": None},                       # unquoted leg
        {**MARK, "spot": None},                          # no spot at mark time
        {**MARK, "greeks": {}},                          # no delta
        {**MARK, "status": "expired"},                   # settled, nothing to estimate
    ])
    def test_says_nothing_rather_than_guess(self, mark):
        assert one("optChartEstimate", PUT_SPREAD, mark, 250.0) is None

    def test_no_live_price_means_no_estimate(self):
        assert run_js([("optChartEstimate", [PUT_SPREAD, MARK, None]),
                       ("optChartEstimate", [PUT_SPREAD, MARK, "abc"])]) == [None, None]


# ------------------------------------------------------------ the strip
class TestStrip:
    def test_strip_shows_the_stats_and_labels_the_estimate_as_an_estimate(self):
        html = one("optChartStripHtml", [{"pos": PUT_SPREAD, "mark": MARK}], 250.0)
        assert "TSLA" in html and "3x" in html
        assert "-$94.00" in html            # P&L at the last mark
        assert "$110.00" in html            # live estimate
        assert "est" in html.lower() and "delayed" in html.lower()
        assert "247.90" in html             # breakeven
        assert "1d left" in html

    def test_unmarked_position_says_marking_instead_of_a_number(self):
        html = one("optChartStripHtml", [{"pos": PUT_SPREAD, "mark": None}], 250.0)
        assert "marking" in html.lower()
        assert "$0.00" not in html

    def test_empty_strip_is_empty(self):
        assert one("optChartStripHtml", [], 250.0) == ""

    def test_a_string_breakeven_from_old_storage_does_not_throw(self):
        # fmtPrice calls toFixed; a string used to throw and blank the whole chart.
        odd = {**PUT_SPREAD, "breakeven": "247.9"}
        html = one("optChartStripHtml", [{"pos": odd, "mark": MARK}], 250.0)
        assert "247.90" in html

    def test_symbol_text_is_escaped(self):
        evil = {**PUT_SPREAD, "symbol": "<img src=x onerror=alert(1)>"}
        html = one("optChartStripHtml", [{"pos": evil, "mark": None}], 250.0)
        assert "<img" not in html


# ------------------------------------------------------------ the marking loop
# Each case runs in a FRESH vm, so every scenario states its own book and stubs.
LOOP = r"""() => {
  optBookTick = () => { __ticks += 1; };
  const save = (open) => localStorage.setItem("mp_optbook", JSON.stringify({ open, marks: {} }));
  const out = {};
  %s
  return out;
}"""


def loop(body):
    return one(LOOP % body)


class TestMarkingLoop:
    def test_starts_marking_when_the_chart_shows_a_held_symbol(self):
        got = loop("""save([{ id: "a", symbol: "TSLA" }]);
                      optChartEnsureMarking(true);
                      out.running = optChartTimer !== null; out.ticks = __ticks;""")
        assert got == {"running": True, "ticks": 1}

    def test_stopping_clears_the_interval(self):
        got = loop("""save([{ id: "a", symbol: "TSLA" }]);
                      optChartEnsureMarking(true); optChartEnsureMarking(false);
                      out.running = optChartTimer !== null; out.cleared = __cleared.length;""")
        assert got == {"running": False, "cleared": 1}

    def test_the_interval_switches_itself_off_once_the_book_is_empty(self):
        got = loop("""save([{ id: "a", symbol: "TSLA" }]);
                      optChartEnsureMarking(true);
                      save([]);
                      __intervals[__intervals.length - 1]();
                      out.running = optChartTimer !== null; out.ticks = __ticks;""")
        assert got == {"running": False, "ticks": 1}

    def test_the_interval_defers_to_the_books_own_loop(self):
        got = loop("""save([{ id: "a", symbol: "TSLA" }]);
                      optChartEnsureMarking(true);
                      optBookTimer = 99;
                      __intervals[__intervals.length - 1]();
                      out.running = optChartTimer !== null; out.ticks = __ticks;""")
        assert got == {"running": False, "ticks": 1}

    def test_leaving_the_live_tab_stops_the_loop(self):
        src = _read("app.js")
        i = src.index("stopChartPoll()")
        assert "optChartEnsureMarking(false)" in src[i - 400:i + 400]


# ------------------------------------------------------------ wiring
def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


class TestWiring:
    def test_page_loads_the_module_after_options_paper_and_before_app(self):
        html = _read("index.html")
        a, b, c = (html.index('src="options-paper.js"'), html.index('src="chart-options.js"'),
                   html.index('src="app.js"'))
        assert a < b < c
        assert 'id="ltcOpt"' in html

    def test_chart_render_passes_option_lines_to_the_engine(self):
        assert "optLines" in _read("chart.js")
        eng = _read("chart-engine.js")
        assert "_pcSetOptLines(m.optLines" in eng and "_pcSetOptLines([])" in eng

    def test_price_scale_stretches_to_keep_nearby_option_lines_in_view(self):
        # Found by looking: the breakeven sat just below the auto-fitted ladder,
        # so the one line that matters was off screen. Replay keeps its pinned range.
        eng = _read("chart-engine.js")
        assert "_pcWithOptRange(base())" in eng
        assert "PC_OPT_NEAR" in eng and "pc.optRange" in eng

    def test_opening_a_position_jumps_to_its_live_chart(self):
        src = _read("options-paper.js")
        assert "openLiveFor(\"stock\", pos.symbol)" in src
        assert "data-optchart" in src

    def test_service_worker_caches_the_new_file(self):
        assert "chart-options.js" in _read("sw.js")
