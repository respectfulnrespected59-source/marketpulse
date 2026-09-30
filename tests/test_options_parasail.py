"""Para-Sail rules on the options paper book (static/options-parasail.js), owner 2026-09-30.

"C both" — the app's signal picks the spread (he used "Load the signal's spread" on TSLA), and the
Para-Sail rules wrap it:
  ON PLAN     bounce = call spread with the stock inside its 8 % low zone;
              breakdown = put spread with the stock within 2 % of its 30-day low (TSLA 9/29: at it)
  CAP         a spread costing more than 10 % of equity is off plan
  PARA-SAIL   up 40 % on what it cost (after every commission) -> close half; one contract = all of it
  TIME CHUTE  expiry day, from noon New York time: take it or cut it (TSLA 9/30: near max at the
              morning low, worth $0.19 at the close)
  SCORECARD   pre-registered forward test: trades grouped (a para-sail half is part of its trade),
              losers counted, on plan vs off, expectancy; a verdict only at 25 trades
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
const ctx = { console, Math, Number, String, JSON, isFinite, Array, Object, Intl, Date };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(process.argv[1], "static", "options-parasail.js"), "utf8"), ctx);
process.stdout.write(JSON.stringify(vm.runInContext(process.argv[2], ctx)));
"""


def run(expr):
    if NODE is None:
        pytest.skip("node is not installed")
    res = subprocess.run([NODE, "-e", HARNESS, ROOT, expr], capture_output=True, text=True, encoding="utf-8",
                         timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def js(v):
    return json.dumps(v)


# ------------------------------------------------------------------ on plan?
@pytest.mark.parametrize("direction,zone,setup,on_plan", [
    ("put", {"low": 352.84, "top": 381.07, "close": 352.84, "where": "inside"}, "breakdown", True),   # TSLA 9/29
    ("put", {"low": 354.08, "top": 382.41, "close": 357.45, "where": "inside"}, "breakdown", True),   # TSLA 9/28
    ("put", {"low": 100, "top": 108, "close": 105, "where": "inside"}, "off plan", False),            # 5 % over
    ("call", {"low": 100, "top": 108, "close": 104, "where": "inside"}, "bounce", True),
    ("call", {"low": 100, "top": 108, "close": 115, "where": "above"}, "off plan", False),
])
def test_the_signals_spread_is_on_plan_only_at_the_low(direction, zone, setup, on_plan):
    out = run(f"optSetup({js(direction)}, {js(zone)})")
    assert out["setup"] == setup and out["onPlan"] is on_plan
    assert out["why"]


def test_no_read_on_the_underlying_is_unknown_not_on_plan():
    out = run("optSetup('put', null)")
    assert out["setup"] == "unknown" and out["onPlan"] is False


# ------------------------------------------------------------------ the cap
def test_the_cap_is_ten_percent_of_equity():
    assert run("optCapCheck(750, 10000)") == {"ok": True, "pct": 7.5}          # TSLA: 3 x ~$250 on $10k
    assert run("optCapCheck(1001, 10000)")["ok"] is False
    assert run("optCapCheck(100, 0)")["ok"] is False


# ------------------------------------------------------------------ para-sail
POS = {"id": "op1", "trade": "op1", "symbol": "TSLA", "expiry": "2026-09-30", "contracts": 3, "entry_debit": 2.5,
       "cost_usd": 753.9, "commission": 3.9, "max_loss_usd": 753.9, "max_profit_usd": 746.1,
       "legs": [{"right": "put", "strike": 355, "side": "long", "qty": 3, "entry": 4.1},
                {"right": "put", "strike": 350, "side": "short", "qty": 3, "entry": 1.6}],
       "setup": "breakdown", "onPlan": True}


def test_para_sail_is_due_at_plus_40_after_every_commission():
    assert run(f"optSailDue({js(POS)}, {{net_usd: 301.56}})") is True     # 0.40 x 753.90 = 301.56
    assert run(f"optSailDue({js(POS)}, {{net_usd: 301.55}})") is False
    assert run(f"optSailDue({js({**POS, 'sailed': True})}, {{net_usd: 700}})") is False   # once per trade
    assert run(f"optSailDue({js(POS)}, {{net_usd: null}})") is False                       # no mark, no call


def test_closing_half_scales_every_total_and_keeps_the_trade_together():
    out = run(f"optSplitClose({js(POS)}, {{mark: 4.9, net_usd: 714.3}}, 1)")
    closed, rest = out["closed"], out["rest"]
    assert closed["contracts"] == 1 and closed["pnl"] == pytest.approx(238.1)
    assert closed["trade"] == "op1" and closed["setup"] == "breakdown" and closed["sailed"] is True
    assert rest["contracts"] == 2 and rest["sailed"] is True and rest["trade"] == "op1"
    assert rest["cost_usd"] == pytest.approx(502.6) and rest["commission"] == pytest.approx(2.6)
    assert rest["max_loss_usd"] == pytest.approx(502.6) and rest["max_profit_usd"] == pytest.approx(497.4)
    assert [leg["qty"] for leg in rest["legs"]] == [2, 2]
    assert rest["id"] != POS["id"] or closed["id"] != POS["id"]


def test_half_of_three_is_one_and_half_of_one_is_the_whole_thing():
    assert run("optHalf(3)") == 1 and run("optHalf(2)") == 1 and run("optHalf(4)") == 2
    assert run("optHalf(1)") == 1
    out = run(f"optSplitClose({js({**POS, 'contracts': 1})}, {{mark: 4.9, net_usd: 238.1}}, 1)")
    assert out["rest"] is None and out["closed"]["pnl"] == pytest.approx(238.1)


# ------------------------------------------------------------------ the time parachute
@pytest.mark.parametrize("utc,due", [
    ("Date.UTC(2026, 8, 30, 15, 59)", False),   # 11:59 New York (EDT) on expiry day
    ("Date.UTC(2026, 8, 30, 16, 0)", True),     # noon New York on expiry day
    ("Date.UTC(2026, 8, 29, 19, 0)", False),    # the afternoon BEFORE expiry
    ("Date.UTC(2026, 9, 1, 14, 0)", True),      # past expiry and still open
    ("Date.UTC(2026, 11, 18, 17, 0)", True),    # noon in December = EST (UTC-5): the clock is New York's
])
def test_the_time_parachute_opens_at_noon_new_york_on_expiry_day(utc, due):
    expiry = "2026-12-18" if "11, 18" in utc else "2026-09-30"
    assert run(f"optTimeParachute({js(expiry)}, {utc})") is due


# ------------------------------------------------------------------ the scorecard
def t(trade, pnl, setup="breakdown", on=True, **over):
    return {"trade": trade, "pnl": pnl, "setup": setup, "onPlan": on, **over}


def test_the_scorecard_groups_a_para_sail_with_its_trade_and_counts_losers():
    closed = [t("a", 238.1, sailed=True), t("a", 476.2), t("b", -250.0), t("c", 90.0, "off plan", False),
              {"trade": "old", "pnl": 500.0}]          # before the rules: no setup, not scored
    s = run(f"optScorecard({js(closed)})")
    assert s["n"] == 3 and s["target"] == 25 and s["done"] is False
    assert s["wins"] == 2 and s["losses"] == 1
    assert s["total"] == pytest.approx(554.3)
    assert s["expectancy"] == pytest.approx(554.3 / 3)
    assert s["avgWin"] == pytest.approx((714.3 + 90.0) / 2) and s["avgLoss"] == pytest.approx(-250.0)
    assert s["onPlan"]["n"] == 2 and s["offPlan"]["n"] == 1
    assert s["onPlan"]["total"] == pytest.approx(464.3)
    assert s["verdict"] is None              # no verdict before 25 trades


def test_a_trade_still_open_after_its_para_sail_is_not_scored_yet():
    # Caught on the real page: the half was scored as a finished 100 % win while 2 contracts rode on —
    # a trade that can still lose must not count until the last contract is closed.
    closed = [t("a", 207.33, sailed=True), t("b", -120.0)]
    s = run(f"optScorecard({js(closed)}, ['a'])")
    assert s["n"] == 1 and s["wins"] == 0 and s["losses"] == 1 and s["open"] == 1
    assert run(f"optScorecard({js(closed)})")["n"] == 2       # no open list: everything closed is scored


def test_at_25_trades_the_scorecard_gives_the_pre_registered_verdict():
    wins = [t(f"w{i}", 100.0) for i in range(10)]
    losses = [t(f"l{i}", -80.0) for i in range(15)]
    s = run(f"optScorecard({js(wins + losses)})")
    assert s["done"] is True and s["n"] == 25
    assert s["expectancy"] == pytest.approx((1000 - 1200) / 25)
    assert s["verdict"] == "fail"            # expectancy after every cost must be above $0
    good = run(f"optScorecard({js([t(f'x{i}', 50.0) for i in range(25)])})")
    assert good["verdict"] == "pass"
