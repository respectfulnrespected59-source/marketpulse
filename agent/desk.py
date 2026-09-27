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

import threading
import time
from decimal import Decimal

import agent_config as config
import broker
import credentials
import guardrails
import notify
import oslock
import store

_LOCK = threading.Lock()
LOCK_FILE = ".desk.lock"


class DeskBusyError(oslock.BusyError):
    """Another approval (maybe in another process) holds the desk lock."""


def FileLock(timeout: float = 10.0) -> oslock.FileLock:  # noqa: N802 — kept as the old class name
    """Cross-process exclusive lock on agent/data/.desk.lock."""
    return oslock.FileLock(LOCK_FILE, timeout, DeskBusyError,
                           "Another approval is in progress. Try again in a moment.")

class _SentButUnrecorded(Exception):
    """Alpaca accepted the order but the 'submitted' record could not be saved."""

    def __init__(self, oid, mode):
        super().__init__(oid)
        self.oid, self.mode = oid, mode


class _MaybeSent(Exception):
    """The order may have reached Alpaca and even 'unconfirmed' couldn't be saved."""

    def __init__(self, mode):
        super().__init__(mode)
        self.mode = mode


SEND_STUCK_S = 300      # a 'sending' this old was interrupted mid-send: settle it with Alpaca
NOT_FOUND_TRUST_S = 60  # Alpaca may not index a brand-new order at once: trust "not found" only after this


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
        store.update_proposal(pid, status="sending", sending_since=time.time())
    except Exception as exc:  # noqa: BLE001 — could not claim it: send nothing, say so
        store.audit("claim_failed", {"id": pid, "error": type(exc).__name__})
        return _result(False, pid, "pending",
                       f"Could not save the approval ({type(exc).__name__}); nothing was sent. Try again.")
    try:
        return _send(p, live_permitted=live_permitted, auto=auto)
    except _SentButUnrecorded as exc:   # never "not sent": Alpaca HAS this order
        store.audit("bookkeeping_failed", {"id": pid, "order_id": exc.oid, "stage": "submitted"})
        return _result(True, pid, "submitted",
                       f"SENT: order {exc.oid} was accepted by Alpaca, but saving that here failed. "
                       "Do NOT approve it again; the desk will settle it with Alpaca.",
                       mode=exc.mode, order_id=exc.oid)
    except _MaybeSent as exc:
        store.audit("bookkeeping_failed", {"id": pid, "stage": "unconfirmed"})
        return _result(False, pid, "unconfirmed",
                       "Alpaca didn't answer and the desk couldn't save that. The order MAY have been "
                       "placed: check your Alpaca orders before doing anything else.", mode=exc.mode)
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
    except (guardrails.GuardrailError, store.LedgerError) as exc:
        return _block(pid, str(exc))

    exit_pl: float | None = None
    try:
        if p["side"] == "buy":
            order = broker.submit_order(symbol, "buy", notional=p["notional"], client_order_id=pid)
        else:
            try:
                held = broker.position(symbol)
            except broker.BrokerError as exc:   # a READ failed: no order was attempted
                return _block(pid, f"Couldn't read the position from Alpaca, so nothing was sent: {exc}")
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
    except broker.TransportError as exc:
        return _unconfirmed(p, mode, auto, exc)
    except broker.BrokerError as exc:
        return _block(pid, f"Alpaca refused the order: {exc}", "send_failed")

    # From here on Alpaca HAS the order: no failure may ever read as "not sent".
    oid = order.get("id") if isinstance(order, dict) else None
    try:
        _mark_submitted(pid, broker_order_id=oid, mode=mode, auto=auto, exit_pl=exit_pl)
    except _SentButUnrecorded:
        raise
    except Exception:  # noqa: BLE001
        raise _SentButUnrecorded(oid, mode) from None
    try:
        if p["side"] == "buy":
            guardrails.record_spend(Decimal(str(p["notional"])), symbol, oid, mode=mode)
        else:
            guardrails.record_trade_result(is_win=(exit_pl is None or exit_pl >= 0))
            store.audit("exit_result", {"id": pid, "symbol": symbol, "unrealized_pl": exit_pl, "mode": mode})
    finally:
        store.audit("submitted", {"id": pid, "symbol": symbol, "side": p["side"], "mode": mode,
                                  "order_id": oid, "auto": auto})
    return _result(True, pid, "submitted", f"{p['side'].upper()} {symbol} sent to Alpaca ({mode}).",
                   mode=mode, order_id=oid)


def _mark_submitted(pid: str, **fields) -> None:
    """Record an order Alpaca accepted. Retried, because a lost write here would
    otherwise read as "not sent" for an order that exists."""
    for attempt in range(3):
        try:
            store.update_proposal(pid, status="submitted", **fields)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.2 * (attempt + 1))
    raise _SentButUnrecorded(fields.get("broker_order_id"), fields.get("mode"))


def _provisional(pid: str) -> str:
    """Ledger tag for the spend of an order whose reply never came."""
    return f"unconfirmed:{pid}"


def _unconfirmed(p: dict, mode: str, auto: bool, exc: Exception) -> dict:
    """No usable reply to an order: it may or may not exist. Never call that
    "refused". A buy's spend is counted now (the safe side of the daily cap)
    and refresh_fills settles the truth with Alpaca by our own order id."""
    pid = p["id"]
    try:
        store.update_proposal(pid, status="unconfirmed", mode=mode, auto=auto, unconfirmed_since=time.time(),
                              note="Alpaca didn't answer in time; checking whether the order was placed.")
        if p["side"] == "buy":
            guardrails.record_spend(Decimal(str(p["notional"])), p["symbol"], _provisional(pid), mode=mode)
    except Exception:  # noqa: BLE001
        raise _MaybeSent(mode) from None
    store.audit("unconfirmed", {"id": pid, "mode": mode, "error": type(exc).__name__})
    return _result(False, pid, "unconfirmed",
                   "Alpaca didn't answer in time. The order MAY have been placed; the desk is checking "
                   "with Alpaca. Don't place it again by hand.", mode=mode)


def reject(pid: str) -> dict:
    """Under the SAME locks as approve(): a reject from the CLI (another
    process) must never overwrite a proposal an approval already claimed."""
    with _LOCK:
        try:
            with FileLock():
                p = store.get_proposal(pid)
                if not p or p.get("status") != "pending":
                    return _result(False, pid, (p or {}).get("status", "missing"),
                                   "Only a pending proposal can be rejected.")
                store.update_proposal(pid, status="rejected")
        except DeskBusyError as exc:
            return _result(False, pid, "pending", str(exc))
    store.audit("rejected", {"id": pid})
    return _result(True, pid, "rejected", "Rejected; nothing was sent.")


def auto_exit_pass(*, live_permitted: bool) -> list[dict]:
    """Auto mode, owner decision 2026-09-27: auto may CLOSE positions on its own
    (exits cap the downside); every new BUY still waits for a human Approve.

    In live mode without permission it does nothing at all: approving would
    only mark each exit 'blocked', and a blocked exit is one the human can no
    longer approve. Left pending, it stays one click away."""
    creds = credentials.load()
    if creds is not None and creds.mode == "live" and not live_permitted:
        store.audit("auto_exit_skipped", {"reason": "live not permitted"})
        return []
    results = []
    for p in store.load_proposals():
        if p.get("status") == "pending" and p.get("side") == "sell":
            results.append(approve(p["id"], live_permitted=live_permitted, auto=True))
    return results


# ------------------------------------------------------------------ settings
SETTINGS_FILE = "desk_settings.json"
_DEFAULTS = {"auto_exits": False}


def settings() -> dict:
    raw = store.read_json(SETTINGS_FILE, {})
    raw = raw if isinstance(raw, dict) else {}
    return {"auto_exits": raw.get("auto_exits") is True}   # anything odd reads as OFF


def set_auto_exits(on: bool) -> dict:
    new = {**settings(), "auto_exits": bool(on)}
    store.write_json(SETTINGS_FILE, new)
    store.audit("auto_exits", {"on": bool(on)})
    return new


# ------------------------------------------------------------------ the loop
def tick(*, live_permitted: bool, scan=None) -> dict:
    """One pass of the background loop: expire stale proposals, scan for new
    ones, then (only if the owner switched auto-exits on) close positions whose
    exit fired. Buys are never sent from here. `scan` is injectable for tests."""
    if credentials.load() is None:
        return {"ran": False, "why": "not connected"}
    if scan is None:
        import proposer
        scan = proposer.scan
    new = scan()
    toast = notify.message(new)        # a buy nobody sees in 30 minutes is a buy nobody approves
    if toast:
        notify.send(toast)
    exits = auto_exit_pass(live_permitted=live_permitted) if settings()["auto_exits"] else []
    refresh_fills()
    out = {"ran": True, "new": len(new), "notified": bool(toast),
           "auto_exits": [r["status"] for r in exits]}
    # Heartbeat: proof the scheduled scans are really running, shown on the desk.
    store.write_json(HEARTBEAT_FILE, {"ts": int(time.time()), **out})
    return out


HEARTBEAT_FILE = "last_tick.json"


def last_tick() -> dict | None:
    beat = store.read_json(HEARTBEAT_FILE, None)
    return beat if isinstance(beat, dict) and isinstance(beat.get("ts"), int) else None


# ------------------------------------------------------------------ receipts
_FINAL = {"filled", "canceled", "expired", "rejected", "done_for_day", "replaced"}


def _fill(o: dict) -> dict:
    return {"status": o.get("status"), "qty": o.get("filled_qty"),
            "avg_price": o.get("filled_avg_price"), "at": o.get("filled_at")}


def reconcile(now: float | None = None) -> int:
    """Settle orders whose reply never came ('unconfirmed', or a 'sending' left
    by an interrupted send) by asking Alpaca for OUR id. Found: submitted.
    Alpaca has none: blocked, never sent. Runs under the approval lock so it
    can never race a send in progress."""
    now = time.time() if now is None else now

    def stuck(p: dict) -> bool:
        return p.get("status") == "unconfirmed" or (
            p.get("status") == "sending"
            and now - float(p.get("sending_since") or p.get("ts") or 0) > SEND_STUCK_S)

    if not any(stuck(p) for p in store.load_proposals()):
        return 0
    settled = 0
    if not _LOCK.acquire(timeout=0.5):     # an approval is running: settle on the next pass
        return 0
    try:
        try:
            with FileLock(timeout=0):
                for p in [p for p in store.load_proposals() if stuck(p)]:
                    try:
                        o = broker.get_order_by_client_id(p["id"])
                    except broker.NotFoundError:
                        since = float(p.get("unconfirmed_since") or p.get("sending_since") or p.get("ts") or 0)
                        if now - since < NOT_FOUND_TRUST_S:
                            continue      # too soon to believe "not found"; ask again next pass
                        store.remove_spend(_provisional(p["id"]))   # it never left: give the cap back
                        store.update_proposal(p["id"], status="blocked",
                                              note="Alpaca has no order with this id: it was never placed.")
                        store.audit("reconciled", {"id": p["id"], "found": False})
                    except broker.BrokerError:
                        continue          # still no answer: ask again next pass
                    else:
                        store.update_proposal(p["id"], status="submitted", broker_order_id=o.get("id"),
                                              mode=p.get("mode"), fill=_fill(o))
                        store.audit("reconciled", {"id": p["id"], "found": True, "order_id": o.get("id")})
                    settled += 1
        except DeskBusyError:
            return settled
    finally:
        _LOCK.release()
    return settled


def refresh_fills(limit: int = 10) -> int:
    """Read the fill (qty, average price) of sent orders back from Alpaca, so
    the desk shows what actually happened, not just "sent". Oldest first: a
    newest-first slice could leave an old unresolved order unread forever."""
    reconcile()
    todo = [p for p in store.load_proposals()
            if p.get("status") == "submitted" and p.get("broker_order_id")
            and (p.get("fill") or {}).get("status") not in _FINAL][:limit]
    done = 0
    for p in todo:
        try:
            o = broker.get_order(p["broker_order_id"])
        except broker.BrokerError:
            continue          # try again next pass; a receipt is never worth a crash
        store.update_proposal(p["id"], fill=_fill(o))
        done += 1
    return done


# ------------------------------------------------------------------ report
def report(days: float = 7, now: float | None = None) -> dict:
    """What the agent did in the last `days`, split paper vs live. The go/no-go
    evidence between the paper week and the live pilot."""
    now = time.time() if now is None else now
    since = now - days * 86400
    rows = [p for p in store.load_proposals() if float(p.get("ts") or 0) >= since]
    out = {"days": days, "proposed": len(rows), "by_status": {}, "modes": {}}
    for p in rows:
        out["by_status"][p.get("status", "?")] = out["by_status"].get(p.get("status", "?"), 0) + 1
    for p in rows:
        if p.get("status") != "submitted":
            continue
        m = out["modes"].setdefault(p.get("mode") or "paper", {
            "buys": 0, "sells": 0, "auto_sells": 0, "filled": 0, "bought_usd": 0.0})
        m["buys" if p["side"] == "buy" else "sells"] += 1
        m["auto_sells"] += 1 if p["side"] == "sell" and p.get("auto") else 0
        fill = p.get("fill") or {}
        if fill.get("status") == "filled":
            m["filled"] += 1
            if p["side"] == "buy":
                m["bought_usd"] += float(fill.get("qty") or 0) * float(fill.get("avg_price") or 0)
    # P/L on each position at the moment it was closed, kept on the proposal
    # itself (not scraped from the audit log, whose tail can roll past a week).
    exits = [p for p in rows if p.get("status") == "submitted" and p.get("side") == "sell"
             and p.get("exit_pl") is not None]
    pl: dict = {}
    for p in exits:
        mode = p.get("mode") or "paper"
        pl[mode] = round(pl.get(mode, 0.0) + float(p["exit_pl"]), 2)
    out["exit_pl_usd"] = pl
    out["exits"] = len(exits)
    return out
