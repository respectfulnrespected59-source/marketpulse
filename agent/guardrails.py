"""Independent safety controls — enforced BEFORE any order is sent.

Layered defenses from the llm-trading-agent-security skill. Each check is
independent: prompt/signal output never decides whether a trade is allowed,
these functions do. If any raises, the order does not go out.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal

import config
import store


class GuardrailError(Exception):
    """Base: an order was refused by a safety control."""


class SpendLimitError(GuardrailError):
    pass


class CircuitBreakerError(GuardrailError):
    pass


class HaltError(GuardrailError):
    pass


class StaleProposalError(GuardrailError):
    pass


class SlippageError(GuardrailError):
    pass


class DisallowedSymbolError(GuardrailError):
    pass


# --------------------------------------------------------------- spend limits
def check_spend(usd: Decimal) -> None:
    """Per-trade ceiling + 24h rolling daily ceiling. Does NOT record;
    recording happens only after a successful send (see record_spend)."""
    if usd <= 0:
        raise SpendLimitError(f"Non-positive notional: {usd}")
    if usd > config.MAX_SINGLE_TX_USD:
        raise SpendLimitError(
            f"${usd} exceeds per-trade cap ${config.MAX_SINGLE_TX_USD}")
    daily = Decimal(str(store.spend_last_24h()))
    if daily + usd > config.MAX_DAILY_SPEND_USD:
        raise SpendLimitError(
            f"24h spend ${daily} + ${usd} exceeds daily cap "
            f"${config.MAX_DAILY_SPEND_USD}")


def record_spend(usd: Decimal, symbol: str, order_id: str | None) -> None:
    store.record_spend(str(usd), symbol, order_id)


# --------------------------------------------------------------- kill switch
def check_not_halted() -> None:
    if store.is_halted():
        state = store.load_circuit()
        raise HaltError(f"Trading halted: {state.get('reason') or 'manual kill switch'}")


# --------------------------------------------------------------- staleness
def check_fresh(proposal: dict) -> None:
    age = time.time() - proposal.get("ts", 0)
    if age > config.PROPOSAL_TTL:
        raise StaleProposalError(
            f"Proposal {proposal['id']} is {int(age)}s old "
            f"(> {config.PROPOSAL_TTL}s); signal has gone stale")


# --------------------------------------------------------------- allow-list
def check_symbol_allowed(proposal: dict) -> None:
    """Re-validate the symbol against the configured universe at send time.

    The chokepoint must not trust the proposal record: a corrupted or tampered
    queue could name any ticker. We independently confirm it is one we are
    permitted to trade (security skill: enforce independently of upstream)."""
    symbol = proposal.get("symbol", "")
    if symbol not in config.allowed_symbols():
        raise DisallowedSymbolError(
            f"Symbol {symbol!r} is not in the allowed universe")


# --------------------------------------------------------------- slippage
def check_slippage(proposal: dict, current_price: float) -> None:
    """The stock/crypto analog of a mandatory `min_amount_out`.

    Compare the live price against the reference price captured when the signal
    fired. Refuse if the market has moved against the proposed side by more than
    the per-strategy band. Buys are hurt by a higher price, sells by a lower one.
    """
    ref = float(proposal.get("ref_price") or 0)
    if ref <= 0:
        raise SlippageError(
            f"Proposal {proposal['id']} has no reference price to bound slippage")
    if current_price <= 0:
        raise SlippageError("Live price unavailable; refusing to send blind")

    band = config.MAX_SLIPPAGE_PCT.get(proposal.get("kind", ""), 0.005)
    move = (current_price - ref) / ref
    adverse = move if proposal["side"] == "buy" else -move
    if adverse > band:
        raise SlippageError(
            f"{proposal['symbol']} moved {move:+.2%} since signal "
            f"(ref ${ref:g} -> live ${current_price:g}); adverse {adverse:+.2%} "
            f"exceeds {band:.2%} band")


# --------------------------------------------------------------- circuit breaker
def update_equity_and_check(equity: float) -> None:
    """Roll the daily window, then halt if daily drawdown breaches the limit.

    Call this with the account's current equity before producing proposals.
    Consecutive-loss tracking is updated separately via record_trade_result.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = store.load_circuit()

    if state.get("day") != today or state.get("day_start_equity", 0) <= 0:
        state = {**state, "day": today, "day_start_equity": equity}
        store.save_circuit(state)
        return

    start = state["day_start_equity"]
    if start <= 0:
        return
    drawdown = (equity - start) / start
    if drawdown <= -config.MAX_DAILY_LOSS_PCT:
        store.engage_halt(
            f"Daily drawdown {drawdown:.1%} breached "
            f"-{config.MAX_DAILY_LOSS_PCT:.0%} limit")
        raise CircuitBreakerError(f"Daily drawdown {drawdown:.1%} — trading halted")


def record_trade_result(is_win: bool) -> None:
    """Track consecutive losses; halt after the configured streak."""
    state = store.load_circuit()
    losses = 0 if is_win else state.get("consecutive_losses", 0) + 1
    store.save_circuit({**state, "consecutive_losses": losses})
    if losses >= config.MAX_CONSECUTIVE_LOSSES:
        store.engage_halt(f"{losses} consecutive losses")


# --------------------------------------------------------------- full gate
def authorize_send(proposal: dict, current_price: float | None = None) -> None:
    """Run every independent control. Raises GuardrailError if any fails.

    This is the single chokepoint every order must pass. Order of checks is
    deliberate: cheap/global first, then market-move, then money checks.

    `current_price` is a freshly pulled live price (see broker.latest_price).
    It is REQUIRED — omitting it means we cannot bound slippage, so we fail
    closed rather than send blind.
    """
    check_not_halted()
    check_symbol_allowed(proposal)
    check_fresh(proposal)
    if current_price is None:
        raise SlippageError(
            "No live price supplied to authorize_send; refusing to send blind")
    check_slippage(proposal, current_price)
    if proposal["side"] == "buy":  # sells reduce exposure; don't spend-cap exits
        check_spend(Decimal(str(proposal["notional"])))
    store.audit("authorized", {"id": proposal["id"], "symbol": proposal["symbol"],
                               "side": proposal["side"], "notional": proposal["notional"],
                               "ref_price": proposal.get("ref_price"),
                               "live_price": current_price})
