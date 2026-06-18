"""Turn MarketPulse signals into trade PROPOSALS (never direct orders).

Reuses the exact same signal engine the dashboard shows the human
(app.fetch_stocks / app.fetch_crypto -> indicators.score_signals), so what the
agent proposes is identical to what you'd see on screen. No hidden second brain.

Rules (kept intentionally strict):
  ENTRY  buy  only on a STRONG BUY label AND we don't already hold it
  EXIT   sell only when we hold it AND the label flips to SELL / STRONG SELL
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


def _held_symbols() -> set[str]:
    """Set of symbols we currently hold, normalized to slashless crypto form."""
    try:
        import broker
        return {p["symbol"].replace("/", "") for p in broker.positions()}
    except Exception:  # noqa: BLE001 — proposing must work even offline
        return set()


def _pending_symbols() -> set[str]:
    return {p["symbol"] for p in store.load_proposals() if p["status"] == "pending"}


def _make_proposal(kind: str, symbol: str, side: str, sig: dict,
                   price: float | None) -> dict:
    notional = min(config.PER_TRADE_USD, config.MAX_SINGLE_TX_USD)
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
              held: set[str], pending: set[str]) -> dict | None:
    label = sig.get("label")
    slashless = symbol.replace("/", "")
    if symbol in pending:
        return None
    is_held = slashless in held
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

    held = _held_symbols()
    pending = _pending_symbols()
    new: list[dict] = []

    # Stocks
    for row in app.fetch_stocks(config.STOCK_UNIVERSE):
        if row.get("error"):
            continue
        p = _consider("stock", row["symbol"], row["signal"], row.get("price"),
                      held, pending)
        if p:
            new.append(p)

    # Crypto — the engine wants the CoinGecko id; the proposal carries the
    # Alpaca pair. CRYPTO_UNIVERSE maps {pair -> coingecko id}, so fetch per id
    # and propose under the pair, keeping the id->pair mapping exact.
    for pair, cg_id in config.CRYPTO_UNIVERSE.items():
        rows = app.fetch_crypto([cg_id])
        if not rows:
            continue
        p = _consider("crypto", pair, rows[0]["signal"], rows[0].get("price"),
                      held, pending)
        if p:
            new.append(p)

    for p in new:
        store.add_proposal(p)
        store.audit("proposed", {"id": p["id"], "symbol": p["symbol"],
                                 "side": p["side"], "label": p["label"],
                                 "score": p["score"]})
    return new
