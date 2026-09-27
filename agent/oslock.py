"""Cross-process exclusive lock on a file in agent/data (msvcrt on Windows,
fcntl elsewhere). The CLI, the app and the background scanner are separate
threads or processes, so a thread lock alone cannot keep them apart.

Not named filelock.py on purpose: that would shadow the popular pip package.
"""
from __future__ import annotations

import os
import time

import agent_config as config


class BusyError(Exception):
    """Someone else (maybe another process) holds the lock."""


class FileLock:
    """Polls until `timeout`, then raises `busy` (BusyError by default)."""

    def __init__(self, name: str, timeout: float = 10.0, busy: type[Exception] = BusyError,
                 message: str = "The agent is busy. Try again in a moment.") -> None:
        self.name = name
        self.timeout = timeout
        self._busy = busy
        self._message = message
        self._fh = None

    def acquire(self) -> None:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        fh = open(os.path.join(config.DATA_DIR, self.name), "a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                _lock(fh)
                self._fh = fh
                return
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    raise self._busy(self._message) from None
                time.sleep(0.02)

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
