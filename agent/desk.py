"""The one place an approved proposal becomes an order.

Both the CLI (`cli.py approve`) and the app's Trade desk call approve(); the
auto-exit loop calls auto_exit_pass(). Order of operations, every time:

  1. claim the proposal under a lock (pending -> sending): a double click or two
     tabs can never send it twice
  2. keys present? live permitted? (before any network call)
  3. fresh live price + market clock from Alpaca
  4. guardrails.authorize_send: kill switch, live permission, allow-list,
     staleness, market hours, slippage, spend caps (live clamped to $25/$100)
  5. send with client_order_id = proposal id (Alpaca refuses a repeat)
  6. mark SUBMITTED the moment Alpaca accepts, then do the bookkeeping, so a
     bookkeeping hiccup can never make a real order look unsent

Nothing is ever left in 'sending': any failure before Alpaca accepts the order
lands the proposal in 'blocked' with a reason.

Locking: steps 1-6 run under ONE lock held from the claim through the spend
record, both a thread lock and an OS file lock (the CLI and the app are
separate processes). Without it, several approvals at once each read the same
"spent so far" and together blow past the $100/day live cap. Alpaca's
client_order_id is the second, independent guard against a double send.
"""
from __future__ import annotations

import os
import threading
import time
from decimal import Decimal

import agent_config as config
import broker
import credentials
import guardrails
import store

_LOCK = threading.Lock()
LOCK_FILE = ".desk.lock"


class DeskBusyError(Exception):
    """Another approval (maybe in another process) holds the desk lock."""


class FileLock:
    """Cross-process exclusive lock on agent/data/.desk.lock (msvcrt on Windows,
    fcntl elsewhere). Polls until `timeout`, then raises DeskBusyError."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._fh = None

    def acquire(self) -> None:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        fh = open(os.path.join(config.DATA_DIR, LOCK_FILE), "a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                _lock(fh)
                self._fh = fh
                return
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    raise DeskBusyError("Another approval is in progress. Try again in a moment.") from None
                time.sleep(0.05)

    def release(self) -> None:
        if self._fh is not None:
            try:
                _unlock(self._fh)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


if os.name == "nt":
    import msvcrt

    def _lock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _result(ok: bool, pid: str, status: str, message: str, **extra) -> dict:
    return {"ok": ok, "id": pid, "status": status, "message": message, **extra}


def _block(pid: str, message: str, event: str = "blocked") -> dict:
    store.update_proposal(pid, status="blocked", note=message)
    store.audit(event, {"id": pid, "reason": message})
    return _result(False, pid, "blocked", message)


def approve(pid: str, *, live_permitted: bool, auto: bool = False) -> dict:
    with _LOCK:
        try:
            with FileLock():
                return _approve_locked(pid, live_permitted=live_permitted, auto=auto)
        except DeskBusyError as exc:
            return _result(False, pid, "pending", str(exc))


def _approve_locked(pid: str, *, live_permitted: bool, auto: bool) -> dict:
    p = store.get_proposal(pid)
    if not p:
        return _result(False, pid, "missing", "No such proposal.")
    if p.get("status") != "pending":
        return _result(False, pid, p.get("status", "unknown"),
                       f"This proposal is already {p.get('status')}; nothing was sent.")
    try:
        store.update_proposal(pid, status="sending")
    except Exception as exc:  # noqa: BLE001 — could not claim it: send nothing, say so
        store.audit("claim_failed", {"id": pid, "error": type(exc).__name__})
        return _result(False, pid, "pending",
                       f"Could not save the approval ({type(exc).__name__}); nothing was sent. Try again.")
    try:
        return _send(p, live_permitted=live_permitted, auto=auto)
    except Exception as exc:  # noqa: BLE001 — never leave a proposal stuck in 'sending'
        current = store.get_proposal(pid) or {}
        status = current.get("status")
        if status == "sending":
            return _block(pid, f"Not sent: unexpected error ({type(exc).__name__}).", "send_failed")
        if status == "submitted":  # Alpaca HAS the order; only our bookkeeping failed
            oid = current.get("broker_order_id")
            store.audit("bookkeeping_failed", {"id": pid, "order_id": oid, "error": type(exc).__name__})
            return _result(True, pid, "submitted",
                           f"SENT: order {oid} was accepted by Alpaca, but recording it here failed "
                           f"({type(exc).__name__}). Do NOT approve it again; check the spend ledger.",
                           mode=current.get("mode"), order_id=oid)
        return _result(False, pid, status or "unknown", f"Not sent ({type(exc).__name__}).")


def _send(p: dict, *, live_permitted: bool, auto: bool) -> dict:
    pid, symbol = p["id"], p["symbol"]
    creds = credentials.load()
    if creds is None:
        return _block(pid, "Connect your Alpaca account first; nothing was sent.")
    mode = creds.mode
    try:  # everything that needs no network, BEFORE any request leaves this computer
        guardrails.check_not_halted()
        guardrails.check_live_permitted(mode, live_permitted)
        guardrails.check_symbol_allowed(p)
    except guardrails.GuardrailError as exc:
        return _block(pid, str(exc))

    try:
        live = broker.latest_price(symbol)
    except broker.BrokerError as exc:
        return _block(pid, f"No live price, so the slippage limit can't be checked: {exc}")
    clock = None
    if p.get("kind") != "crypto":
        try:
            clock = broker.clock()
        except broker.BrokerError:
            clock = None  # unknown clock counts as closed for stocks
    try:
        guardrails.authorize_send(p, current_price=live, mode=mode, clock=clock,
                                  live_permitted=live_permitted)
    except guardrails.GuardrailError as exc:
        return _block(pid, str(exc))

    exit_pl: float | None = None
    try:
        if p["side"] == "buy":
            order = broker.submit_order(symbol, "buy", notional=p["notional"], client_order_id=pid)
        else:
            held = broker.position(symbol)
            if not held:
                return _block(pid, "There is no open position to close.")
            exit_pl = float(held.get("unrealized_pl", 0) or 0)
            if mode == "live":
                est = float(held.get("qty") or 0) * live
                if est > float(config.LIVE_SELL_SANITY_USD):
                    return _block(pid, f"Sanity stop: this sale would be about ${est:,.0f}, far more than "
                                       f"the pilot could have bought (${config.LIVE_SELL_SANITY_USD}). "
                                       "Check the position in Alpaca; nothing was sent.")
            order = broker.submit_order(symbol, "sell", qty=held["qty"], client_order_id=pid)
    except broker.DuplicateOrderError:
        store.update_proposal(pid, status="duplicate",
                              note="Alpaca already has an order with this id; it was not sent again.")
        store.audit("duplicate", {"id": pid, "mode": mode})
        return _result(False, pid, "duplicate",
                       "Alpaca already has this order, so it was not sent again. Check your Alpaca orders.")
    except broker.BrokerError as exc:
        return _block(pid, f"Alpaca refused the order: {exc}", "send_failed")

    oid = order.get("id")
    store.update_proposal(pid, status="submitted", broker_order_id=oid, mode=mode, auto=auto)
    try:
        if p["side"] == "buy":
            guardrails.record_spend(Decimal(str(p["notional"])), symbol, oid, mode=mode)
        else:
            guardrails.record_trade_result(is_win=(exit_pl is None or exit_pl >= 0))
            store.audit("exit_result", {"id": pid, "symbol": symbol, "unrealized_pl": exit_pl})
    finally:
        store.audit("submitted", {"id": pid, "symbol": symbol, "side": p["side"], "mode": mode,
                                  "order_id": oid, "auto": auto})
    return _result(True, pid, "submitted", f"{p['side'].upper()} {symbol} sent to Alpaca ({mode}).",
                   mode=mode, order_id=oid)


def reject(pid: str) -> dict:
    with _LOCK:
        p = store.get_proposal(pid)
        if not p or p.get("status") != "pending":
            return _result(False, pid, (p or {}).get("status", "missing"), "Only a pending proposal can be rejected.")
        store.update_proposal(pid, status="rejected")
    store.audit("rejected", {"id": pid})
    return _result(True, pid, "rejected", "Rejected; nothing was sent.")


def auto_exit_pass(*, live_permitted: bool) -> list[dict]:
    """Auto mode, owner decision 2026-09-27: auto may CLOSE positions on its own
    (exits cap the downside); every new BUY still waits for a human Approve."""
    results = []
    for p in store.load_proposals():
        if p.get("status") == "pending" and p.get("side") == "sell":
            results.append(approve(p["id"], live_permitted=live_permitted, auto=True))
    return results
