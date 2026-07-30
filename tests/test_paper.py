"""Paper-trading decisions: the trader's rules against live prices.

paper_scan reports what the rules imply — it never opens or closes anything
itself. The browser does that. So the contract these tests hold is narrow and
important: given a rule set and a set of open positions, does it say the right
thing, and does it stay quiet when it should?

It runs the SAME engine the paid agent runs. That is the point: a rule that
fires on paper must fire identically when it is executing on a real broker.
"""

import pytest

import app

pytestmark = pytest.mark.unit


def a_row(symbol="AAPL", price=190.0, rsi=60.0, label="STRONG BUY", stack="bull"):
    return {
        "symbol": symbol,
        "price": price,
        "signal": {"rsi": rsi, "label": label, "score": 4},
        "guides": {"stack": stack, "ma5": 189.0, "vwap": 188.0},
        "squeeze": {"weekly": {"state": "fired", "bars": 4, "mom": "bull",
                               "accel": "rising"}},
    }


def a_strategy(**over):
    doc = {
        "name": "Paper rules",
        "kind": "stock",
        "universe": ["AAPL"],
        "entry": {"all": [["rsi", "<", 70]]},
        "exit": {"any": [["rsi", ">", 80]], "stop_loss_pct": 8},
    }
    doc.update(over)
    return doc


@pytest.fixture
def stocks(monkeypatch):
    """Swap the live fetch for a controllable one."""
    rows: list[dict] = []

    def fake(symbols):
        return [r for r in rows if r["symbol"] in symbols]

    monkeypatch.setattr(app, "fetch_stocks", fake)
    return rows


class TestPaperScanEntries:
    def test_reports_an_entry_when_the_rules_hold(self, stocks):
        stocks.append(a_row(rsi=60.0))
        out = app.paper_scan(a_strategy(), {})
        assert out["decisions"][0]["entry"] is True
        assert out["decisions"][0]["exit"] is False

    def test_stays_quiet_when_the_rules_do_not_hold(self, stocks):
        stocks.append(a_row(rsi=85.0))
        out = app.paper_scan(a_strategy(), {})
        assert out["decisions"][0]["entry"] is False

    def test_does_not_re_enter_a_position_already_held(self, stocks):
        # Holding it means the only question is whether to exit.
        stocks.append(a_row(rsi=60.0))
        out = app.paper_scan(a_strategy(), {"AAPL": 180.0})
        assert out["decisions"][0]["entry"] is False

    def test_reports_the_price_the_decision_was_made_on(self, stocks):
        stocks.append(a_row(price=190.0))
        assert app.paper_scan(a_strategy(), {})["decisions"][0]["price"] == 190.0


class TestPaperScanExits:
    def test_stop_loss_fires_and_says_so(self, stocks):
        stocks.append(a_row(price=91.0, rsi=50.0))
        out = app.paper_scan(a_strategy(), {"AAPL": 100.0})
        assert out["decisions"][0]["exit"] is True
        assert "stop loss" in out["decisions"][0]["why"]

    def test_take_profit_fires(self, stocks):
        stocks.append(a_row(price=120.0, rsi=50.0))
        doc = a_strategy(exit={"take_profit_pct": 15})
        out = app.paper_scan(doc, {"AAPL": 100.0})
        assert out["decisions"][0]["exit"] is True
        assert "take profit" in out["decisions"][0]["why"]

    def test_a_rule_exit_fires(self, stocks):
        stocks.append(a_row(price=100.0, rsi=90.0))
        out = app.paper_scan(a_strategy(), {"AAPL": 100.0})
        assert out["decisions"][0]["exit"] is True

    def test_holds_when_nothing_says_otherwise(self, stocks):
        stocks.append(a_row(price=101.0, rsi=50.0))
        out = app.paper_scan(a_strategy(), {"AAPL": 100.0})
        assert out["decisions"][0]["exit"] is False
        assert out["decisions"][0]["why"] == ""


class TestPaperScanGuards:
    def test_an_invalid_strategy_is_refused_with_reasons(self, stocks):
        out = app.paper_scan({"name": "x"}, {})
        assert out["error"] == "invalid strategy"
        assert out["problems"]

    def test_a_bad_ticker_is_skipped_not_fatal(self, stocks):
        # One unusable symbol must not cost the trader their whole run.
        stocks.append(a_row("AAPL"))
        doc = a_strategy(universe=["AAPL", "../etc/passwd"])
        out = app.paper_scan(doc, {})
        assert [d["symbol"] for d in out["decisions"]] == ["AAPL"]

    def test_the_universe_is_bounded(self, stocks, monkeypatch):
        # A 500-symbol universe would fan out into 500 upstream fetches.
        seen = {}

        def fake(symbols):
            seen["n"] = len(symbols)
            return []

        monkeypatch.setattr(app, "fetch_stocks", fake)
        app.paper_scan(a_strategy(universe=[f"SYM{i}" for i in range(500)]), {})
        assert seen["n"] <= app.MAX_PAPER_SYMBOLS

    def test_rows_with_errors_are_ignored(self, stocks):
        stocks.append({"symbol": "AAPL", "error": "upstream down"})
        assert app.paper_scan(a_strategy(), {})["decisions"] == []

    def test_a_missing_reading_never_produces_an_entry(self, stocks):
        # No RSI at all — the rule mentions it, so it cannot be satisfied.
        row = a_row()
        row["signal"] = {"label": "STRONG BUY"}
        stocks.append(row)
        assert app.paper_scan(a_strategy(), {})["decisions"][0]["entry"] is False
