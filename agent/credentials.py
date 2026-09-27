"""Alpaca keys: where they live and how they are shown.

Keys are entered in the app (or exported as env vars for the CLI) and stored
ONLY on this computer, in agent/data/alpaca.json, written atomically and
locked to the current user: mode 0600 on macOS/Linux, and on Windows (where
0600 means nothing) an explicit icacls grant to this user only. They are sent to Alpaca and nowhere else, never
logged, and never returned to the browser: the UI only ever sees the mode and
the last four characters of the key id.

Env vars (MP_ALPACA_KEY_ID / MP_ALPACA_SECRET / MP_ALPACA_PAPER) win over the
file, so the existing CLI workflow keeps working unchanged.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

import agent_config as config

FILE = "alpaca.json"
MODES = ("paper", "live")
KEY_ID_RE = re.compile(r"^[A-Z0-9]{16,40}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9/+=]{20,80}$")


@dataclass(frozen=True)
class Credentials:
    key_id: str
    secret: str
    mode: str
    source: str = field(default="file", compare=False)   # "file" (the app) or "env"

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError("mode must be 'paper' or 'live'")
        if not isinstance(self.key_id, str) or not KEY_ID_RE.match(self.key_id):
            raise ValueError("That doesn't look like an Alpaca key id.")
        if not isinstance(self.secret, str) or not SECRET_RE.match(self.secret):
            raise ValueError("That doesn't look like an Alpaca secret key.")

    def __repr__(self) -> str:  # never print a secret, even by accident
        return f"Credentials(mode={self.mode!r}, key_id=...{self.key_id[-4:]})"


def problem() -> str:
    """Why load() found nothing, when there is a reason worth telling the user.
    Malformed env vars refuse to trade (they never silently fall back to the
    saved file, which may be a different mode), and this says so plainly."""
    key, secret = os.environ.get("MP_ALPACA_KEY_ID", ""), os.environ.get("MP_ALPACA_SECRET", "")
    if key or secret:
        if not (key and secret):
            return "Only one of MP_ALPACA_KEY_ID / MP_ALPACA_SECRET is set; set both or neither."
        try:
            Credentials(key, secret, "paper")
        except ValueError as exc:
            return f"MP_ALPACA_KEY_ID / MP_ALPACA_SECRET are set but malformed: {exc}"
    return ""


def _path() -> str:
    return os.path.join(config.DATA_DIR, FILE)


def load() -> Credentials | None:
    key, secret = os.environ.get("MP_ALPACA_KEY_ID", ""), os.environ.get("MP_ALPACA_SECRET", "")
    if key or secret:  # any env key present = env wins; malformed = refuse (see problem())
        if not (key and secret):
            return None
        mode = "paper" if os.environ.get("MP_ALPACA_PAPER", "true").lower() != "false" else "live"
        try:
            return Credentials(key, secret, mode, source="env")
        except ValueError:
            return None
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return Credentials(data["key_id"], data["secret"], data["mode"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(creds: Credentials) -> None:
    """Owner-only, atomic: a crash mid-write can never leave half a secret."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = _path() + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"key_id": creds.key_id, "secret": creds.secret, "mode": creds.mode}, fh)
    # On Windows the temp file briefly has the folder's inherited ACL (0600 is a
    # no-op there) until the next line locks it; it holds no data anyone else
    # can race for on a single-user machine, and it is renamed only once locked.
    _lock_to_this_user(tmp)
    os.replace(tmp, _path())


def _lock_to_this_user(path: str) -> None:
    """Windows ignores 0600, so drop inherited permissions and grant only the
    current user. A failure is loud (stderr), never silent."""
    if os.name != "nt":
        return
    user = getpass.getuser()
    r = subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"{user}:(F)"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[warn] could not restrict {path} to {user}: {r.stderr.strip() or r.stdout.strip()}",
              file=sys.stderr)


def clear() -> None:
    try:
        os.remove(_path())
    except FileNotFoundError:
        pass


def masked(creds: Credentials | None) -> dict:
    """All the browser is ever allowed to see."""
    if creds is None:
        return {"connected": False, "problem": problem()}
    return {"connected": True, "mode": creds.mode, "key_id_last4": creds.key_id[-4:],
            "source": creds.source,
            # env keys silently beating a file saved in the app is how someone
            # "switches to paper" in the UI and keeps trading live: say it.
            "overrides_saved_file": creds.source == "env" and os.path.exists(_path())}
