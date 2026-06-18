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

import json
import os
import time
from datetime import datetime, timezone

import config

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
    tmp = _path(name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2)
    os.replace(tmp, _path(name))  # atomic-ish on the same filesystem


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
    _write_json(_PROPOSALS, proposals)


def add_proposal(proposal: dict) -> None:
    proposals = load_proposals()
    proposals.append(proposal)
    save_proposals(proposals)


def update_proposal(pid: str, **changes) -> dict | None:
    """Return a NEW updated record (immutable style) and persist the list."""
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
        save_proposals(out)
    return updated


def get_proposal(pid: str) -> dict | None:
    for p in load_proposals():
        if p["id"] == pid:
            return p
    return None


# ----------------------------------------------------------------- ledger
def record_spend(usd: str, symbol: str, order_id: str | None) -> None:
    ledger = _read_json(_LEDGER, [])
    ledger.append({"ts": int(time.time()), "usd": str(usd),
                   "symbol": symbol, "order_id": order_id})
    _write_json(_LEDGER, ledger)


def spend_last_24h() -> float:
    cutoff = time.time() - 24 * 3600
    ledger = _read_json(_LEDGER, [])
    return sum(float(r["usd"]) for r in ledger if r["ts"] >= cutoff)


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
