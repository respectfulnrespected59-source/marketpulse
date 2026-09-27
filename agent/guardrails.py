"""Independent safety controls — enforced BEFORE any order is sent.

Layered defenses from the llm-trading-agent-security skill. Each check is
independent: prompt/signal output never decides whether a trade is allowed,
these functions do. If any raises, the order does not go out.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import agent_config as config
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


class MarketClosedError(GuardrailError):
    pass


class LiveNotPermittedError(GuardrailError):
    pass


# --------------------------------------------------------------- spend limits
def check_spend(usd: Decimal, mode: str = "paper") -> None:
    """Per-trade ceiling + 24h rolling daily ceiling for this mode (live is
    clamped to the hard ceilings in agent_config.caps). Does NOT record;
    recording happens only after a successful send (see record_spend)."""
    single, daily_cap = config.caps(mode)
    if usd <= 0:
        raise SpendLimitError(f"Non-positive notional: {usd}")
    if usd > single:
        raise SpendLimitError(f"${usd} exceeds the {mode} per-trade cap ${single}")
    daily = Decimal(str(store.spend_last_24h(mode)))
    if daily + usd > daily_cap:
        raise SpendLimitError(
            f"24h {mode} spend ${daily} + ${usd} exceeds the daily cap ${daily_cap}")


def check_spend_value(raw, mode: str = "paper") -> Decimal:
    """Parse an order size from a proposal, then check it. Anything that is not a
    plain positive finite number (NaN, Infinity, 'abc', a negative) is refused as
    a spend-limit breach, never allowed through as an odd exception."""
    try:
        usd = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise SpendLimitError(f"Not a valid order size: {raw!r}") from None
    if not usd.is_finite():
        raise SpendLimitError(f"Not a valid order size: {raw!r}")
    check_spend(usd, mode=mode)
    return usd


def record_spend(usd: Decimal, symbol: str, order_id: str | None, mode: str = "paper") -> None:
    store.record_spend(str(usd), symbol, order_id, mode=mode)


# --------------------------------------------------------------- market hours
def check_market_open(proposal: dict, clock: dict | None) -> None:
    """A stock DAY order sent while the market is closed is QUEUED by Alpaca and
    fills at the next open at whatever price the open prints: that walks right
    around the slippage bound. So stock orders go only while the market is open.
    An unknown clock counts as closed. Crypto trades 24/7."""
    if proposal.get("kind") == "crypto":
        return
    if not clock or clock.get("is_open") is not True:
        raise MarketClosedError(
            "The stock market is closed. Approve during market hours "
            "(9:30am-4pm ET) so the price you see is the price you get.")


# --------------------------------------------------------------- live permission
def check_live_permitted(mode: str, permitted: bool) -> None:
    """Real money only when the caller has proven it is allowed (Pro license,
    or the owner's pilot). Paper is always allowed."""
    if mode == "live" and not permitted:
        raise LiveNotPermittedError(
            "Live trading is not switched on for this copy (needs MarketPulse Pro).")


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
    with store.locked():
        state = store.load_circuit()
        if state.get("day") != today or state.get("day_start_equity", 0) <= 0:
            store.save_circuit({**state, "day": today, "day_start_equity": equity})
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
    with store.locked():
        state = store.load_circuit()
        losses = 0 if is_win else state.get("consecutive_losses", 0) + 1
        store.save_circuit({**state, "consecutive_losses": losses})
    if losses >= config.MAX_CONSECUTIVE_LOSSES:
        store.engage_halt(f"{losses} consecutive losses")


# --------------------------------------------------------------- full gate
def authorize_send(proposal: dict, current_price: float | None = None, *,
                   mode: str = "paper", clock: dict | None = None,
                   live_permitted: bool = False) -> None:
    """Run every independent control. Raises GuardrailError if any fails.

    This is the single chokepoint every order must pass. Order of checks is
    deliberate: cheap/global first, then market-move, then money checks.

    `current_price` is a freshly pulled live price (see broker.latest_price).
    It is REQUIRED — omitting it means we cannot bound slippage, so we fail
    closed rather than send blind. `clock` is Alpaca's market clock; without
    it a stock order is treated as market-closed. `live_permitted` must be
    True for a live-mode order to pass.
    """
    try:
        check_not_halted()
        check_live_permitted(mode, live_permitted)
        check_symbol_allowed(proposal)
        check_fresh(proposal)
        check_market_open(proposal, clock)
        if current_price is None:
            raise SlippageError(
                "No live price supplied to authorize_send; refusing to send blind")
        check_slippage(proposal, current_price)
        if proposal["side"] == "buy":  # sells reduce exposure; don't spend-cap exits
            check_spend_value(proposal.get("notional"), mode=mode)
    except GuardrailError as exc:
        # store.audit promises "every decision is logged, success or not" -- and a
        # refusal IS the decision this agent exists to make. Logging only the
        # approvals would leave the audit trail describing a system that never
        # says no. Record which control fired, then re-raise unchanged.
        store.audit("refused", {"id": proposal.get("id"), "mode": mode,
                                "symbol": proposal.get("symbol"),
                                "side": proposal.get("side"),
                                "notional": proposal.get("notional"),
                                "control": type(exc).__name__,
                                "reason": str(exc)})
        raise
    store.audit("authorized", {"id": proposal["id"], "mode": mode, "symbol": proposal["symbol"],
                               "side": proposal["side"], "notional": proposal["notional"],
                               "ref_price": proposal.get("ref_price"),
                               "live_price": current_price})
