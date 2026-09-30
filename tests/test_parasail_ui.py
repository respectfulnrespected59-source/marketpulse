"""The Para-Sail card and the buy-zone watcher (static/parasail-ui.js).

Pinned: the zone watcher fires at or under the zone top (and above/below alerts still work), the
words on a chip and a notification say what actually happened, and the card tells the truth — BTC is
shown as held, "in the zone" only when the numbers say so, and whichever of para-sailing or holding
did better on this history is the one it names. The JS runs in Node's vm with the page's globals.
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
const ctx = {
  console, Math, Number, String, JSON, isFinite, Array, Object,
  esc: (s) => String(s ?? "").replace(/[&<>"']/g, (c) => "&#" + c.charCodeAt(0) + ";"),
  fmtPrice: (p) => (p == null ? "—" : "$" + Number(p).toFixed(2)),
  potMoney: (v) => "$" + Math.round(v).toLocaleString("en-US"),
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(process.argv[1], "static", "parasail-ui.js"), "utf8"), ctx);
const out = vm.runInContext(process.argv[2], ctx);
process.stdout.write(JSON.stringify(out));
"""


def run(expr):
    if NODE is None:
        pytest.skip("node is not installed")
    # utf-8 explicitly: node writes UTF-8, and Windows would otherwise decode "◆ ≤" with its code page
    res = subprocess.run([NODE, "-e", HARNESS, ROOT, expr], capture_output=True, text=True, encoding="utf-8",
                         timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


BASE = {"symbol": "ETHEREUM", "kind": "crypto", "hold": False, "since": "2025-09-30", "until": "2026-09-29",
        "rules": {"low_days": 30, "zone_pct": 8, "gap_days": 7, "fill": 100, "cap": 2000, "sail_pct": 40,
                  "sell_pct": 50},
        "zone": {"low": 2400, "low_date": "2026-09-10", "top": 2592, "close": 2683, "where": "above",
                 "gap_pct": 3.5},
        "buys": [], "sails": [], "n": 12, "n_sails": 2, "invested": 1200, "peak": 1100, "proceeds": 300,
        "value": 1400, "profit": 600, "roi": 54.5, "hold_profit": 400, "hold_roi": 33.3}


def card(**over):
    return run(f"parasailCard({json.dumps({**BASE, **over})})")


# ------------------------------------------------------------------ alerts
@pytest.mark.parametrize("alert,price,hit", [
    ({"dir": "zone", "price": 2592}, 2592, True),
    ({"dir": "zone", "price": 2592}, 2500, True),
    ({"dir": "zone", "price": 2592}, 2593, False),
    ({"dir": "above", "price": 100}, 101, True),
    ({"dir": "above", "price": 100}, 99, False),
    ({"dir": "below", "price": 100}, 99, True),
    ({"dir": "below", "price": 100}, 101, False),
    ({"dir": "sideways", "price": 100}, 100, False),
])
def test_alerts_fire_when_their_line_is_crossed(alert, price, hit):
    assert run(f"alertHit({json.dumps(alert)}, {price})") is hit


def test_a_zone_chip_and_its_notification_say_what_happened():
    a = {"dir": "zone", "price": 2592, "low": 2400}
    assert run(f"alertText({json.dumps(a)})") == "◆ buy zone ≤ $2592.00"
    msg = run(f"alertFiredMsg('ETH', {json.dumps(a)})")
    assert msg == "ETH entered its Para-Sail buy zone: at or under $2592.00 (8 % over its 30-day low $2400.00)"
    assert run("alertText({dir: 'above', price: 5})") == "▲ above $5.00"
    assert run("alertFiredMsg('X', {dir: 'below', price: 5})") == "X dropped below $5.00"


# ------------------------------------------------------------------ the card
def test_the_card_says_above_the_zone_with_the_numbers():
    html = card()
    assert "Above the buy zone" in html and "3.5%" in html and "$2400.00" in html and "2026-09-10" in html
    assert "In the buy zone" not in html


def test_the_card_says_in_the_zone_only_when_the_close_is_inside():
    html = card(zone={**BASE["zone"], "close": 2500, "where": "inside", "gap_pct": -3.5})
    assert "In the buy zone" in html and "Above the buy zone" not in html


def test_btc_is_shown_as_held_not_para_sailed():
    html = card(symbol="BITCOIN", hold=True, n_sails=0, profit=400, roi=33.3)
    assert "held" in html.lower() and "treat as money" in html
    assert "para-sails" not in html


def test_uncapped_btc_says_so_and_never_shows_a_zero_cap():
    # Number(null) is 0: the card must read the cap BEFORE coercing, or uncapped BTC shows "cap $0".
    html = card(symbol="BITCOIN", hold=True, n_sails=0, rules={**BASE["rules"], "cap": None})
    assert "no cap — held as money" in html and "cap $0" not in html
    assert "cap $2,000 per name" in card()


def test_the_card_judges_per_dollar_at_risk_and_shows_the_money_each_needed():
    # NVDA on the real app (09-30): para-sail +$1,755 on $2,000 in (+87.8 %); holding the same 54 buys
    # made more dollars (+$2,308) but needed $5,400 in (+42.7 %). "Holding did better by $553" was unfair.
    better = card(profit=1755, peak=2000, roi=87.8, invested=5400, hold_profit=2308, hold_roi=42.7)
    assert "Per dollar at risk, para-sailing did better here" in better
    assert "$2,000" in better and "$5,400" in better
    assert "Holding made more dollars" in better          # the dollars are still said, with the capital
    worse = card(profit=300, peak=2000, roi=15.0, invested=2000, hold_profit=900, hold_roi=45.0)
    assert "Holding the same buys did better here" in worse and "Per dollar at risk, para-sailing" not in worse


def test_no_sale_yet_is_a_tie_not_a_win():
    # ETH on the real app (09-30): 0 para-sails, +2.6 % vs +2.6 %, and the card called para-sailing the winner.
    html = card(n_sails=0, profit=51, roi=2.6, peak=2000, invested=2000, hold_profit=51, hold_roi=2.6)
    assert "did better" not in html
    assert "No wave has reached +40% yet" in html


def test_the_card_carries_the_news_cord_and_the_watch_button():
    html = card()
    assert "news" in html.lower() and "bankruptcy" in html and 'id="psWatch"' in html


def test_the_card_escapes_the_symbol():
    html = card(symbol='<img src=x onerror="alert(1)">')
    assert "<img" not in html


def test_errors_and_locks_render_as_messages():
    assert "not enough history" in run("parasailCard({error: 'not enough history', symbol: 'X'})")
    assert "Pro" in run("parasailCard({locked: true, error: 'The Para-Sail strategy is a Pro feature.'})")
