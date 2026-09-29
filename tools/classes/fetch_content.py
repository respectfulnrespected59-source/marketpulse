"""Deploy step: pull the PRIVATE lessons repo into classes/.

This repo is public, so lesson content lives in a private repo and the host
pulls it at build time with a read-only token from its environment:

  MP_CLASSES_TOKEN   read-only GitHub token (the owner pastes it into Render)
  MP_CLASSES_REPO    owner/name, default respectfulnrespected59-source/marketpulse-classes

It never fails the deploy: no token, a bad repo name or a failed pull all
leave the site up with an empty catalogue, and say so in the build log.

The token never touches disk or argv. The clone URL is the plain repo URL; the
credential rides in git's per-invocation config via the environment
(GIT_CONFIG_COUNT), so it is not written into classes/.git/config and does not
show in the process list. Every message is redacted before it is printed.

Run:  python tools/classes/fetch_content.py      (render.yaml buildCommand)
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from pathlib import Path

DEST = Path(__file__).resolve().parents[2] / "classes"
DEFAULT_REPO = "respectfulnrespected59-source/marketpulse-classes"
# GitHub owners start alphanumeric; neither part may start with "." (no "..", no hidden names).
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
MAX_LOG = 300


def _say(msg: str, token: str) -> None:
    safe = msg.replace(token, "***") if token else msg      # redact first, THEN trim
    print("[classes] " + safe[:MAX_LOG], file=sys.stderr)


def auth_env(token: str) -> dict:
    """Git config for this one invocation: an Authorization header for github.com."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"}


def _commands(dest: Path, url: str) -> list:
    if (dest / ".git").exists():
        # set-url also scrubs a token an older clone may have stored in .git/config.
        # --ff-only never discards anything; a rewritten history just leaves the old checkout.
        return [["git", "-C", str(dest), "remote", "set-url", "origin", url],
                ["git", "-C", str(dest), "pull", "--ff-only", "--quiet", "origin"]]
    return [["git", "clone", "--depth", "1", "--quiet", url, str(dest)]]


def main(env=None, run=subprocess.run, dest: Path = DEST) -> int:
    env = os.environ if env is None else env
    token = (env.get("MP_CLASSES_TOKEN") or "").strip()
    repo = (env.get("MP_CLASSES_REPO") or DEFAULT_REPO).strip()
    if not token:
        _say("no MP_CLASSES_TOKEN set: skipping the lesson pull (empty catalogue)", token)
        return 0
    if not REPO_RE.fullmatch(repo):
        _say("MP_CLASSES_REPO is not owner/name: skipping (empty catalogue)", token)
        return 0
    git_env = auth_env(token)
    for cmd in _commands(dest, f"https://github.com/{repo}.git"):
        try:
            res = run(cmd, capture_output=True, text=True, errors="replace", env=git_env, timeout=300)
        except Exception as exc:  # noqa: BLE001 — a lesson pull must never fail the deploy
            _say(f"lesson pull could not run ({type(exc).__name__}): deploying with an empty catalogue", token)
            return 0
        if res.returncode != 0:
            _say(f"lesson pull failed ({res.returncode}): {(res.stderr or '').strip()}"
                 " - deploying with an empty catalogue", token)
            return 0
    _say(f"lessons pulled from {repo}", token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
