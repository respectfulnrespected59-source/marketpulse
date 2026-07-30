"""Resolving any tradable symbol, instead of a hardcoded shortlist.

The app used to know about exactly ten coins, because COINBASE_MAP was written
by hand. Anything outside it silently vanished from the grid. These helpers
resolve a symbol against what the venues *actually* list right now: Coinbase's
product catalogue for crypto, and Yahoo's search index for everything else.

Pure functions over payloads the caller fetches, so they unit-test without a
network and the caching policy stays in app.py where the rest of it lives.
"""

from __future__ import annotations

# Quote currencies we can price against, best first. USD is the real target;
# USDC/USDT stand in for coins Coinbase only lists against a stablecoin.
QUOTE_PREFERENCE = ("USD", "USDC", "USDT")


def parse_coinbase_products(raw: object) -> dict[str, str]:
    """Map base ticker -> product id from Coinbase's /products payload.

    Skips anything delisted or halted, so we never offer a market that cannot
    actually be traded. When a coin lists against several quote currencies the
    QUOTE_PREFERENCE order decides, so BTC resolves to BTC-USD and not BTC-USDT.
    """
    if not isinstance(raw, list):
        return {}

    best: dict[str, tuple[int, str]] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "online":
            continue
        if row.get("trading_disabled") or row.get("auction_mode"):
            continue

        base = str(row.get("base_currency") or "").upper()
        quote = str(row.get("quote_currency") or "").upper()
        product = str(row.get("id") or "")
        if not base or not product or quote not in QUOTE_PREFERENCE:
            continue

        rank = QUOTE_PREFERENCE.index(quote)
        current = best.get(base)
        if current is None or rank < current[0]:
            best[base] = (rank, product)

    return {base: product for base, (_, product) in best.items()}


def resolve_crypto_product(
    symbol: str,
    curated: dict[str, tuple],
    listed: dict[str, str] | None = None,
) -> str | None:
    """Find the Coinbase product for a symbol, or None if it isn't tradable.

    Accepts either form the app passes around: a CoinGecko slug ("bitcoin",
    used by the default grid) or a plain ticker ("BTC", "PEPE", what a user
    types). The curated map wins so the shipped defaults keep their exact
    behaviour; the live catalogue covers everything else.
    """
    if not symbol:
        return None

    slug = symbol.strip().lower()
    entry = curated.get(slug)
    if entry:
        return entry[0]

    ticker = symbol.strip().upper()
    for _slug, value in curated.items():
        # Curated entries are (product, ticker, name); match the ticker too so
        # "BTC" resolves the same way "bitcoin" does.
        if len(value) > 1 and str(value[1]).upper() == ticker:
            return value[0]

    return (listed or {}).get(ticker)


def crypto_display_name(symbol: str, curated: dict[str, tuple]) -> str:
    """Human label for a coin: the curated name if we have one, else the ticker."""
    slug = symbol.strip().lower()
    entry = curated.get(slug)
    if entry and len(entry) > 2:
        return str(entry[2])
    ticker = symbol.strip().upper()
    for value in curated.values():
        if len(value) > 2 and str(value[1]).upper() == ticker:
            return str(value[2])
    return ticker


def round_price(value: float) -> float:
    """Round a price without flattening sub-penny coins to zero.

    A fixed 4 decimal places is fine for equities and silently destroys memecoins:
    PEPE trades around $0.000008, so round(price, 4) is 0.0 and every candle on
    the chart collapses onto the axis. Precision scales with magnitude instead.
    """
    magnitude = abs(value)
    if magnitude >= 1000:
        return round(value, 2)
    if magnitude >= 1:
        return round(value, 4)
    if magnitude >= 0.01:
        return round(value, 6)
    return round(value, 12)


def search_listed_crypto(
    query: str,
    listed: dict[str, str],
    curated: dict[str, tuple],
    limit: int = 6,
) -> list[dict]:
    """Match a query against coins the venue actually lists.

    Yahoo's crypto results are its own internal identifiers (PEPE24478 and
    friends), which are not tradable anywhere here, so crypto search reads the
    Coinbase catalogue directly. Exact ticker first, then prefix, then any
    substring — so typing "pep" surfaces PEPE rather than burying it.
    """
    q = (query or "").strip().upper()
    if not q or not listed:
        return []

    exact = [t for t in listed if t == q]
    prefix = sorted(t for t in listed if t.startswith(q) and t != q)
    contains = sorted(t for t in listed if q in t and not t.startswith(q))

    rows: list[dict] = []
    for ticker in exact + prefix + contains:
        rows.append({
            "symbol": ticker,
            "kind": "crypto",
            "name": crypto_display_name(ticker, curated),
            "exchange": "Coinbase",
            "type": "CRYPTOCURRENCY",
        })
        if len(rows) >= limit:
            break
    return rows


# Yahoo quoteTypes we surface. Crypto is deliberately excluded — see
# search_listed_crypto for why Yahoo's crypto identifiers are unusable here.
_TRADABLE_TYPES = {"EQUITY", "ETF", "INDEX", "MUTUALFUND"}


def parse_yahoo_search(raw: object, limit: int = 12) -> list[dict]:
    """Normalize Yahoo's search payload into stock rows the UI can render."""
    if not isinstance(raw, dict):
        return []
    quotes = raw.get("quotes")
    if not isinstance(quotes, list):
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    for q in quotes:
        if not isinstance(q, dict):
            continue
        quote_type = str(q.get("quoteType") or "").upper()
        if quote_type not in _TRADABLE_TYPES:
            continue
        symbol = str(q.get("symbol") or "").strip()
        if not symbol:
            continue

        key = symbol.upper()
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "symbol": symbol,
            "kind": "stock",
            "name": str(q.get("shortname") or q.get("longname") or symbol),
            "exchange": str(q.get("exchDisp") or q.get("exchange") or ""),
            "type": quote_type,
        })
        if len(rows) >= limit:
            break

    return rows
