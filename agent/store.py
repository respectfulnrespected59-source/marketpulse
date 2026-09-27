"""Tiny JSON-file persistence for the agent — no database, no pip.

State lives under agent/data/:
  proposals.json   list of proposal records (the approve/reject queue)
  ledger.json      24h rolling spend records (feeds the spend guard)
  circuit.json     circuit-breaker state
  audit.log.jsonl  append-only decision log (every event, not just sends)
  HALT             presence of this file = global kill switch engaged

All timestamps that matter to logic are epoch seconds; the audit log also
stamps an ISO-8601 UTC string for human reading. Day buckets are 'YYYY-MM-DD'.
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from datetime import datetime, timezone

import agent_config as config
import oslock

_PROPOSALS = "proposals.json"
_LEDGER = "ledger.json"
_CIRCUIT = "circuit.json"
_AUDIT = "audit.log.jsonl"
_HALT = "HALT"


def _path(name: str) -> str:
    return os.path.join(config.DATA_DIR, name)


def _ensure() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)


def _read_json(name: str, default):
    path = _path(name)
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(name: str, value) -> None:
    _ensure()
    # A temp name per writer: two writers sharing one ".tmp" could rename the
    # other's half-written file into place.
    tmp = _path(f"{name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2)
    os.replace(tmp, _path(name))  # atomic-ish on the same filesystem


# Public names for the agent's other small state files (pilot, desk settings).
read_json = _read_json
write_json = _write_json


class LedgerError(Exception):
    """The spend ledger exists but cannot be read: the spend caps cannot be
    checked, so nothing may be sent (fail closed, never "spent $0")."""


# ----------------------------------------------------------------- locking
# Every read-modify-write of proposals and the ledger runs under one lock, a
# thread lock plus an OS file lock, because the background scanner, the app and
# the CLI all write these files. Without it an Approve that lands while a scan
# is saving can be overwritten, flipping a SENT order back to "pending".
_STORE_LOCK = threading.RLock()
_HELD = threading.local()
STORE_LOCK_FILE = ".store.lock"


@contextlib.contextmanager
def _locked():
    with _STORE_LOCK:
        depth = getattr(_HELD, "depth", 0)
        if depth:                      # re-entered on this thread: already hold the file lock
            _HELD.depth = depth + 1
            try:
                yield
            finally:
                _HELD.depth = depth
            return
        with oslock.FileLock(STORE_LOCK_FILE, timeout=10.0):
            _HELD.depth = 1
            try:
                yield
            finally:
                _HELD.depth = 0


# ----------------------------------------------------------------- audit
def audit(event: str, detail: dict | None = None) -> None:
    """Append one immutable line. Every decision is logged, success or not."""
    _ensure()
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "detail": detail or {},
    }
    with open(_path(_AUDIT), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def read_audit(limit: int = 50) -> list[dict]:
    path = _path(_AUDIT)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


# ----------------------------------------------------------------- proposals
def load_proposals() -> list[dict]:
    return _read_json(_PROPOSALS, [])


def save_proposals(proposals: list[dict]) -> None:
    with _locked():
        _write_json(_PROPOSALS, proposals)


def add_proposal(proposal: dict) -> None:
    with _locked():
        _write_json(_PROPOSALS, [*load_proposals(), proposal])


def update_proposal(pid: str, **changes) -> dict | None:
    """Return a NEW updated record (immutable style) and persist the list."""
    with _locked():
        proposals = load_proposals()
        updated = None
        out = []
        for p in proposals:
            if p["id"] == pid:
                updated = {**p, **changes}
                out.append(updated)
            else:
                out.append(p)
        if updated is not None:
            _write_json(_PROPOSALS, out)
        return updated


def expire_stale(ttl_s: float, now: float | None = None) -> list[str]:
    """Pending proposals older than the TTL become 'expired'. A stale one can
    never be approved anyway (guardrails.check_fresh), and left pending it
    blocks every new proposal for that symbol. Returns the expired ids."""
    now = time.time() if now is None else now
    with _locked():
        proposals = load_proposals()
        gone = [p["id"] for p in proposals
                if p.get("status") == "pending" and now - float(p.get("ts") or 0) > ttl_s]
        if gone:
            _write_json(_PROPOSALS, [{**p, "status": "expired"} if p["id"] in gone else p
                                     for p in proposals])
    for pid in gone:
        audit("expired", {"id": pid})
    return gone


def get_proposal(pid: str) -> dict | None:
    for p in load_proposals():
        if p["id"] == pid:
            return p
    return None


# ----------------------------------------------------------------- ledger
def _read_ledger() -> list[dict]:
    """The ledger, or LedgerError if it exists but is unreadable. Reading a
    damaged ledger as empty would reset the daily cap to $0 spent."""
    path = _path(_LEDGER)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            ledger = json.load(fh)
        if not isinstance(ledger, list):
            raise ValueError("not a list")
        return ledger
    except (OSError, ValueError) as exc:
        raise LedgerError(f"The spend ledger can't be read ({type(exc).__name__}); "
                          "nothing will be sent until it is fixed.") from None


def record_spend(usd: str, symbol: str, order_id: str | None, mode: str = "paper") -> None:
    with _locked():
        _write_json(_LEDGER, [*_read_ledger(), {"ts": int(time.time()), "usd": str(usd),
                                                "symbol": symbol, "order_id": order_id,
                                                "mode": mode}])


def spend_last_24h(mode: str | None = None) -> float:
    """24h spend, optionally for one mode only. Paper and live budgets are
    separate: fake-money practice must never use up the real daily cap.
    Records written before modes existed count as paper."""
    cutoff = time.time() - 24 * 3600
    return sum(float(r["usd"]) for r in _read_ledger()
               if r["ts"] >= cutoff and (mode is None or r.get("mode", "paper") == mode))


# ----------------------------------------------------------------- circuit
def load_circuit() -> dict:
    return _read_json(_CIRCUIT, {
        "halted": False, "reason": "", "consecutive_losses": 0,
        "day": "", "day_start_equity": 0.0,
    })


def save_circuit(state: dict) -> None:
    _write_json(_CIRCUIT, state)


# ----------------------------------------------------------------- kill switch
def is_halted() -> bool:
    return os.path.isfile(_path(_HALT)) or load_circuit().get("halted", False)


def engage_halt(reason: str) -> None:
    _ensure()
    with open(_path(_HALT), "w", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat()} {reason}\n")
    state = load_circuit()
    save_circuit({**state, "halted": True, "reason": reason})
    audit("halt_engaged", {"reason": reason})


def release_halt() -> None:
    path = _path(_HALT)
    if os.path.isfile(path):
        os.remove(path)
    state = load_circuit()
    save_circuit({**state, "halted": False, "reason": "",
                  "consecutive_losses": 0})
    audit("halt_released", {})
