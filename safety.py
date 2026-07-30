"""Input validation and a bounded cache for the HTTP layer.

Both guards exist for the same reason: every value in an inbound query string
is attacker-controlled, and two things downstream trusted it. `symbol` was
interpolated straight into an upstream URL path, and it was also used as a
cache key in a dict that never evicted anything — so a client could grow the
server's memory without bound just by asking for symbols that don't exist.

Kept separate from app.py so the rules are unit-testable without standing up
an HTTP server.
"""

from __future__ import annotations

import re
from collections import OrderedDict

# Longest ticker we will pass upstream. Real symbols are short: the longest
# things we legitimately send are CoinGecko slugs like "bitcoin-cash" (12).
MAX_SYMBOL_LEN = 12

# Tickers and CoinGecko slugs only: an optional leading "^" (Yahoo's index
# convention, as in ^GSPC), then alphanumerics with single dots or hyphens
# (BRK.B, BRK-B, bitcoin-cash). This deliberately excludes everything that
# could change the meaning of the URL it lands in — "/", "?", "#", "%", ":",
# "@" and whitespace. "^" is not a URL delimiter, so it cannot.
_SYMBOL_RE = re.compile(r"^\^?[A-Za-z0-9](?:[A-Za-z0-9]|[.\-](?=[A-Za-z0-9])){0,11}$")

# Kinds the API understands. Anything else is a client bug, not a market.
VALID_KINDS = ("stock", "crypto")


class InvalidSymbol(ValueError):
    """Raised when a caller-supplied ticker is not safe to send upstream."""


def clean_symbol(raw: str | None) -> str:
    """Return a normalized ticker, or raise InvalidSymbol.

    Normalization is only whitespace-trimming; case is preserved because Yahoo
    is case-sensitive on some symbols and the crypto path lowercases its own.
    """
    symbol = (raw or "").strip()
    if not symbol:
        raise InvalidSymbol("symbol required")
    if len(symbol) > MAX_SYMBOL_LEN:
        raise InvalidSymbol("symbol too long")
    if not _SYMBOL_RE.match(symbol):
        raise InvalidSymbol("symbol contains unsupported characters")
    return symbol


def clean_kind(raw: str | None, default: str = "stock") -> str:
    """Return a supported market kind, falling back to `default`."""
    kind = (raw or "").strip().lower()
    return kind if kind in VALID_KINDS else default


class BoundedCache:
    """A dict-shaped TTL cache with a hard entry ceiling.

    Drop-in for the plain dict this replaced: callers still do
    `cache.get(key)` and `cache[key] = (timestamp, value)`. The difference is
    that inserting past `max_entries` evicts the least recently used entry
    instead of growing forever.
    """

    def __init__(self, max_entries: int = 512) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max = max_entries
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()

    def get(self, key: str, default=None):
        hit = self._data.get(key)
        if hit is None:
            return default
        # Reading counts as use, so hot symbols survive eviction pressure.
        self._data.move_to_end(key)
        return hit

    def __setitem__(self, key: str, value: tuple[float, object]) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()
