"""Does the signal actually PAY when expressed as an options spread?

backtest.py answers a different question — whether the signal beats buy-and-hold
on the underlying. That is a long-only stock timing rule. The app uses the same
signal to pick a 2-DTE debit spread, which is a completely different instrument
with a completely different payoff, and nobody ever measured it for that job.

This module measures the real one. The design decision that makes it honest:

    ENTRY is modelled. EXIT is not.

A debit spread held to expiry is worth exactly its intrinsic value, and we have
the real historical close on the expiry date — so the exit is fact, not a model.
Only the entry price needs Black-Scholes, and every modelling choice there is
made to cost the strategy money rather than flatter it: implied vol is taken
from trailing realised vol using bars up to and INCLUDING the entry bar only,
the bid-ask is charged on both legs, and commission is charged both ways.

If a result survives that, it is worth looking at. If it does not, no amount of
UI work on top will create an edge.

Everything here is pure math. No network, no clock.
"""

import pytest

import options_edge as oe

pytestmark = pytest.mark.unit


def _stamp(closes):
    """Dates for a close series — content irrelevant, length is what matters."""
    return [f"2026-{1 + (i // 28) % 12:02d}-{1 + i % 28:02d}" for i in range(len(closes))]


def _falling(n=140):
    return [200.0 - i * 0.5 for i in range(n)]


def _rising(n=140):
    return [100.0 + i * 0.5 for i in range(n)]


# ------------------------------------------------------- Black-Scholes

class TestBlackScholes:
    def test_a_call_is_never_worth_less_than_its_intrinsic(self):
        assert oe.bs_price(110.0, 100.0, 0.05, 0.30, "call") >= 10.0

    def test_a_put_is_never_worth_less_than_its_intrinsic(self):
        assert oe.bs_price(90.0, 100.0, 0.05, 0.30, "put") >= 9.9

    def test_put_call_parity_holds(self):
        # An independent check: C - P == S - K*e^(-rT). If the pricer is wrong
        # this fails even though it never re-derives the same formula.
        import math
        s, k, t, v, r = 100.0, 105.0, 0.25, 0.35, oe.RISK_FREE
        c = oe.bs_price(s, k, t, v, "call", r)
        p = oe.bs_price(s, k, t, v, "put", r)
        assert c - p == pytest.approx(s - k * math.exp(-r * t), abs=1e-6)

    def test_more_time_is_worth_more(self):
        near = oe.bs_price(100.0, 100.0, 0.01, 0.30, "call")
        far = oe.bs_price(100.0, 100.0, 0.50, 0.30, "call")
        assert far > near

    def test_more_volatility_is_worth_more(self):
        calm = oe.bs_price(100.0, 100.0, 0.10, 0.15, "call")
        wild = oe.bs_price(100.0, 100.0, 0.10, 0.80, "call")
        assert wild > calm

    def test_at_zero_volatility_it_collapses_to_intrinsic(self):
        assert oe.bs_price(110.0, 100.0, 0.05, 0.0, "call") == pytest.approx(10.0, abs=0.3)

    def test_at_expiry_it_is_exactly_intrinsic(self):
        assert oe.bs_price(110.0, 100.0, 0.0, 0.30, "call") == pytest.approx(10.0)
        assert oe.bs_price(110.0, 100.0, 0.0, 0.30, "put") == 0.0

    def test_a_far_out_of_the_money_option_is_nearly_worthless(self):
        assert oe.bs_price(100.0, 200.0, 0.02, 0.25, "call") < 0.01


# ------------------------------------------------------- realised vol

class TestRealisedVol:
    def test_a_flat_tape_has_no_volatility(self):
        assert oe.realised_vol([100.0] * 40, 39) == pytest.approx(0.0, abs=1e-9)

    def test_a_choppy_tape_has_more_than_a_calm_one(self):
        calm = [100.0 + (i % 2) * 0.1 for i in range(40)]
        wild = [100.0 + (i % 2) * 5.0 for i in range(40)]
        assert oe.realised_vol(wild, 39) > oe.realised_vol(calm, 39)

    def test_it_never_looks_past_the_entry_bar(self):
        # The bars AFTER entry are the future. Using them is the classic
        # backtest lie that turns a losing system into a winning chart.
        history = [100.0 + (i % 2) * 0.5 for i in range(40)]
        quiet_then_explosive = history + [100.0, 400.0, 20.0, 380.0]
        assert oe.realised_vol(quiet_then_explosive, 39) == pytest.approx(
            oe.realised_vol(history, 39))

    def test_too_little_history_is_none(self):
        assert oe.realised_vol([100.0, 101.0], 1) is None

    def test_it_is_annualised(self):
        closes = [100.0 * (1.0 + 0.01 * (i % 2)) for i in range(60)]
        v = oe.realised_vol(closes, 59)
        assert 0.01 < v < 3.0


# --------------------------------------------------- one simulated trade

class TestSimulateTrade:
    def a_trade(self, exit_price, direction="put", **over):
        kw = dict(direction=direction, spot=100.0, long_strike=100.0,
                  short_strike=97.5, sigma=0.35, dte=2, exit_spot=exit_price)
        kw.update(over)
        return oe.simulate_trade(**kw)

    def test_a_put_spread_wins_when_price_falls_through_both_strikes(self):
        t = self.a_trade(90.0)
        assert t["intrinsic"] == pytest.approx(2.5)      # full width
        assert t["pnl_usd"] > 0

    def test_a_put_spread_loses_everything_above_both_strikes(self):
        t = self.a_trade(110.0)
        assert t["intrinsic"] == 0.0
        assert t["pnl_usd"] == pytest.approx(-t["cost_usd"])

    def test_a_call_spread_wins_when_price_rises_through_both_strikes(self):
        t = self.a_trade(110.0, direction="call",
                         long_strike=100.0, short_strike=102.5)
        assert t["intrinsic"] == pytest.approx(2.5)
        assert t["pnl_usd"] > 0

    def test_the_exit_is_taken_from_the_real_price_not_a_model(self):
        # Settling on intrinsic is what makes this measurement trustworthy.
        assert self.a_trade(98.75)["intrinsic"] == pytest.approx(1.25)

    def test_the_bid_ask_is_charged_on_entry(self):
        clean = self.a_trade(90.0, spread_pct=0.0)
        charged = self.a_trade(90.0, spread_pct=0.03)
        assert charged["debit"] > clean["debit"]
        assert charged["pnl_usd"] < clean["pnl_usd"]

    def test_commission_is_charged_both_ways_on_both_legs(self):
        t = self.a_trade(90.0, contracts=1)
        assert t["commission"] == pytest.approx(4 * oe.COMMISSION_PER_CONTRACT)

    def test_a_wider_volatility_assumption_makes_entry_more_expensive(self):
        cheap = self.a_trade(90.0, sigma=0.20)
        rich = self.a_trade(90.0, sigma=0.90)
        assert rich["debit"] > cheap["debit"]

    def test_max_profit_can_never_exceed_the_width(self):
        t = self.a_trade(1.0)          # price collapses far past both strikes
        assert t["intrinsic"] <= 2.5

    def test_it_records_the_assumption_it_priced_on(self):
        # The number is only readable next to what was assumed to produce it.
        assert self.a_trade(90.0)["sigma"] == pytest.approx(0.35)

    def test_an_unpriceable_trade_is_refused_rather_than_guessed(self):
        assert oe.simulate_trade(direction="put", spot=100.0, long_strike=100.0,
                                 short_strike=97.5, sigma=None, dte=2,
                                 exit_spot=90.0) is None


# ------------------------------------------------- walking the history

class TestBacktestOptions:
    def test_it_returns_no_trades_on_history_too_short_to_signal(self):
        out = oe.backtest_options(["2026-01-01"] * 10, [100.0] * 10, "X")
        assert out["trades"] == []

    def test_every_trade_carries_the_reason_it_fired(self):
        # "SHOW the proof with the logic to back it" — a row without its
        # reason is a number the reader has to take on faith.
        out = oe.backtest_options(_stamp(_falling()), _falling(), "X")
        for t in out["trades"]:
            assert t["label"]
            assert t["direction"] in ("call", "put")
            assert "entry_date" in t and "exit_date" in t

    def test_it_never_settles_on_a_bar_it_could_not_have_reached(self):
        closes = _falling()
        out = oe.backtest_options(_stamp(closes), closes, "X")
        for t in out["trades"]:
            assert t["exit_index"] > t["entry_index"]
            assert t["exit_index"] < len(closes)

    def test_a_summary_reports_win_rate_and_expectancy(self):
        out = oe.backtest_options(_stamp(_falling()), _falling(), "X")
        s = out["summary"]
        for key in ("trades", "wins", "losses", "win_rate", "expectancy_usd",
                    "total_usd", "avg_win_usd", "avg_loss_usd"):
            assert key in s

    def test_zero_trades_reports_none_rather_than_a_fake_win_rate(self):
        # 0/0 = 100% is the most flattering lie a backtest can tell.
        s = oe.backtest_options(["2026-01-01"] * 10, [100.0] * 10, "X")["summary"]
        assert s["trades"] == 0
        assert s["win_rate"] is None
        assert s["expectancy_usd"] is None

    def test_expectancy_is_total_over_trades(self):
        out = oe.backtest_options(_stamp(_falling()), _falling(), "X")
        s = out["summary"]
        if s["trades"]:
            assert s["expectancy_usd"] == pytest.approx(
                s["total_usd"] / s["trades"], abs=0.01)


class TestManagedExit:
    """Taking the money before the reversal — the trade the first cut never made.

    backtest_options holds every position to expiry. For a 2-DTE spread that is
    close to the worst available exit: the thing can be up 40% an hour after
    entry and still expire worthless, and the measurement would record only the
    zero. A scalper never sees that number because they are already out.

    So the exit rule is not a refinement, it is a different strategy, and it has
    to be measured as one. `manage_trade` walks the path bar by bar, reprices
    the spread with the time that is actually left, and leaves on whichever
    comes first: the target, the stop, or expiry.
    """

    def a_path(self, *prices):
        return list(prices)

    def test_a_move_in_your_favour_exits_at_the_target(self):
        out = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                              short_strike=97.5, sigma=0.40,
                              path=self.a_path(99.0, 97.0, 95.0),
                              t_total=2 / 252, take_profit=0.30, stop_loss=0.60)
        assert out["exit_reason"] == "target"
        assert out["pnl_pct"] >= 0.30

    def test_a_move_against_you_exits_at_the_stop(self):
        out = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                              short_strike=97.5, sigma=0.40,
                              path=self.a_path(101.0, 103.0, 106.0),
                              t_total=2 / 252, take_profit=0.30, stop_loss=0.40)
        assert out["exit_reason"] == "stop"

    def test_a_quiet_path_runs_to_expiry(self):
        out = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                              short_strike=97.5, sigma=0.40,
                              path=self.a_path(100.0, 100.0, 100.0),
                              t_total=2 / 252, take_profit=5.0, stop_loss=5.0)
        assert out["exit_reason"] == "expiry"

    def test_it_exits_on_the_FIRST_bar_that_qualifies(self):
        # Exiting on a later, better bar is hindsight. The first touch is what
        # a live order would actually have got.
        out = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                              short_strike=97.5, sigma=0.40,
                              path=self.a_path(95.0, 90.0, 85.0),
                              t_total=2 / 252, take_profit=0.30, stop_loss=0.60)
        assert out["exit_index"] == 0

    def test_taking_a_profit_beats_holding_a_round_trip(self):
        # THE point of the whole exercise: a path that spikes your way and then
        # comes all the way back. Managed exit banks it; hold-to-expiry gets zero.
        spike_and_revert = self.a_path(94.0, 96.0, 100.5)
        managed = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                                  short_strike=97.5, sigma=0.40,
                                  path=spike_and_revert, t_total=2 / 252,
                                  take_profit=0.30, stop_loss=0.90)
        held = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                               short_strike=97.5, sigma=0.40,
                               path=spike_and_revert, t_total=2 / 252,
                               take_profit=99.0, stop_loss=99.0)
        assert managed["exit_reason"] == "target"
        assert held["exit_reason"] == "expiry"
        assert managed["pnl_usd"] > held["pnl_usd"]

    def test_the_exit_is_charged_the_spread_too(self):
        tight = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                                short_strike=97.5, sigma=0.40,
                                path=self.a_path(95.0), t_total=2 / 252,
                                take_profit=0.10, stop_loss=0.90, spread_pct=0.0)
        wide = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                               short_strike=97.5, sigma=0.40,
                               path=self.a_path(95.0), t_total=2 / 252,
                               take_profit=0.10, stop_loss=0.90, spread_pct=0.05)
        assert wide["pnl_usd"] < tight["pnl_usd"]

    def test_time_decays_along_the_path(self):
        # A flat path still bleeds theta; the last bar must carry less time
        # value than the first.
        out = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                              short_strike=97.5, sigma=0.40,
                              path=self.a_path(100.0, 100.0, 100.0),
                              t_total=2 / 252, take_profit=9.0, stop_loss=9.0)
        assert out["exit_reason"] == "expiry"
        assert out["exit_value"] <= out["debit"]

    def test_an_empty_path_is_refused(self):
        assert oe.manage_trade("put", spot=100.0, long_strike=100.0,
                               short_strike=97.5, sigma=0.40, path=[],
                               t_total=2 / 252, take_profit=0.3,
                               stop_loss=0.3) is None

    def test_it_reports_how_long_it_was_in_the_trade(self):
        out = oe.manage_trade("put", spot=100.0, long_strike=100.0,
                              short_strike=97.5, sigma=0.40,
                              path=self.a_path(100.0, 99.0, 95.0),
                              t_total=2 / 252, take_profit=0.30, stop_loss=0.90)
        assert out["bars_held"] >= 1


class TestRegime:
    """Is the bearish signal broken, or only broken in a bull market?

    The measured period ran +52.9% on TSLA and +196% on SNDK. Betting against
    a tape like that loses regardless of signal quality, so a verdict on SELL
    that ignores regime is not a verdict at all — it is a description of the
    weather. Classifying each entry lets the two be told apart.

    The classification uses the 200-bar average ENDING AT the entry bar, so it
    is knowable at decision time. A regime label computed from the whole series
    would be hindsight wearing a lab coat.
    """

    # Needs more bars than the 200-wide regime window, so these fixtures run
    # longer than the ones the trade tests use.
    def test_price_above_its_long_average_is_an_uptrend(self):
        assert oe.regime_at(_rising(260), 259) == "uptrend"

    def test_price_below_its_long_average_is_a_downtrend(self):
        assert oe.regime_at(_falling(260), 259) == "downtrend"

    def test_too_little_history_has_no_regime(self):
        # Better to say "I don't know" than to average a partial window and
        # call the answer a trend.
        assert oe.regime_at([100.0] * 10, 9) is None
        assert oe.regime_at(_rising(260), 100) is None

    def test_it_never_looks_past_the_entry_bar(self):
        # Same guarantee the vol estimate makes, for the same reason.
        base = _rising(260)
        crash = base + [1.0] * 60
        assert oe.regime_at(crash, 259) == oe.regime_at(base, 259)

    def test_every_trade_is_stamped_with_the_regime_it_was_taken_in(self):
        out = oe.backtest_options(_stamp(_falling()), _falling(), "X")
        for t in out["trades"]:
            assert t["regime"] in ("uptrend", "downtrend", None)

    def test_results_can_be_split_by_regime(self):
        out = oe.backtest_options(_stamp(_falling()), _falling(), "X")
        split = oe.by_regime(out["trades"])
        assert set(split) <= {"uptrend", "downtrend", "unknown"}
        for bucket in split.values():
            assert "trades" in bucket and "win_rate" in bucket

    def test_splitting_preserves_every_trade(self):
        # A segmentation that quietly drops rows would flatter whichever
        # bucket it dropped them from.
        out = oe.backtest_options(_stamp(_falling()), _falling(), "X")
        split = oe.by_regime(out["trades"])
        assert sum(b["trades"] for b in split.values()) == len(out["trades"])


class TestNonOverlapping:
    """One position at a time — the difference between 2,804 trades and the truth.

    The first scalp run entered on EVERY bar carrying a signal. Signals persist
    for runs of bars, so a single move got counted twenty times over, each copy
    winning or losing together. That does not just inflate the trade count; it
    inflates confidence, because 2,804 correlated samples look like 2,804
    independent bets and they are nothing of the kind.

    A real trader holds one position, exits, and only then looks for the next
    entry. These tests pin that: no two trades may overlap, ever.
    """

    def _ramp(self, n=400):
        # A long clean downtrend: plenty of bearish signal, plenty of bars.
        return ([300.0 - i * 0.4 for i in range(n)],)

    def test_no_two_trades_overlap(self):
        (closes,) = self._ramp()
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        out = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                take_profit=0.25, stop_loss=0.5, max_bars=10)
        last_exit = -1
        for t in out["trades"]:
            assert t["entry_index"] > last_exit, "a trade started before the last one closed"
            last_exit = t["entry_index"] + t["bars_held"]

    def test_a_cooldown_is_respected(self):
        (closes,) = self._ramp()
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        out = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                take_profit=0.25, stop_loss=0.5, max_bars=10,
                                cooldown=20)
        prev = None
        for t in out["trades"]:
            if prev is not None:
                gap = t["entry_index"] - (prev["entry_index"] + prev["bars_held"])
                assert gap >= 20
            prev = t

    def test_it_yields_fewer_trades_than_entering_on_every_signal_bar(self):
        # The whole point: honest counting collapses the sample. Compared
        # against the real bar-by-bar count rather than an invented fraction —
        # a made-up threshold tests the threshold, not the behaviour.
        import backtest as bt
        (closes,) = self._ramp()
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        signal_bars = sum(1 for lab in bt._compute_labels(closes)
                          if lab in oe.BULL or lab in oe.BEAR)
        clean = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                  take_profit=0.25, stop_loss=0.5, max_bars=10)
        assert signal_bars > 0
        assert len(clean["trades"]) < signal_bars

    def test_a_cooldown_collapses_the_sample_further(self):
        (closes,) = self._ramp()
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        tight = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                  take_profit=0.25, stop_loss=0.5, max_bars=10)
        spaced = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                   take_profit=0.25, stop_loss=0.5, max_bars=10,
                                   cooldown=30)
        assert len(spaced["trades"]) < len(tight["trades"])

    def test_every_trade_still_carries_its_evidence(self):
        (closes,) = self._ramp()
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        out = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                take_profit=0.25, stop_loss=0.5, max_bars=10)
        for t in out["trades"]:
            assert t["label"] and t["direction"] in ("call", "put")
            assert t["exit_reason"] in ("target", "stop", "expiry")
            assert "entry_date" in t

    def test_the_squeeze_gate_only_ever_removes_trades(self):
        (closes,) = self._ramp()
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        base = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                 take_profit=0.25, stop_loss=0.5, max_bars=10)
        gated = oe.backtest_scalp(highs, lows, closes, _stamp(closes), "X",
                                  take_profit=0.25, stop_loss=0.5, max_bars=10,
                                  squeeze_only=True)
        assert len(gated["trades"]) <= len(base["trades"])

    def test_too_little_history_produces_nothing_rather_than_erroring(self):
        out = oe.backtest_scalp([1.0] * 10, [1.0] * 10, [1.0] * 10,
                                ["2026-01-01"] * 10, "X")
        assert out["trades"] == []
        assert out["summary"]["win_rate"] is None


class TestAssumptionSensitivity:
    def test_it_reports_results_across_volatility_assumptions(self):
        # Entry price is the one modelled number, so the honest presentation
        # is a range: if the conclusion flips between plausible IVs, there is
        # no conclusion.
        out = oe.sensitivity(_stamp(_falling()), _falling(), "X")
        assert len(out["bands"]) >= 3
        for b in out["bands"]:
            assert "iv_multiple" in b and "total_usd" in b

    def test_paying_more_for_entry_never_improves_the_result(self):
        out = oe.sensitivity(_stamp(_falling()), _falling(), "X")
        totals = [b["total_usd"] for b in
                  sorted(out["bands"], key=lambda x: x["iv_multiple"])]
        assert totals == sorted(totals, reverse=True)
