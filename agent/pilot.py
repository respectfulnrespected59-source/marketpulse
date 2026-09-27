"""The owner's live pilot: one week, $25 a trade, $100 a day (owner decision
2026-09-27). Live permission from the pilot needs BOTH:

  * MP_OWNER_PILOT=1 in the environment (set only on the owner's own machine), and
  * a started, unexpired window in agent/data/pilot.json

so the pilot switches itself off after seven days instead of quietly becoming
permanent. The $25/$100 ceilings themselves live in agent_config.caps("live")
and apply to every live order, pilot or not.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import store

FILE = "pilot.json"
DAYS = 7


class PilotError(Exception):
    pass


def _flag() -> bool:
    return os.environ.get("MP_OWNER_PILOT") == "1"


def window() -> dict | None:
    """{"started": epoch, "ends": epoch}, or None when no pilot has been started
    (or the file is unreadable, which counts as no pilot: fail closed)."""
    raw = store.read_json(FILE, None)
    if not isinstance(raw, dict):
        return None
    try:
        started, ends = float(raw["started"]), float(raw["ends"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"started": started, "ends": ends} if ends > started else None


def active(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    w = window()
    return _flag() and w is not None and w["started"] <= now < w["ends"]


def start(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if not _flag():
        raise PilotError("The live pilot runs only on the owner's machine: set MP_OWNER_PILOT=1 first.")
    w = window()
    if w and now < w["ends"]:
        raise PilotError(f"A pilot is already running until {_iso(w['ends'])}.")
    new = {"started": now, "ends": now + DAYS * 86400}
    store.write_json(FILE, new)
    store.audit("pilot_started", {"ends": _iso(new["ends"])})
    return new


def stop(now: float | None = None) -> None:
    """End the pilot early. The record is kept (ends = now), not deleted."""
    now = time.time() if now is None else now
    w = window()
    if w and now < w["ends"]:
        store.write_json(FILE, {"started": w["started"], "ends": now})
        store.audit("pilot_stopped", {})


def status(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    w = window()
    return {
        "flag": _flag(),
        "active": active(now),
        "started": _iso(w["started"]) if w else None,
        "ends": _iso(w["ends"]) if w else None,
        "days_left": round(max(0.0, (w["ends"] - now) / 86400), 1) if w else 0.0,
    }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="minutes")
