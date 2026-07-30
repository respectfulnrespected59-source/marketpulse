"""User-declared trading rules — the thing that makes this YOUR system.

The agent used to trade one hardcoded rule: buy on STRONG BUY, sell when the
signal flips. That is fine as a demo and useless as a product, because it is
somebody else's opinion. This module lets a trader write their own entries and
exits in a small, boring, checkable format, and the agent executes exactly
those — nothing implied, nothing inferred.

Deliberately narrow. A condition is [field, operator, value]; conditions group
under "all" (every one must hold) or "any" (one is enough). There is no nesting,
no arithmetic, no expression language. If a rule cannot be said in this
vocabulary, the honest answer is to write Python against `facts_from()` rather
than for me to invent a language — a half-built DSL in an order path is a
liability, not a feature.

Nothing here places an order or decides size on its own. It answers one
question: do this trader's conditions hold right now? Every order still passes
guardrails.authorize_send, which is the only chokepoint that can send.
"""

from __future__ import annotations

import json
import os

# Every fact a rule may reference, and where it comes from. Anything outside
# this list is rejected at validation time with the list attached, so a typo
# fails loudly on load instead of silently never matching at 3am.
FIELDS: dict[str, str] = {
    # composite signal engine (indicators.score_signals)
    "score": "Composite signal score, negative bearish to positive bullish",
    "label": "STRONG BUY / BUY / NEUTRAL / SELL / STRONG SELL",
    "rsi": "Relative strength index, 0-100",
    "macd_hist": "MACD histogram; positive = bullish momentum",
    "stoch": "Stochastic %K, 0-100",
    "pct_b": "Bollinger %B; 0 = lower band, 1 = upper band",
    "sma": "50-period simple moving average",
    "sma200": "200-period simple moving average",
    "htf": "Higher-timeframe trend: 1 up, -1 down, 0 flat",
    # moving-average stack (indicators.ma_stack)
    "ma5": "5-period moving average",
    "ma14": "14-period moving average",
    "ma21": "21-period moving average",
    "stack": "MA stack alignment: bull / bear / mixed",
    "above_ma5": "True when price is above the 5-period MA",
    # TTM squeeze (indicators.ttm_squeeze)
    "squeeze_state": "Volatility squeeze: on / fired / off",
    "squeeze_bars": "How many bars the squeeze has been on",
    "squeeze_mom": "Squeeze momentum: bull / bear / neutral",
    "squeeze_accel": "Momentum acceleration: rising / falling / fading",
    # price context
    "price": "Latest price",
    "vwap": "Session VWAP",
    "above_vwap": "True when price is above session VWAP",
}

# Operators a rule may use. No arithmetic, no function calls.
OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "in", "not in")

GROUPS = ("all", "any")

STRATEGY_FILENAME = "strategy.json"


class StrategyError(ValueError):
    """Raised when a strategy file cannot be trusted to run."""


# --------------------------------------------------------------- facts

def facts_from(signal: dict, price: float | None = None,
               guides: dict | None = None, squeeze: dict | None = None) -> dict:
    """Flatten the indicator payloads into the names rules can reference.

    Missing inputs yield missing facts rather than zeros — a rule that mentions
    a fact we do not have simply does not match, which is the safe direction.
    A zero would look like a real reading and could fire an entry.
    """
    facts: dict = {}
    for key in ("score", "label", "rsi", "macd_hist", "stoch", "pct_b",
                "sma", "sma200", "htf"):
        if signal and signal.get(key) is not None:
            facts[key] = signal[key]

    if guides:
        for key in ("ma5", "ma14", "ma21", "stack", "above_ma5"):
            if guides.get(key) is not None:
                facts[key] = guides[key]
        if guides.get("vwap") is not None:
            facts["vwap"] = guides["vwap"]
            if price is not None:
                facts["above_vwap"] = price > guides["vwap"]

    if squeeze:
        if squeeze.get("state") is not None:
            facts["squeeze_state"] = squeeze["state"]
        if squeeze.get("bars") is not None:
            facts["squeeze_bars"] = squeeze["bars"]
        if squeeze.get("mom") is not None:
            facts["squeeze_mom"] = squeeze["mom"]
        if squeeze.get("accel") is not None:
            facts["squeeze_accel"] = squeeze["accel"]

    if price is not None:
        facts["price"] = price
    return facts


# ---------------------------------------------------------- evaluation

def _compare(left, op: str, right) -> bool:
    """Apply one operator, treating any type mismatch as 'did not match'.

    A rule comparing a string label to a number is a mistake, but at runtime
    the safe reading of a mistake is False — never fire an order because two
    incomparable things raised.
    """
    try:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == "in":
            return left in right
        if op == "not in":
            return left not in right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
    except TypeError:
        return False
    return False


def _condition_holds(cond: list, facts: dict) -> bool:
    field, op, value = cond[0], cond[1], cond[2]
    if field not in facts:
        return False            # unknown reading -> not a match, never an entry
    return _compare(facts[field], op, value)


def group_holds(group: dict | None, facts: dict) -> bool:
    """Evaluate an {"all"|"any": [...]} block against the current facts.

    An empty or absent group is False for entries — "no rule" must never mean
    "always buy".
    """
    if not group:
        return False
    if "all" in group:
        conds = group["all"]
        return bool(conds) and all(_condition_holds(c, facts) for c in conds)
    if "any" in group:
        conds = group["any"]
        return bool(conds) and any(_condition_holds(c, facts) for c in conds)
    return False


def entry_signal(strategy: dict, facts: dict) -> bool:
    """True when this trader's entry conditions hold right now."""
    return group_holds(strategy.get("entry"), facts)


def exit_signal(strategy: dict, facts: dict,
                entry_price: float | None = None) -> tuple[bool, str]:
    """True when the position should be closed, plus the reason why.

    Stop-loss and take-profit are checked before the rule block, because a
    protective exit should never be outvoted by an indicator condition.
    """
    exit_rules = strategy.get("exit") or {}
    price = facts.get("price")

    if entry_price and price:
        stop = exit_rules.get("stop_loss_pct")
        if stop and price <= entry_price * (1 - float(stop) / 100.0):
            return True, f"stop loss {stop}%"
        target = exit_rules.get("take_profit_pct")
        if target and price >= entry_price * (1 + float(target) / 100.0):
            return True, f"take profit {target}%"

    block = {k: v for k, v in exit_rules.items() if k in GROUPS}
    if block and group_holds(block, facts):
        return True, "exit rule matched"
    return False, ""


# ---------------------------------------------------------- validation

def validate(doc: object) -> list[str]:
    """Return every problem with a strategy document, or [] when it is sound.

    Reports all errors at once, not just the first — fixing a config one
    exception at a time is miserable.
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["strategy must be a JSON object"]

    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name: required, must be a non-empty string")

    kind = doc.get("kind", "stock")
    if kind not in ("stock", "crypto"):
        errors.append(f"kind: must be 'stock' or 'crypto', got {kind!r}")

    universe = doc.get("universe")
    if not isinstance(universe, list) or not universe:
        errors.append("universe: required, must be a non-empty list of symbols")
    elif not all(isinstance(s, str) and s.strip() for s in universe):
        errors.append("universe: every symbol must be a non-empty string")

    if "entry" not in doc:
        errors.append("entry: required — a strategy with no entry never trades")
    else:
        errors += _validate_group("entry", doc.get("entry"))

    exit_rules = doc.get("exit")
    if exit_rules is not None:
        if not isinstance(exit_rules, dict):
            errors.append("exit: must be an object")
        else:
            block = {k: v for k, v in exit_rules.items() if k in GROUPS}
            if block:
                errors += _validate_group("exit", block)
            for pct_key in ("stop_loss_pct", "take_profit_pct"):
                if pct_key in exit_rules:
                    val = exit_rules[pct_key]
                    if not isinstance(val, (int, float)) or val <= 0:
                        errors.append(f"exit.{pct_key}: must be a positive number")

    sizing = doc.get("sizing")
    if sizing is not None:
        if not isinstance(sizing, dict):
            errors.append("sizing: must be an object")
        else:
            notional = sizing.get("notional")
            if notional is not None and (
                not isinstance(notional, (int, float)) or notional <= 0
            ):
                errors.append("sizing.notional: must be a positive number")
            max_open = sizing.get("max_open")
            if max_open is not None and (
                not isinstance(max_open, int) or max_open < 1
            ):
                errors.append("sizing.max_open: must be an integer of at least 1")
    return errors


def _validate_group(where: str, group: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(group, dict):
        return [f"{where}: must be an object with 'all' or 'any'"]

    keys = [k for k in group if k in GROUPS]
    if len(keys) != 1:
        return [f"{where}: needs exactly one of 'all' or 'any'"]

    conds = group[keys[0]]
    if not isinstance(conds, list) or not conds:
        return [f"{where}.{keys[0]}: must be a non-empty list of conditions"]

    for i, cond in enumerate(conds):
        label = f"{where}.{keys[0]}[{i}]"
        if not isinstance(cond, list) or len(cond) != 3:
            errors.append(f"{label}: must be [field, operator, value]")
            continue
        field, op, value = cond
        if field not in FIELDS:
            errors.append(
                f"{label}: unknown field {field!r}. Available: "
                + ", ".join(sorted(FIELDS))
            )
        if op not in OPERATORS:
            errors.append(
                f"{label}: unknown operator {op!r}. Available: "
                + ", ".join(OPERATORS)
            )
        if op in ("in", "not in") and not isinstance(value, list):
            errors.append(f"{label}: '{op}' needs a list on the right")
    return errors


# ------------------------------------------------------------- loading

def load(path: str | None = None) -> dict:
    """Read and validate a strategy file. Raises StrategyError if unusable."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                STRATEGY_FILENAME)
    if not os.path.isfile(path):
        raise StrategyError(
            f"No strategy at {path}. Run `python cli.py strategy init` to "
            "write a documented starting point."
        )
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as exc:
        raise StrategyError(f"{path} is not valid JSON: {exc}") from exc

    errors = validate(doc)
    if errors:
        raise StrategyError(
            f"{path} has {len(errors)} problem(s):\n  - " + "\n  - ".join(errors)
        )
    return doc


# A starting point that is deliberately conservative and obviously editable.
# It is a template, not a recommendation — the comments say so plainly.
TEMPLATE = {
    "_readme": [
        "Your rules. The agent executes exactly these — nothing implied.",
        "A condition is [field, operator, value]. Group under 'all' or 'any'.",
        "Run `python cli.py strategy fields` to list every field you can use.",
        "Run `python cli.py strategy validate` after every edit.",
        "This template is an EXAMPLE, not advice. Backtest it, then paper it.",
    ],
    "name": "Squeeze breakout (example — edit me)",
    "kind": "stock",
    "universe": ["TSLA", "NVDA", "MU"],
    "entry": {
        "all": [
            ["squeeze_state", "==", "fired"],
            ["stack", "==", "bull"],
            ["rsi", "<", 70],
        ]
    },
    "exit": {
        "any": [
            ["label", "in", ["SELL", "STRONG SELL"]],
            ["rsi", ">", 80],
        ],
        "stop_loss_pct": 8,
        "take_profit_pct": 15,
    },
    "sizing": {"notional": 50, "max_open": 3},
}
