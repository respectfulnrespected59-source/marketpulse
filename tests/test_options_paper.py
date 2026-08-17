"""Options paper positions: what a multi-leg trade actually costs and is worth.

The stock paper engine already refuses to fill at the mid price, because a
paper record that flatters itself talks people into risking money on a system
that never worked. Options make that failure far worse: a TSLA put can quote
$4.20 bid / $4.30 ask, and a two-leg spread crosses that gap four times over a
round trip. Fill every leg at mid and you invent profit that does not exist —
on a 2-DTE spread that is the difference between "this works" and an empty pot.

So the contract these tests hold is blunt:

  * Buying fills at the ASK. Selling fills at the BID. Never the mid, never
    the last trade, not once, not anywhere.
  * Commission is charged per leg, per contract, on the way in AND on the way
    out — a spread is four commissions round trip, not one.
  * Marking an open position uses the price you would actually CLOSE at, which
    is the unfavourable side again.
  * At expiry the thing settles on intrinsic value, not on a quote.

Everything here is pure math on dicts. No network, no clock, no I/O.
"""

import pytest

import app
import options_paper as op

pytestmark = pytest.mark.unit


# --------------------------------------------------------------- fixtures

def quote(strike, bid, ask, right="put", **extra):
    """One contract as /api/options reports it."""
    q = {"strike": strike, "bid": bid, "ask": ask, "right": right}
    q.update(extra)
    return q


def a_put_debit_spread(contracts=1):
    """The TSLA 340/332.5 put debit spread, priced as it really quoted.

    Long 340P at 4.20/4.30, short 332.5P at 1.76/1.83.
    Buy the long at 4.30, sell the short at 1.76 -> 2.54 debit.
    """
    return op.open_position(
        symbol="TSLA",
        expiry="2026-08-19",
        legs=[
            {"right": "put", "strike": 340.0, "side": "long",
             "quote": quote(340.0, 4.20, 4.30)},
            {"right": "put", "strike": 332.5, "side": "short",
             "quote": quote(332.5, 1.76, 1.83)},
        ],
        contracts=contracts,
    )


# ------------------------------------------------------------ leg fills

class TestFillPrice:
    def test_buying_pays_the_ask(self):
        assert op.fill_price(quote(340, 4.20, 4.30), "buy") == 4.30

    def test_selling_receives_the_bid(self):
        assert op.fill_price(quote(332.5, 1.76, 1.83), "sell") == 1.76

    def test_never_returns_the_mid(self):
        # The mid of 4.20/4.30 is 4.25 — it must not appear on either side.
        q = quote(340, 4.20, 4.30)
        assert op.fill_price(q, "buy") != 4.25
        assert op.fill_price(q, "sell") != 4.25

    def test_a_missing_quote_side_is_unfillable(self):
        # No bid means nobody is buying. Pretending otherwise invents liquidity.
        assert op.fill_price(quote(340, None, 4.30), "sell") is None
        assert op.fill_price(quote(340, 4.20, None), "buy") is None

    def test_a_zero_bid_is_unfillable(self):
        assert op.fill_price(quote(340, 0, 4.30), "sell") is None


class TestLegAction:
    def test_opening_a_long_leg_buys(self):
        assert op.leg_action("long", "open") == "buy"

    def test_closing_a_long_leg_sells(self):
        assert op.leg_action("long", "close") == "sell"

    def test_opening_a_short_leg_sells(self):
        assert op.leg_action("short", "open") == "sell"

    def test_closing_a_short_leg_buys(self):
        assert op.leg_action("short", "close") == "buy"


# --------------------------------------------------------- opening a trade

class TestOpenPosition:
    def test_net_debit_is_long_ask_minus_short_bid(self):
        pos = a_put_debit_spread()
        assert pos["entry_debit"] == pytest.approx(2.54)

    def test_it_is_a_debit_so_cash_leaves_the_account(self):
        assert a_put_debit_spread()["entry_debit"] > 0

    def test_cash_out_is_the_debit_times_the_multiplier_plus_commission(self):
        pos = a_put_debit_spread()
        # 2.54 * 100 = 254, plus 2 legs * 0.65 commission
        assert pos["cost_usd"] == pytest.approx(254 + 1.30)

    def test_commission_is_charged_per_leg_per_contract(self):
        pos = a_put_debit_spread(contracts=3)
        assert pos["commission"] == pytest.approx(2 * 3 * op.COMMISSION_PER_CONTRACT)

    def test_contracts_scale_the_cash_not_the_per_share_debit(self):
        pos = a_put_debit_spread(contracts=4)
        assert pos["entry_debit"] == pytest.approx(2.54)
        assert pos["cost_usd"] == pytest.approx(254 * 4 + 2 * 4 * op.COMMISSION_PER_CONTRACT)

    def test_each_leg_records_the_price_it_actually_filled_at(self):
        legs = a_put_debit_spread()["legs"]
        assert legs[0]["entry"] == 4.30    # long -> paid ask
        assert legs[1]["entry"] == 1.76    # short -> received bid

    def test_a_credit_spread_comes_out_negative(self):
        # Sell the expensive strike, buy the cheap one: money comes IN.
        pos = op.open_position(
            symbol="TSLA", expiry="2026-08-19",
            legs=[
                {"right": "put", "strike": 340.0, "side": "short",
                 "quote": quote(340.0, 4.20, 4.30)},
                {"right": "put", "strike": 332.5, "side": "long",
                 "quote": quote(332.5, 1.76, 1.83)},
            ],
            contracts=1,
        )
        # Receive 4.20 bid, pay 1.83 ask -> 2.37 credit -> stored as -2.37
        assert pos["entry_debit"] == pytest.approx(-2.37)

    def test_an_unfillable_leg_refuses_the_whole_position(self):
        # Half a spread is a different trade with different risk. Never open it.
        with pytest.raises(op.Unfillable):
            op.open_position(
                symbol="TSLA", expiry="2026-08-19",
                legs=[
                    {"right": "put", "strike": 340.0, "side": "long",
                     "quote": quote(340.0, 4.20, 4.30)},
                    {"right": "put", "strike": 332.5, "side": "short",
                     "quote": quote(332.5, None, 1.83)},
                ],
                contracts=1,
            )

    def test_zero_contracts_is_refused(self):
        with pytest.raises(ValueError):
            a_put_debit_spread(contracts=0)

    def test_it_carries_the_symbol_and_expiry(self):
        pos = a_put_debit_spread()
        assert pos["symbol"] == "TSLA"
        assert pos["expiry"] == "2026-08-19"


# ------------------------------------------------------ marking it live

class TestMarkPosition:
    def test_marking_closes_at_the_unfavourable_side(self):
        # To close: sell the long at its BID, buy the short back at its ASK.
        pos = a_put_debit_spread()
        chain = {
            ("put", 340.0): quote(340.0, 5.00, 5.20),
            ("put", 332.5): quote(332.5, 2.00, 2.10),
        }
        # 5.00 bid - 2.10 ask = 2.90
        assert op.mark_value(pos, chain) == pytest.approx(2.90)

    def test_a_favourable_move_shows_a_gain(self):
        pos = a_put_debit_spread()
        chain = {
            ("put", 340.0): quote(340.0, 5.00, 5.20),
            ("put", 332.5): quote(332.5, 2.00, 2.10),
        }
        pnl = op.position_pnl(pos, chain)
        # mark 2.90 vs entry 2.54 = +0.36/share = +$36 gross on 1 contract
        assert pnl["gross_usd"] == pytest.approx(36.0)

    def test_net_pnl_also_charges_the_exit_commission(self):
        # Round trip on a 2-leg spread is FOUR commissions, not two.
        pos = a_put_debit_spread()
        chain = {
            ("put", 340.0): quote(340.0, 5.00, 5.20),
            ("put", 332.5): quote(332.5, 2.00, 2.10),
        }
        pnl = op.position_pnl(pos, chain)
        assert pnl["net_usd"] == pytest.approx(36.0 - 2 * 1.30)

    def test_an_adverse_move_shows_a_loss(self):
        pos = a_put_debit_spread()
        chain = {
            ("put", 340.0): quote(340.0, 2.00, 2.10),
            ("put", 332.5): quote(332.5, 0.70, 0.80),
        }
        # 2.00 - 0.80 = 1.20 vs 2.54 entry -> -1.34/share -> -$134
        assert op.position_pnl(pos, chain)["gross_usd"] == pytest.approx(-134.0)

    def test_a_missing_leg_quote_marks_unknown_rather_than_guessing(self):
        # Guessing a mark is how a losing book looks flat.
        pos = a_put_debit_spread()
        chain = {("put", 340.0): quote(340.0, 5.00, 5.20)}
        assert op.mark_value(pos, chain) is None
        assert op.position_pnl(pos, chain)["net_usd"] is None

    def test_pnl_scales_with_contracts(self):
        pos = a_put_debit_spread(contracts=5)
        chain = {
            ("put", 340.0): quote(340.0, 5.00, 5.20),
            ("put", 332.5): quote(332.5, 2.00, 2.10),
        }
        assert op.position_pnl(pos, chain)["gross_usd"] == pytest.approx(36.0 * 5)


# ------------------------------------------------- the shape of the risk

class TestVerticalGeometry:
    def test_width_is_the_distance_between_strikes(self):
        assert op.spread_width(a_put_debit_spread()) == pytest.approx(7.5)

    def test_max_loss_on_a_debit_spread_is_the_debit(self):
        assert op.max_loss_usd(a_put_debit_spread()) == pytest.approx(254.0)

    def test_max_profit_is_width_minus_debit(self):
        assert op.max_profit_usd(a_put_debit_spread()) == pytest.approx(496.0)

    def test_breakeven_on_a_put_debit_spread_is_long_strike_minus_debit(self):
        assert op.breakeven(a_put_debit_spread()) == pytest.approx(337.46)

    def test_breakeven_on_a_call_debit_spread_is_long_strike_plus_debit(self):
        pos = op.open_position(
            symbol="NVDA", expiry="2026-08-19",
            legs=[
                {"right": "call", "strike": 225.0, "side": "long",
                 "quote": quote(225.0, 3.00, 3.20, right="call")},
                {"right": "call", "strike": 230.0, "side": "short",
                 "quote": quote(230.0, 1.20, 1.30, right="call")},
            ],
            contracts=1,
        )
        # debit = 3.20 - 1.20 = 2.00 -> breakeven 227.00
        assert op.breakeven(pos) == pytest.approx(227.0)

    def test_risk_reward_is_max_profit_over_max_loss(self):
        assert op.risk_reward(a_put_debit_spread()) == pytest.approx(496 / 254, rel=1e-3)


# ------------------------------------------------------------- at expiry

class TestSettlement:
    def test_a_put_is_worth_its_intrinsic_value(self):
        assert op.intrinsic("put", 340.0, spot=330.0) == pytest.approx(10.0)

    def test_a_put_out_of_the_money_expires_worthless(self):
        assert op.intrinsic("put", 340.0, spot=350.0) == 0.0

    def test_a_call_is_worth_its_intrinsic_value(self):
        assert op.intrinsic("call", 225.0, spot=240.0) == pytest.approx(15.0)

    def test_max_profit_when_both_legs_finish_in_the_money(self):
        # Below 332.5 the spread is worth its full width.
        pos = a_put_debit_spread()
        s = op.settle(pos, spot=300.0)
        assert s["value"] == pytest.approx(7.5)
        assert s["gross_usd"] == pytest.approx(496.0)

    def test_max_loss_when_it_finishes_above_both_strikes(self):
        pos = a_put_debit_spread()
        s = op.settle(pos, spot=360.0)
        assert s["value"] == 0.0
        assert s["gross_usd"] == pytest.approx(-254.0)

    def test_it_lands_between_the_strikes(self):
        # Spot 336 -> long 340 put worth 4.00, short 332.5 worthless.
        pos = a_put_debit_spread()
        s = op.settle(pos, spot=336.0)
        assert s["value"] == pytest.approx(4.00)
        assert s["gross_usd"] == pytest.approx(4.00 * 100 - 254)

    def test_settling_at_the_breakeven_is_roughly_flat(self):
        pos = a_put_debit_spread()
        assert op.settle(pos, spot=337.46)["gross_usd"] == pytest.approx(0.0, abs=0.5)

    def test_expiring_worthless_costs_no_closing_commission(self):
        # Letting it expire really is cheaper than closing it, and the ledger
        # should say so rather than inventing a fee.
        pos = a_put_debit_spread()
        assert op.settle(pos, spot=360.0)["net_usd"] == pytest.approx(-254.0 - 1.30)


class TestExpiryClock:
    def test_a_past_expiry_is_expired(self):
        assert op.is_expired("2026-08-19", today="2026-08-20") is True

    def test_expiry_day_itself_is_not_yet_expired(self):
        # It trades all day. Settling it at 9am would be a lie.
        assert op.is_expired("2026-08-19", today="2026-08-19") is False

    def test_a_future_expiry_is_live(self):
        assert op.is_expired("2026-08-19", today="2026-08-17") is False

    def test_days_to_expiry_counts_calendar_days(self):
        assert op.days_to_expiry("2026-08-19", today="2026-08-17") == 2


class TestNetGreeks:
    def test_a_short_leg_offsets_the_long_legs_decay(self):
        # The entire reason to trade a vertical rather than a naked long put:
        # the short leg pays for most of the theta.
        pos = a_put_debit_spread()
        chain = {
            ("put", 340.0): quote(340.0, 4.20, 4.30, delta=-0.42, theta=-0.56),
            ("put", 332.5): quote(332.5, 1.76, 1.83, delta=-0.22, theta=-0.41),
        }
        g = op.net_greeks(pos, chain)
        assert g["theta"] == pytest.approx(-0.15, abs=1e-6)
        assert g["delta"] == pytest.approx(-0.20, abs=1e-6)

    def test_greeks_scale_with_contracts(self):
        pos = a_put_debit_spread(contracts=10)
        chain = {
            ("put", 340.0): quote(340.0, 4.20, 4.30, theta=-0.56),
            ("put", 332.5): quote(332.5, 1.76, 1.83, theta=-0.41),
        }
        assert op.net_greeks(pos, chain)["theta"] == pytest.approx(-1.5, abs=1e-6)

    def test_no_greeks_in_the_chain_reports_nothing_rather_than_zero(self):
        # Zero theta and unknown theta are very different claims.
        pos = a_put_debit_spread()
        chain = {
            ("put", 340.0): quote(340.0, 4.20, 4.30),
            ("put", 332.5): quote(332.5, 1.76, 1.83),
        }
        assert op.net_greeks(pos, chain) == {}


class TestChainIndex:
    def test_it_keys_contracts_by_right_and_strike(self):
        idx = op.chain_index({
            "calls": [{"strike": 340.0, "bid": 6.6, "ask": 6.8}],
            "puts": [{"strike": 340.0, "bid": 4.2, "ask": 4.3}],
        })
        assert idx[("call", 340.0)]["bid"] == 6.6
        assert idx[("put", 340.0)]["bid"] == 4.2

    def test_it_tags_each_contract_with_its_right(self):
        idx = op.chain_index({"puts": [{"strike": 340.0, "bid": 4.2, "ask": 4.3}]})
        assert idx[("put", 340.0)]["right"] == "put"

    def test_a_malformed_contract_is_skipped_not_fatal(self):
        # One bad row upstream must not cost the trader the whole mark.
        idx = op.chain_index({"puts": [{"bid": 1}, {"strike": 340.0, "bid": 4.2}]})
        assert list(idx) == [("put", 340.0)]

    def test_an_empty_chain_is_an_empty_index(self):
        assert op.chain_index({}) == {}

    def test_it_feeds_mark_value_directly(self):
        # The whole point of the index: /api/options output marks a position
        # without any hand-massaging in between.
        pos = a_put_debit_spread()
        idx = op.chain_index({"puts": [
            {"strike": 340.0, "bid": 5.00, "ask": 5.20},
            {"strike": 332.5, "bid": 2.00, "ask": 2.10},
        ]})
        assert op.mark_value(pos, idx) == pytest.approx(2.90)


# ------------------------------------------------- the live mark loop
#
# app.options_mark is what the browser polls. Like paper_scan it decides
# nothing — it reports what each held position is worth right now. The
# browser still owns the record.

@pytest.fixture
def chains(monkeypatch):
    """Swap the live CBOE fetch for a controllable one, keyed by symbol."""
    book: dict[str, dict] = {}

    def fake(symbol, expiry=None):
        return book.get(str(symbol).upper(), {"error": "no options data"})

    monkeypatch.setattr(app.options, "chain", fake)
    # The route caches by symbol+expiry; an empty cache keeps tests honest.
    monkeypatch.setattr(app, "_cached", lambda key: None)
    monkeypatch.setattr(app, "_store", lambda key, value: value)
    return book


def a_tsla_chain(spot=341.17, p340=(5.00, 5.20), p3325=(2.00, 2.10)):
    return {
        "symbol": "TSLA", "spot": spot, "expiry": "2026-08-19", "dte": 2,
        "puts": [
            {"strike": 340.0, "bid": p340[0], "ask": p340[1], "theta": -0.56},
            {"strike": 332.5, "bid": p3325[0], "ask": p3325[1], "theta": -0.41},
        ],
        "calls": [],
    }


class TestOptionsMark:
    def test_it_marks_an_open_position_against_the_live_chain(self, chains):
        chains["TSLA"] = a_tsla_chain()
        out = app.options_mark([a_put_debit_spread()], today="2026-08-17")
        m = out["marks"][0]
        assert m["status"] == "open"
        assert m["mark"] == pytest.approx(2.90)
        assert m["gross_usd"] == pytest.approx(36.0)

    def test_it_reports_the_spot_it_marked_against(self, chains):
        chains["TSLA"] = a_tsla_chain(spot=338.0)
        out = app.options_mark([a_put_debit_spread()], today="2026-08-17")
        assert out["marks"][0]["spot"] == 338.0

    def test_it_carries_the_risk_geometry_for_the_panel(self, chains):
        chains["TSLA"] = a_tsla_chain()
        m = app.options_mark([a_put_debit_spread()], today="2026-08-17")["marks"][0]
        assert m["max_profit_usd"] == pytest.approx(496.0)
        assert m["max_loss_usd"] == pytest.approx(254.0)
        assert m["breakeven"] == pytest.approx(337.46)

    def test_it_reports_net_theta(self, chains):
        chains["TSLA"] = a_tsla_chain()
        m = app.options_mark([a_put_debit_spread()], today="2026-08-17")["marks"][0]
        assert m["greeks"]["theta"] == pytest.approx(-0.15, abs=1e-6)

    def test_an_expired_position_settles_instead_of_marking(self, chains):
        # Past expiry there is no quote to mark against — only intrinsic value.
        chains["TSLA"] = a_tsla_chain(spot=300.0)
        m = app.options_mark([a_put_debit_spread()], today="2026-08-20")["marks"][0]
        assert m["status"] == "expired"
        assert m["gross_usd"] == pytest.approx(496.0)

    def test_expiry_day_still_marks_live(self, chains):
        # It trades all day; settling it early would report a result the
        # trader never actually got.
        chains["TSLA"] = a_tsla_chain()
        m = app.options_mark([a_put_debit_spread()], today="2026-08-19")["marks"][0]
        assert m["status"] == "open"

    def test_a_dead_chain_marks_unquoted_rather_than_zero(self, chains):
        chains["TSLA"] = {"error": "no options data"}
        m = app.options_mark([a_put_debit_spread()], today="2026-08-17")["marks"][0]
        assert m["status"] == "unquoted"
        assert m["net_usd"] is None

    def test_one_bad_position_does_not_kill_the_batch(self, chains):
        chains["TSLA"] = a_tsla_chain()
        out = app.options_mark(
            [{"symbol": "TSLA"}, a_put_debit_spread()], today="2026-08-17")
        # The malformed one is reported as unquoted; the good one still marks.
        assert len(out["marks"]) == 2
        assert any(m["status"] == "open" for m in out["marks"])

    def test_it_fetches_each_symbol_and_expiry_once(self, chains, monkeypatch):
        # Ten positions on one expiry is one upstream call, not ten.
        calls = []

        def counting(symbol, expiry=None):
            calls.append(symbol)
            return a_tsla_chain()

        monkeypatch.setattr(app.options, "chain", counting)
        app.options_mark([a_put_debit_spread() for _ in range(10)],
                         today="2026-08-17")
        assert len(calls) == 1

    def test_the_batch_is_bounded(self, chains):
        chains["TSLA"] = a_tsla_chain()
        out = app.options_mark(
            [a_put_debit_spread() for _ in range(500)], today="2026-08-17")
        assert len(out["marks"]) <= app.MAX_MARK_POSITIONS

    def test_an_empty_book_is_not_an_error(self, chains):
        assert app.options_mark([], today="2026-08-17")["marks"] == []

    def test_it_echoes_the_position_id_so_the_browser_can_match_them_up(self, chains):
        chains["TSLA"] = a_tsla_chain()
        pos = a_put_debit_spread()
        pos["id"] = "abc123"
        assert app.options_mark([pos], today="2026-08-17")["marks"][0]["id"] == "abc123"


# ------------------------------------------------------- opening a trade
#
# The browser must never price a fill itself. paper_scan's docstring already
# makes the argument: two implementations drift, and the drift shows up as
# "it behaved differently with real money". So opening goes through the
# server and the same options_paper math the mark loop uses.

class TestExportBook:
    """Getting the browser's book onto disk so the scheduled journal can see it.

    The book lives in localStorage, which a cron job cannot read, so the note
    was reporting `open_positions: unknown` every day. This is the bridge.

    It writes ONE fixed path, chosen by the server. The path never comes from
    the request — an endpoint that writes wherever a caller says is a file-write
    primitive pointed at the whole disk, and this app takes unauthenticated
    POSTs on localhost.
    """

    def a_position(self, **over):
        pos = {
            "id": "op123", "symbol": "TSLA", "expiry": "2026-08-19",
            "contracts": 25, "entry_debit": 3.14, "cost_usd": 7882.5,
            "commission": 32.5, "opened": 1755432000000,
            "legs": [{"right": "put", "strike": 340.0, "side": "long",
                      "qty": 25, "entry": 4.30}],
        }
        pos.update(over)
        return pos

    def test_it_writes_the_positions_to_the_given_path(self, tmp_path):
        import json
        target = tmp_path / "paper_positions.json"
        out = app.export_book([self.a_position()], str(target))
        assert out["count"] == 1
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["open"][0]["symbol"] == "TSLA"

    def test_a_second_export_overwrites_rather_than_appends(self, tmp_path):
        import json
        target = tmp_path / "paper_positions.json"
        app.export_book([self.a_position(), self.a_position(id="op2")], str(target))
        app.export_book([self.a_position()], str(target))
        assert len(json.loads(target.read_text(encoding="utf-8"))["open"]) == 1

    def test_an_empty_book_is_exportable_and_means_empty(self, tmp_path):
        # "I have no positions" is a real state the journal should record as 0,
        # not as the "unknown" it reports when there is no file at all.
        target = tmp_path / "paper_positions.json"
        assert app.export_book([], str(target))["count"] == 0
        assert target.exists()

    def test_it_keeps_only_the_fields_the_marker_needs(self, tmp_path):
        import json
        target = tmp_path / "paper_positions.json"
        app.export_book([self.a_position(evil="<script>", note="x" * 5000)],
                        str(target))
        saved = json.loads(target.read_text(encoding="utf-8"))["open"][0]
        assert "evil" not in saved
        assert "note" not in saved
        assert saved["symbol"] == "TSLA"

    def test_leg_fields_are_whitelisted_too(self, tmp_path):
        import json
        target = tmp_path / "paper_positions.json"
        app.export_book(
            [self.a_position(legs=[{"right": "put", "strike": 340.0,
                                    "side": "long", "entry": 4.3, "junk": 1}])],
            str(target))
        leg = json.loads(target.read_text(encoding="utf-8"))["open"][0]["legs"][0]
        assert "junk" not in leg
        assert leg["strike"] == 340.0

    def test_the_batch_is_bounded(self, tmp_path):
        import json
        target = tmp_path / "paper_positions.json"
        app.export_book([self.a_position() for _ in range(500)], str(target))
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert len(saved["open"]) <= app.MAX_MARK_POSITIONS

    def test_a_non_list_is_refused(self, tmp_path):
        target = tmp_path / "paper_positions.json"
        assert "error" in app.export_book({"not": "a list"}, str(target))

    def test_malformed_entries_are_dropped_not_fatal(self, tmp_path):
        import json
        target = tmp_path / "paper_positions.json"
        out = app.export_book(["nonsense", None, self.a_position()], str(target))
        assert out["count"] == 1
        assert len(json.loads(target.read_text(encoding="utf-8"))["open"]) == 1

    def test_it_stamps_when_the_snapshot_was_taken(self, tmp_path):
        import json
        target = tmp_path / "paper_positions.json"
        app.export_book([self.a_position()], str(target))
        # A stale snapshot silently marked as today's would be worse than none.
        assert "exported_ts" in json.loads(target.read_text(encoding="utf-8"))

    def test_an_unwritable_path_reports_an_error_not_a_crash(self, tmp_path):
        bad = tmp_path / "no-such-dir" / "deep" / "paper_positions.json"
        assert "error" in app.export_book([self.a_position()], str(bad))

    def test_the_exported_file_round_trips_into_a_mark(self, chains, tmp_path):
        # The real contract: what export writes must be markable as-is.
        import json
        chains["TSLA"] = a_tsla_chain()
        target = tmp_path / "paper_positions.json"
        pos = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
            {"right": "put", "strike": 332.5, "side": "short"},
        ], contracts=25)["position"]
        pos["id"] = "op1"
        app.export_book([pos], str(target))
        reloaded = json.loads(target.read_text(encoding="utf-8"))["open"]
        m = app.options_mark(reloaded, today="2026-08-17")["marks"][0]
        assert m["status"] == "open"
        assert m["net_usd"] is not None


class TestTheGate:
    """The feature gate must actually open on Pro.

    Regression: the first cut gated on a feature key named "options_paper",
    which config.PRO does not define — so features().get(...) was None and the
    endpoint returned 402 for everyone, Pro included. Every unit test passed;
    the product was simply switched off. Hence a test on the gate itself.
    """

    def test_the_gate_only_uses_keys_the_tier_actually_grants(self):
        # Loaded by path because conftest puts agent/ first on sys.path, so a
        # bare `import config` gets the agent's config, not the tier table.
        import importlib.util
        import pathlib
        root = pathlib.Path(app.__file__).resolve().parent / "config.py"
        spec = importlib.util.spec_from_file_location("mp_tier_config", root)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        # Whatever key the gate reads has to exist in the tier table, or
        # features().get() returns None and it is locked on every tier.
        assert "options" in cfg.PRO
        assert "options" in cfg.FREE
        assert cfg.PRO["options"] is True

    def test_pro_with_the_module_present_unlocks_it(self, monkeypatch):
        monkeypatch.setattr(app, "_enabled", lambda f: f == "options")
        monkeypatch.setattr(app, "options_paper", op)
        assert app._options_paper_enabled() is True

    def test_free_keeps_it_locked(self, monkeypatch):
        monkeypatch.setattr(app, "_enabled", lambda f: False)
        monkeypatch.setattr(app, "options_paper", op)
        assert app._options_paper_enabled() is False

    def test_a_missing_module_keeps_it_locked_even_on_pro(self, monkeypatch):
        # The free buyer pack has no options_paper.py; the app must still boot
        # and simply refuse this route.
        monkeypatch.setattr(app, "_enabled", lambda f: f == "options")
        monkeypatch.setattr(app, "options_paper", None)
        assert app._options_paper_enabled() is False


class TestOptionsOpen:
    def test_it_prices_the_legs_off_the_live_chain(self, chains):
        chains["TSLA"] = a_tsla_chain(p340=(4.20, 4.30), p3325=(1.76, 1.83))
        out = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
            {"right": "put", "strike": 332.5, "side": "short"},
        ], contracts=1)
        assert out["position"]["entry_debit"] == pytest.approx(2.54)

    def test_it_fills_the_long_at_the_ask_and_the_short_at_the_bid(self, chains):
        chains["TSLA"] = a_tsla_chain()
        legs = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
            {"right": "put", "strike": 332.5, "side": "short"},
        ], contracts=1)["position"]["legs"]
        assert legs[0]["entry"] == 5.20     # long -> ask
        assert legs[1]["entry"] == 2.00     # short -> bid

    def test_it_records_the_spot_it_opened_against(self, chains):
        chains["TSLA"] = a_tsla_chain(spot=341.17)
        out = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
        ], contracts=1)
        assert out["position"]["spot_at_entry"] == 341.17

    def test_a_strike_that_is_not_on_the_chain_is_refused(self, chains):
        chains["TSLA"] = a_tsla_chain()
        out = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 999.0, "side": "long"},
        ], contracts=1)
        assert "error" in out

    def test_a_dead_chain_is_refused_rather_than_guessed(self, chains):
        chains["TSLA"] = {"error": "no options data"}
        assert "error" in app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
        ], contracts=1)

    def test_zero_contracts_is_refused(self, chains):
        chains["TSLA"] = a_tsla_chain()
        out = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
        ], contracts=0)
        assert "error" in out

    def test_it_bounds_the_number_of_legs(self, chains):
        # A 40-leg "position" is a mistake or an attack, not a trade.
        chains["TSLA"] = a_tsla_chain()
        out = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"} for _ in range(40)
        ], contracts=1)
        assert "error" in out

    def test_no_legs_is_refused(self, chains):
        chains["TSLA"] = a_tsla_chain()
        assert "error" in app.options_open("TSLA", "2026-08-19", [], contracts=1)

    def test_size_is_the_traders_call_not_the_probe_budget(self, chains):
        # The $300 pot and its 20% probe are a SIZING RECOMMENDATION on the
        # Options tab, for someone learning on a small stake. The paper book
        # is a different question: does the play work? Someone who can fund
        # the full-size trade must be able to run the identical play, so
        # nothing here caps contracts against the pot.
        chains["TSLA"] = a_tsla_chain()
        out = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
            {"right": "put", "strike": 332.5, "side": "short"},
        ], contracts=25)
        pos = out["position"]
        assert pos["contracts"] == 25
        # 25 x $320 debit = $8,000 of risk — far past a $300 pot, and allowed.
        assert pos["cost_usd"] > 300

    def test_a_full_size_winner_scales_the_whole_way_up(self, chains):
        # Same play, 25 contracts: the P&L must scale linearly, with no
        # silent ceiling anywhere in the mark path.
        chains["TSLA"] = a_tsla_chain(p340=(4.20, 4.30), p3325=(1.76, 1.83))
        pos = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
            {"right": "put", "strike": 332.5, "side": "short"},
        ], contracts=25)["position"]
        # It works: TSLA lands under both strikes at expiry -> full width.
        s = op.settle(pos, spot=300.0)
        assert s["gross_usd"] == pytest.approx(496.0 * 25)

    def test_a_big_book_on_a_hot_name_still_marks(self, chains):
        # NVDA call debit spread at real size — the mark loop must not choke
        # on contract counts a funded account would actually trade.
        chains["NVDA"] = {
            "symbol": "NVDA", "spot": 225.16, "expiry": "2026-08-19", "dte": 2,
            "calls": [
                {"strike": 225.0, "bid": 3.00, "ask": 3.20, "theta": -0.30},
                {"strike": 230.0, "bid": 1.20, "ask": 1.30, "theta": -0.22},
            ],
            "puts": [],
        }
        pos = app.options_open("NVDA", "2026-08-19", [
            {"right": "call", "strike": 225.0, "side": "long"},
            {"right": "call", "strike": 230.0, "side": "short"},
        ], contracts=50)["position"]
        m = app.options_mark([pos], today="2026-08-17")["marks"][0]
        assert m["status"] == "open"
        assert m["max_loss_usd"] == pytest.approx(2.00 * 100 * 50)

    def test_the_opened_position_marks_immediately(self, chains):
        # Opened at ask/bid then marked at bid/ask, a fresh position is
        # already DOWN by the spread. That is real and the trader should
        # see it on day one rather than discover it at exit.
        chains["TSLA"] = a_tsla_chain()
        pos = app.options_open("TSLA", "2026-08-19", [
            {"right": "put", "strike": 340.0, "side": "long"},
            {"right": "put", "strike": 332.5, "side": "short"},
        ], contracts=1)["position"]
        m = app.options_mark([pos], today="2026-08-17")["marks"][0]
        assert m["gross_usd"] < 0
