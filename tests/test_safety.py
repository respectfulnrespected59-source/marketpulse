"""Guards on caller-supplied input and on cache growth."""

import pytest

from safety import (
    BoundedCache,
    InvalidSymbol,
    clean_kind,
    clean_symbol,
)

pytestmark = pytest.mark.unit


class TestCleanSymbol:
    @pytest.mark.parametrize(
        "symbol",
        ["AAPL", "TSLA", "F", "BRK.B", "BRK-B", "bitcoin", "bitcoin-cash", "SPY"],
    )
    def test_accepts_real_symbols(self, symbol):
        assert clean_symbol(symbol) == symbol

    def test_trims_surrounding_whitespace(self):
        assert clean_symbol("  AAPL  ") == "AAPL"

    def test_preserves_case(self):
        # Yahoo is case-sensitive for some symbols; the crypto path lowercases
        # on its own, so this layer must not normalize case.
        assert clean_symbol("aapl") == "aapl"

    @pytest.mark.parametrize("symbol", ["", "   ", None])
    def test_rejects_empty(self, symbol):
        with pytest.raises(InvalidSymbol):
            clean_symbol(symbol)

    @pytest.mark.parametrize(
        "symbol",
        [
            "../../../etc/passwd",   # path traversal out of the API route
            "AAPL/../../v7/finance", # traversal after a valid-looking prefix
            "AAPL?range=max",        # smuggles an extra query parameter
            "AAPL#fragment",         # truncates the rest of the built URL
            "AAPL%2f..",             # percent-encoded separator
            "AAPL&x=1",              # extra parameter without a '?'
            "evil.com/x",            # slash of any kind
            "AAPL\nHost: evil",      # header-injection shaped input
            "A APL",                 # internal whitespace
            "AAPL@evil.com",         # userinfo trick
            "AAPL:8080",             # port trick
            ".AAPL",                 # leading punctuation
            "-AAPL",
            "AAPL.",                 # trailing punctuation
            "AAPL-",
            "AA..PL",                # doubled punctuation
        ],
    )
    def test_rejects_url_meaningful_input(self, symbol):
        with pytest.raises(InvalidSymbol):
            clean_symbol(symbol)

    def test_rejects_overlong_symbol(self):
        with pytest.raises(InvalidSymbol):
            clean_symbol("A" * 13)

    def test_accepts_symbol_at_the_length_limit(self):
        assert clean_symbol("A" * 12) == "A" * 12

    def test_rejects_a_long_string_that_would_bloat_the_cache_key(self):
        # The cache is keyed on the symbol, so unbounded length is its own
        # memory problem even when the characters are harmless.
        with pytest.raises(InvalidSymbol):
            clean_symbol("A" * 5000)


class TestCleanKind:
    @pytest.mark.parametrize("kind", ["stock", "crypto"])
    def test_accepts_supported_kinds(self, kind):
        assert clean_kind(kind) == kind

    def test_lowercases_input(self):
        assert clean_kind("CRYPTO") == "crypto"

    @pytest.mark.parametrize("kind", ["", None, "bonds", "../etc", "STOCKS"])
    def test_falls_back_to_default_for_anything_else(self, kind):
        assert clean_kind(kind) == "stock"

    def test_honours_an_explicit_default(self):
        assert clean_kind("nonsense", default="crypto") == "crypto"


class TestBoundedCache:
    def test_stores_and_returns_a_value(self):
        cache = BoundedCache(max_entries=4)
        cache["intraday:stock:aapl:1m"] = (1753849200.0, {"last": 190.0})
        assert cache.get("intraday:stock:aapl:1m") == (1753849200.0, {"last": 190.0})

    def test_returns_default_for_a_miss(self):
        cache = BoundedCache(max_entries=4)
        assert cache.get("nope") is None
        assert cache.get("nope", "fallback") == "fallback"

    def test_never_grows_past_the_ceiling(self):
        cache = BoundedCache(max_entries=10)
        # The attack this exists to stop: spray distinct symbols at the API.
        for i in range(5000):
            cache[f"intraday:stock:sym{i}:1m"] = (1753849200.0, i)
        assert len(cache) == 10

    def test_evicts_the_least_recently_used_entry_first(self):
        cache = BoundedCache(max_entries=2)
        cache["a"] = (1753849200.0, 1)
        cache["b"] = (1753849200.0, 2)
        cache.get("a")          # 'a' is now the most recently used
        cache["c"] = (1753849200.0, 3)

        assert "a" in cache
        assert "c" in cache
        assert "b" not in cache  # untouched, so it was evicted

    def test_overwriting_a_key_does_not_grow_the_cache(self):
        cache = BoundedCache(max_entries=4)
        for _ in range(50):
            cache["intraday:stock:aapl:1m"] = (1753849200.0, "v")
        assert len(cache) == 1

    def test_clear_empties_the_cache(self):
        cache = BoundedCache(max_entries=4)
        cache["a"] = (1753849200.0, 1)
        cache.clear()
        assert len(cache) == 0

    def test_rejects_a_nonsensical_ceiling(self):
        with pytest.raises(ValueError):
            BoundedCache(max_entries=0)
