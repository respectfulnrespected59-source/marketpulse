"""Turn MarketPulse signals into trade PROPOSALS (never direct orders).

Reuses the exact same signal engine the dashboard shows the human
(app.fetch_stocks / app.fetch_crypto -> indicators.score_signals), so what the
agent proposes is identical to what you'd see on screen. No hidden second brain.

Which rules run:
  * If agent/strategy.json exists, YOUR declared entry and exit conditions run,
    over YOUR declared universe, at YOUR declared size.
  * If it does not exist, a deliberately strict built-in demo rule runs instead:
    buy only on STRONG BUY when flat, sell only on SELL / STRONG SELL when held.

If the file exists but does not validate, nothing is proposed at all. Falling
back to the built-in rule there would quietly trade a system the user did not
write, which is worse than proposing nothing.

A pending proposal for the same symbol is never duplicated.
"""
from __future__ import annotations

import os
import sys
import time

import config
import guardrails
import store

# The signal engine lives one directory up (the MarketPulse root).
_ROOT = os.path.dirname(config.HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import app  # noqa: E402  (provides fetch_stocks / fetch_crypto with signals)
import strategy  # noqa: E402  (the rule engine lives at the root, beside app)


def _held_symbols() -> set[str]:
    """Set of symbols we currently hold, normalized to slashless crypto form."""
    try:
        import broker
        return {p["symbol"].replace("/", "") for p in broker.positions()}
    except Exception:  # noqa: BLE001 — proposing must work even offline
        return set()


def _pending_symbols() -> set[str]:
    return {p["symbol"] for p in store.load_proposals() if p["status"] == "pending"}


def load_strategy() -> dict | None:
    """The trader's rules, or None when they haven't declared any.

    Raises StrategyError if a file exists but is unusable — the caller stops
    rather than silently trading the built-in rule under their name.
    """
    path = os.path.join(config.HERE, strategy.STRATEGY_FILENAME)
    if not os.path.isfile(path):
        return None
    return strategy.load(path)


def _entry_price(slashless: str) -> float | None:
    """Average fill of the open position, for percentage stops and targets.

    None when it can't be read — strategy.exit_signal then skips the percentage
    exits rather than measuring against a guess.
    """
    try:
        import broker
        for pos in broker.positions():
            if pos["symbol"].replace("/", "") == slashless:
                return float(pos.get("avg_entry_price") or 0) or None
    except Exception:  # noqa: BLE001 — a read failure must not stop proposing
        return None
    return None


def _make_proposal(kind: str, symbol: str, side: str, sig: dict,
                   price: float | None, notional_override: float | None = None) -> dict:
    # The declared size is still only a request: guardrails.check_spend caps it
    # at the per-trade and daily limits before anything can be sent.
    wanted = notional_override if notional_override else config.PER_TRADE_USD
    notional = min(wanted, config.MAX_SINGLE_TX_USD)
    ts = int(time.time())
    return {
        "id": f"p-{ts}-{symbol.replace('/', '')}",
        "ts": ts,
        "kind": kind,
        "symbol": symbol,
        "side": side,
        "notional": str(notional) if side == "buy" else None,  # sells close qty
        "ref_price": float(price) if price else None,  # anchors the slippage gate
        "label": sig.get("label"),
        "score": sig.get("score"),
        "reasons": sig.get("reasons", []),
        "status": "pending",
        "broker_order_id": None,
        "note": "",
    }


def _consider(kind: str, symbol: str, sig: dict, price: float | None,
              held: set[str], pending: set[str], strat: dict | None = None,
              guides: dict | None = None, squeeze: dict | None = None,
              room: bool = True) -> dict | None:
    slashless = symbol.replace("/", "")
    if symbol in pending:
        return None
    is_held = slashless in held

    if strat:
        facts = strategy.facts_from(sig, price, guides, squeeze)
        if not is_held:
            # `room` is False once max_open positions are already committed.
            if room and strategy.entry_signal(strat, facts):
                sizing = strat.get("sizing") or {}
                return _make_proposal(kind, symbol, "buy", sig, price,
                                      sizing.get("notional"))
            return None
        hit, why = strategy.exit_signal(strat, facts, _entry_price(slashless))
        if hit:
            proposal = _make_proposal(kind, symbol, "sell", sig, price)
            proposal["note"] = why       # the audit log records WHY it exited
            return proposal
        return None

    # No declared rules — the shipped demo rule.
    label = sig.get("label")
    if label in config.ENTRY_LABELS and not is_held:
        return _make_proposal(kind, symbol, "buy", sig, price)
    if label in config.EXIT_LABELS and is_held:
        return _make_proposal(kind, symbol, "sell", sig, price)
    return None


def scan() -> list[dict]:
    """Compute fresh signals, emit new proposals, persist + audit them.

    Returns the list of newly created proposals (may be empty).
    """
    # Circuit-breaker pre-check against real equity, when keys are available.
    if config.keys_present():
        try:
            import broker
            equity = float(broker.account().get("equity", 0) or 0)
            guardrails.update_equity_and_check(equity)
        except guardrails.CircuitBreakerError:
            store.audit("scan_blocked", {"reason": "circuit breaker"})
            return []
        except Exception:  # noqa: BLE001 — never let a read error stop proposing
            pass

    if store.is_halted():
        store.audit("scan_blocked", {"reason": "halted"})
        return []

    # A declared strategy replaces both the rules and the universe. A broken
    # one stops the scan outright rather than trading the built-in rule under
    # the trader's name.
    try:
        strat = load_strategy()
    except strategy.StrategyError as exc:
        store.audit("scan_blocked", {"reason": "invalid strategy",
                                     "error": str(exc)})
        return []

    held = _held_symbols()
    pending = _pending_symbols()
    new: list[dict] = []

    # Respect the declared position cap. Every buy proposed in this pass counts
    # against it too, or one scan could queue up far more than max_open. Exits
    # are never blocked by the cap.
    max_open = None
    if strat:
        declared_cap = (strat.get("sizing") or {}).get("max_open")
        if declared_cap:
            max_open = int(declared_cap)
    committed = len(held) + len(pending)

    def has_room() -> bool:
        return max_open is None or committed < max_open

    stock_universe = config.STOCK_UNIVERSE
    crypto_universe = config.CRYPTO_UNIVERSE
    if strat:
        declared = [s.strip() for s in strat.get("universe", []) if s and s.strip()]
        if strat.get("kind", "stock") == "crypto":
            stock_universe = []
            crypto_universe = {s: s.lower() for s in declared}
        else:
            stock_universe = declared
            crypto_universe = {}

    # Stocks
    for row in (app.fetch_stocks(stock_universe) if stock_universe else []):
        if row.get("error"):
            continue
        p = _consider("stock", row["symbol"], row["signal"], row.get("price"),
                      held, pending, strat, row.get("guides"), row.get("squeeze"),
                      has_room())
        if p:
            new.append(p)
            if p["side"] == "buy":
                committed += 1

    # Crypto — the engine wants the CoinGecko id; the proposal carries the
    # Alpaca pair. CRYPTO_UNIVERSE maps {pair -> coingecko id}, so fetch per id
    # and propose under the pair, keeping the id->pair mapping exact.
    for pair, cg_id in crypto_universe.items():
        rows = app.fetch_crypto([cg_id])
        if not rows:
            continue
        # Crypto rows carry no MA-stack or squeeze guides, so rules that name
        # those facts simply won't match — which is the safe direction.
        p = _consider("crypto", pair, rows[0]["signal"], rows[0].get("price"),
                      held, pending, strat, None, None, has_room())
        if p:
            new.append(p)
            if p["side"] == "buy":
                committed += 1

    for p in new:
        store.add_proposal(p)
        store.audit("proposed", {"id": p["id"], "symbol": p["symbol"],
                                 "side": p["side"], "label": p["label"],
                                 "score": p["score"], "note": p.get("note", "")})
    return new
