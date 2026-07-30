"""User-declared trading rules.

This is the layer that decides whether a trade gets proposed at all, so the
tests lean hard on the failure directions: a missing reading, a nonsense
comparison, or an empty rule block must all resolve to "no trade". Anything
that resolves the other way would put money behind a mistake.
"""

import json

import pytest

import strategy

pytestmark = pytest.mark.unit


SIGNAL = {
    "score": 4, "label": "STRONG BUY", "rsi": 61.2, "macd_hist": 0.42,
    "stoch": 70.0, "pct_b": 0.81, "sma": 190.0, "sma200": 175.0, "htf": 1,
}
GUIDES = {"ma5": 193.0, "ma14": 191.0, "ma21": 188.0, "stack": "bull",
          "above_ma5": True, "vwap": 192.0}
SQUEEZE = {"state": "fired", "bars": 6, "mom": "bull", "accel": "rising"}


def a_strategy(**over):
    doc = {
        "name": "Test rules",
        "kind": "stock",
        "universe": ["AAPL"],
        "entry": {"all": [["rsi", "<", 70]]},
        "exit": {"any": [["rsi", ">", 80]]},
        "sizing": {"notional": 50, "max_open": 3},
    }
    doc.update(over)
    return doc


class TestFactsFrom:
    def test_flattens_every_source(self):
        facts = strategy.facts_from(SIGNAL, price=194.0, guides=GUIDES, squeeze=SQUEEZE)
        assert facts["rsi"] == 61.2
        assert facts["label"] == "STRONG BUY"
        assert facts["stack"] == "bull"
        assert facts["squeeze_state"] == "fired"
        assert facts["squeeze_bars"] == 6
        assert facts["price"] == 194.0

    def test_derives_above_vwap_from_price(self):
        assert strategy.facts_from(SIGNAL, 194.0, GUIDES)["above_vwap"] is True
        assert strategy.facts_from(SIGNAL, 190.0, GUIDES)["above_vwap"] is False

    def test_missing_readings_are_absent_not_zero(self):
        # A zero would look like a real reading and could satisfy "rsi < 30".
        facts = strategy.facts_from({"label": "NEUTRAL"}, price=None)
        assert "rsi" not in facts
        assert "price" not in facts

    def test_survives_empty_inputs(self):
        assert strategy.facts_from({}, None, None, None) == {}


class TestConditions:
    @pytest.mark.parametrize("op,value,expected", [
        ("<", 70, True), ("<", 50, False),
        (">", 50, True), (">", 70, False),
        ("<=", 61.2, True), (">=", 61.2, True),
        ("==", 61.2, True), ("!=", 61.2, False),
    ])
    def test_numeric_operators(self, op, value, expected):
        facts = {"rsi": 61.2}
        group = {"all": [["rsi", op, value]]}
        assert strategy.group_holds(group, facts) is expected

    def test_in_and_not_in(self):
        facts = {"label": "STRONG BUY"}
        assert strategy.group_holds({"all": [["label", "in", ["BUY", "STRONG BUY"]]]}, facts)
        assert not strategy.group_holds({"all": [["label", "not in", ["BUY", "STRONG BUY"]]]}, facts)

    def test_a_missing_field_never_matches(self):
        # The reading we need simply isn't there — that is not an entry.
        assert not strategy.group_holds({"all": [["rsi", "<", 70]]}, {"label": "BUY"})

    def test_a_type_mismatch_never_matches_and_never_raises(self):
        # Comparing a label to a number is a mistake; the safe reading is False.
        facts = {"label": "STRONG BUY"}
        assert strategy.group_holds({"all": [["label", "<", 70]]}, facts) is False

    def test_all_requires_every_condition(self):
        facts = {"rsi": 61.2, "stack": "bear"}
        group = {"all": [["rsi", "<", 70], ["stack", "==", "bull"]]}
        assert strategy.group_holds(group, facts) is False

    def test_any_requires_one(self):
        facts = {"rsi": 61.2, "stack": "bear"}
        group = {"any": [["rsi", "<", 70], ["stack", "==", "bull"]]}
        assert strategy.group_holds(group, facts) is True

    @pytest.mark.parametrize("group", [None, {}, {"all": []}, {"any": []}, {"nope": [1]}])
    def test_an_empty_group_is_never_true(self, group):
        # "No rule" must never mean "always buy".
        assert strategy.group_holds(group, {"rsi": 50}) is False


class TestEntrySignal:
    def test_fires_when_conditions_hold(self):
        doc = a_strategy(entry={"all": [["squeeze_state", "==", "fired"],
                                        ["stack", "==", "bull"],
                                        ["rsi", "<", 70]]})
        facts = strategy.facts_from(SIGNAL, 194.0, GUIDES, SQUEEZE)
        assert strategy.entry_signal(doc, facts) is True

    def test_does_not_fire_when_one_condition_fails(self):
        doc = a_strategy(entry={"all": [["squeeze_state", "==", "fired"],
                                        ["rsi", "<", 50]]})
        facts = strategy.facts_from(SIGNAL, 194.0, GUIDES, SQUEEZE)
        assert strategy.entry_signal(doc, facts) is False

    def test_a_strategy_with_no_entry_never_fires(self):
        assert strategy.entry_signal({"name": "x"}, {"rsi": 10}) is False


class TestExitSignal:
    def test_stop_loss_fires_on_the_downside(self):
        doc = a_strategy(exit={"stop_loss_pct": 8})
        hit, why = strategy.exit_signal(doc, {"price": 91.0}, entry_price=100.0)
        assert hit is True
        assert "stop loss" in why

    def test_stop_loss_does_not_fire_above_the_threshold(self):
        doc = a_strategy(exit={"stop_loss_pct": 8})
        hit, _ = strategy.exit_signal(doc, {"price": 93.0}, entry_price=100.0)
        assert hit is False

    def test_take_profit_fires_on_the_upside(self):
        doc = a_strategy(exit={"take_profit_pct": 15})
        hit, why = strategy.exit_signal(doc, {"price": 116.0}, entry_price=100.0)
        assert hit is True
        assert "take profit" in why

    def test_a_protective_exit_outranks_the_rule_block(self):
        # Both could match; the stop must win, because an indicator condition
        # must never be able to keep a losing position open.
        doc = a_strategy(exit={"any": [["rsi", ">", 80]], "stop_loss_pct": 8})
        hit, why = strategy.exit_signal(doc, {"price": 80.0, "rsi": 10}, entry_price=100.0)
        assert hit is True
        assert "stop loss" in why

    def test_rule_block_fires_on_its_own(self):
        doc = a_strategy(exit={"any": [["label", "in", ["SELL", "STRONG SELL"]]]})
        hit, why = strategy.exit_signal(doc, {"label": "SELL"}, entry_price=100.0)
        assert hit is True
        assert why == "exit rule matched"

    def test_no_exit_when_nothing_matches(self):
        doc = a_strategy(exit={"any": [["rsi", ">", 80]], "stop_loss_pct": 8})
        hit, why = strategy.exit_signal(doc, {"price": 101.0, "rsi": 50}, entry_price=100.0)
        assert hit is False
        assert why == ""

    def test_percent_exits_are_skipped_without_an_entry_price(self):
        # Nothing to measure against; must not guess.
        doc = a_strategy(exit={"stop_loss_pct": 8})
        assert strategy.exit_signal(doc, {"price": 10.0}, entry_price=None)[0] is False


class TestValidate:
    def test_accepts_a_sound_strategy(self):
        assert strategy.validate(a_strategy()) == []

    def test_the_shipped_template_is_valid(self):
        # The starting point we hand people must itself pass validation.
        assert strategy.validate(strategy.TEMPLATE) == []

    def test_rejects_a_non_object(self):
        assert strategy.validate("nope")

    def test_requires_a_name(self):
        assert any("name" in e for e in strategy.validate(a_strategy(name="")))

    def test_requires_a_universe(self):
        assert any("universe" in e for e in strategy.validate(a_strategy(universe=[])))

    def test_requires_an_entry(self):
        doc = a_strategy()
        del doc["entry"]
        assert any("entry" in e for e in strategy.validate(doc))

    def test_rejects_an_unknown_kind(self):
        assert any("kind" in e for e in strategy.validate(a_strategy(kind="bonds")))

    def test_rejects_an_unknown_field_and_names_the_valid_ones(self):
        errors = strategy.validate(a_strategy(entry={"all": [["rsy", "<", 70]]}))
        assert errors
        # A typo must fail loudly at load, with the vocabulary attached, rather
        # than silently never matching at 3am.
        assert "rsy" in errors[0] and "rsi" in errors[0]

    def test_rejects_an_unknown_operator(self):
        errors = strategy.validate(a_strategy(entry={"all": [["rsi", "=~", 70]]}))
        assert any("operator" in e for e in errors)

    def test_rejects_a_malformed_condition(self):
        errors = strategy.validate(a_strategy(entry={"all": [["rsi", "<"]]}))
        assert any("[field, operator, value]" in e for e in errors)

    def test_in_requires_a_list(self):
        errors = strategy.validate(a_strategy(entry={"all": [["label", "in", "BUY"]]}))
        assert any("needs a list" in e for e in errors)

    def test_requires_exactly_one_of_all_or_any(self):
        errors = strategy.validate(a_strategy(entry={"all": [["rsi", "<", 70]],
                                                    "any": [["rsi", ">", 5]]}))
        assert any("exactly one" in e for e in errors)

    @pytest.mark.parametrize("bad", [0, -5, "eight"])
    def test_rejects_nonsense_percentages(self, bad):
        errors = strategy.validate(a_strategy(exit={"stop_loss_pct": bad}))
        assert any("stop_loss_pct" in e for e in errors)

    @pytest.mark.parametrize("bad", [0, -1, 2.5])
    def test_rejects_nonsense_max_open(self, bad):
        errors = strategy.validate(a_strategy(sizing={"max_open": bad}))
        assert any("max_open" in e for e in errors)

    def test_reports_every_problem_at_once(self):
        # Fixing a config one exception at a time is miserable.
        errors = strategy.validate({"universe": [], "entry": {"all": [["nope", "?!", 1]]}})
        assert len(errors) >= 3


class TestLoad:
    def test_loads_a_valid_file(self, tmp_path):
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(a_strategy()), encoding="utf-8")
        assert strategy.load(str(path))["name"] == "Test rules"

    def test_missing_file_says_how_to_create_one(self, tmp_path):
        with pytest.raises(strategy.StrategyError) as exc:
            strategy.load(str(tmp_path / "absent.json"))
        assert "strategy init" in str(exc.value)

    def test_broken_json_is_reported_as_such(self, tmp_path):
        path = tmp_path / "strategy.json"
        path.write_text("{ not json", encoding="utf-8")
        with pytest.raises(strategy.StrategyError) as exc:
            strategy.load(str(path))
        assert "not valid JSON" in str(exc.value)

    def test_an_invalid_strategy_refuses_to_load(self, tmp_path):
        # Better to refuse at startup than to trade a misunderstood rule.
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps({"name": "x"}), encoding="utf-8")
        with pytest.raises(strategy.StrategyError) as exc:
            strategy.load(str(path))
        assert "problem" in str(exc.value)
