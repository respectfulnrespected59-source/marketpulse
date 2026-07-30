"""Resolving arbitrary symbols against what the venues actually list."""

import pytest

from symbols import (
    crypto_display_name,
    parse_coinbase_products,
    parse_yahoo_search,
    resolve_crypto_product,
    round_price,
    search_listed_crypto,
)

pytestmark = pytest.mark.unit


# A stand-in for the app's hand-written map: slug -> (product, ticker, name).
CURATED = {
    "bitcoin": ("BTC-USD", "BTC", "Bitcoin"),
    "ethereum": ("ETH-USD", "ETH", "Ethereum"),
}


def product(base, quote="USD", status="online", disabled=False):
    return {
        "id": f"{base}-{quote}",
        "base_currency": base,
        "quote_currency": quote,
        "status": status,
        "trading_disabled": disabled,
    }


class TestParseCoinbaseProducts:
    def test_maps_base_ticker_to_product_id(self):
        out = parse_coinbase_products([product("BTC"), product("PEPE")])
        assert out == {"BTC": "BTC-USD", "PEPE": "PEPE-USD"}

    def test_skips_delisted_and_halted_markets(self):
        out = parse_coinbase_products([
            product("GOOD"),
            product("OFFLINE", status="delisted"),
            product("HALTED", disabled=True),
        ])
        assert out == {"GOOD": "GOOD-USD"}

    def test_prefers_usd_over_stablecoin_pairs(self):
        # Order reversed on purpose: preference must decide, not input order.
        out = parse_coinbase_products([product("SOL", "USDT"), product("SOL", "USD")])
        assert out["SOL"] == "SOL-USD"

    def test_falls_back_to_a_stablecoin_pair_when_no_usd_market_exists(self):
        out = parse_coinbase_products([product("NEWCOIN", "USDC")])
        assert out["NEWCOIN"] == "NEWCOIN-USDC"

    def test_ignores_pairs_quoted_in_currencies_we_cannot_price(self):
        assert parse_coinbase_products([product("BTC", "EUR")]) == {}

    @pytest.mark.parametrize("raw", [None, {}, "nonsense", [None, 42, "x"]])
    def test_survives_a_malformed_payload(self, raw):
        assert parse_coinbase_products(raw) == {}


class TestResolveCryptoProduct:
    def test_resolves_a_curated_slug(self):
        assert resolve_crypto_product("bitcoin", CURATED) == "BTC-USD"

    def test_resolves_a_curated_ticker(self):
        assert resolve_crypto_product("BTC", CURATED) == "BTC-USD"

    def test_is_case_insensitive(self):
        assert resolve_crypto_product("BiTcOiN", CURATED) == "BTC-USD"
        assert resolve_crypto_product("btc", CURATED) == "BTC-USD"

    def test_resolves_an_uncurated_coin_from_the_live_catalogue(self):
        # The whole point: a coin nobody hardcoded still works.
        listed = {"PEPE": "PEPE-USD", "WIF": "WIF-USD"}
        assert resolve_crypto_product("PEPE", CURATED, listed) == "PEPE-USD"

    def test_curated_entries_win_over_the_catalogue(self):
        # Keeps the shipped defaults behaving exactly as before.
        listed = {"BTC": "BTC-USDT"}
        assert resolve_crypto_product("bitcoin", CURATED, listed) == "BTC-USD"

    def test_returns_none_for_something_not_listed_anywhere(self):
        assert resolve_crypto_product("NOTACOIN", CURATED, {"PEPE": "PEPE-USD"}) is None

    @pytest.mark.parametrize("symbol", ["", "   ", None])
    def test_returns_none_for_empty_input(self, symbol):
        assert resolve_crypto_product(symbol, CURATED) is None

    def test_works_with_no_catalogue_loaded(self):
        # If the Coinbase catalogue fetch failed, curated coins must still work.
        assert resolve_crypto_product("bitcoin", CURATED, None) == "BTC-USD"
        assert resolve_crypto_product("PEPE", CURATED, None) is None


class TestCryptoDisplayName:
    def test_uses_the_curated_name_when_known(self):
        assert crypto_display_name("bitcoin", CURATED) == "Bitcoin"
        assert crypto_display_name("BTC", CURATED) == "Bitcoin"

    def test_falls_back_to_the_ticker_for_an_uncurated_coin(self):
        assert crypto_display_name("pepe", CURATED) == "PEPE"


def quote(symbol, qtype="EQUITY", name="Some Co"):
    return {"symbol": symbol, "quoteType": qtype, "shortname": name, "exchDisp": "NasdaqGS"}


class TestParseYahooSearch:
    def test_returns_stock_rows(self):
        rows = parse_yahoo_search({"quotes": [quote("AAPL", name="Apple Inc.")]})
        assert rows == [{
            "symbol": "AAPL", "kind": "stock", "name": "Apple Inc.",
            "exchange": "NasdaqGS", "type": "EQUITY",
        }]

    def test_drops_yahoo_crypto_entirely(self):
        # Yahoo's crypto results are its own identifiers — PEPE24478, PEPE25289 —
        # which are not tradable on Coinbase, so charting them would 404. Crypto
        # search goes through the venue catalogue instead.
        rows = parse_yahoo_search({"quotes": [
            quote("PEPE24478-USD", "CRYPTOCURRENCY", "Pepe USD"),
            quote("BTC-USD", "CRYPTOCURRENCY", "Bitcoin USD"),
        ]})
        assert rows == []

    def test_drops_instrument_types_the_app_cannot_chart(self):
        rows = parse_yahoo_search({"quotes": [
            quote("AAPL250117C00150000", "OPTION"),
            quote("ESZ24", "FUTURE"),
            quote("EURUSD=X", "CURRENCY"),
        ]})
        assert rows == []

    def test_keeps_etfs_and_indexes(self):
        rows = parse_yahoo_search({"quotes": [quote("SPY", "ETF"), quote("^GSPC", "INDEX")]})
        assert {r["symbol"] for r in rows} == {"SPY", "^GSPC"}

    def test_deduplicates_repeated_symbols(self):
        rows = parse_yahoo_search({"quotes": [quote("AAPL"), quote("AAPL")]})
        assert len(rows) == 1

    def test_respects_the_result_limit(self):
        rows = parse_yahoo_search({"quotes": [quote(f"SYM{i}") for i in range(50)]}, limit=5)
        assert len(rows) == 5

    def test_falls_back_to_the_symbol_when_no_name_is_given(self):
        rows = parse_yahoo_search({"quotes": [{"symbol": "XYZ", "quoteType": "EQUITY"}]})
        assert rows[0]["name"] == "XYZ"

    @pytest.mark.parametrize("raw", [None, [], "nonsense", {"quotes": None}, {}])
    def test_survives_a_malformed_payload(self, raw):
        assert parse_yahoo_search(raw) == []


LISTED = {"BTC": "BTC-USD", "ETH": "ETH-USD", "PEPE": "PEPE-USD",
          "PEPECOIN": "PEPECOIN-USD", "WIF": "WIF-USD", "APE": "APE-USD"}


class TestSearchListedCrypto:
    def test_finds_a_coin_by_exact_ticker(self):
        rows = search_listed_crypto("PEPE", LISTED, CURATED)
        assert rows[0]["symbol"] == "PEPE"
        assert rows[0]["kind"] == "crypto"
        assert rows[0]["exchange"] == "Coinbase"

    def test_is_case_insensitive(self):
        assert search_listed_crypto("pepe", LISTED, CURATED)[0]["symbol"] == "PEPE"

    def test_ranks_the_exact_match_above_a_longer_prefix_match(self):
        # Typing "pepe" must not bury PEPE under PEPECOIN.
        rows = search_listed_crypto("PEPE", LISTED, CURATED)
        assert [r["symbol"] for r in rows][:2] == ["PEPE", "PEPECOIN"]

    def test_matches_on_a_prefix(self):
        assert {r["symbol"] for r in search_listed_crypto("PEP", LISTED, CURATED)} == {
            "PEPE", "PEPECOIN"
        }

    def test_uses_the_curated_name_when_there_is_one(self):
        assert search_listed_crypto("BTC", LISTED, CURATED)[0]["name"] == "Bitcoin"

    def test_falls_back_to_the_ticker_for_an_uncurated_coin(self):
        assert search_listed_crypto("WIF", LISTED, CURATED)[0]["name"] == "WIF"

    def test_returns_nothing_for_an_unlisted_coin(self):
        assert search_listed_crypto("NOTACOIN", LISTED, CURATED) == []

    def test_returns_nothing_when_the_catalogue_failed_to_load(self):
        assert search_listed_crypto("BTC", {}, CURATED) == []

    @pytest.mark.parametrize("query", ["", "   ", None])
    def test_returns_nothing_for_an_empty_query(self, query):
        assert search_listed_crypto(query, LISTED, CURATED) == []

    def test_respects_the_limit(self):
        assert len(search_listed_crypto("", LISTED, CURATED, limit=2)) == 0
        assert len(search_listed_crypto("E", LISTED, CURATED, limit=2)) == 2


class TestRoundPrice:
    def test_keeps_sub_penny_coins_from_collapsing_to_zero(self):
        # The bug this exists for: PEPE at ~$0.000008 became 0.0 at 4dp, so
        # every candle on the chart sat flat on the axis.
        assert round_price(0.00000812) == 0.00000812
        assert round_price(0.00000812) != 0.0

    def test_gives_equities_sane_precision(self):
        assert round_price(58.6789123) == 58.6789
        assert round_price(190.12345) == 190.1234 or round_price(190.12345) == 190.1235

    def test_trims_large_prices_to_cents(self):
        assert round_price(104233.98765) == 104233.99

    def test_handles_mid_range_fractions(self):
        assert round_price(0.0234567891) == 0.023457

    def test_handles_zero_and_negatives(self):
        assert round_price(0.0) == 0.0
        assert round_price(-0.00000812) == -0.00000812
