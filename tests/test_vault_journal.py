"""The Obsidian trading journal: a record that cannot quietly flatter itself.

A trading journal is only worth keeping if the boring days are in it. If the
writer skips no-signal names, or drops a symbol whose data failed, or omits the
open-positions section when it has no snapshot, then months later the surviving
notes read as a complete record of a strategy that was actually only sampled on
its interesting days. That is how a losing system looks like a winning one.

So these tests hold three lines:

  * Every symbol asked for appears in the note. Sat-out days say "sat out";
    failed fetches say "unavailable". Nothing is silently dropped.
  * Frontmatter is machine-readable, because the whole point is querying
    months of it with Dataview later.
  * Missing or malformed upstream data degrades to a visible gap, never a
    crash and never an invented number.

Pure rendering only — no network, no filesystem, no clock.
"""

import pytest

import vault_journal as vj

pytestmark = pytest.mark.unit


def a_row(symbol="TSLA", label="STRONG SELL", price=339.21, rsi=48.8, error=None):
    if error:
        return {"symbol": symbol, "error": error}
    return {
        "symbol": symbol, "price": price, "change": -0.55,
        "signal": {"label": label, "rsi": rsi, "reasons": ["MACD bullish", "below SMA50"]},
        "guides": {"stack": "bear", "vwap": 340.1, "vs_vwap": "below"},
        "squeeze": {"weekly": {"state": "off", "mom": "bear"}},
    }


def a_chain(symbol="TSLA", spot=339.21, signal="STRONG SELL"):
    return {
        "symbol": symbol, "spot": spot, "expiry": "2026-08-19", "dte": 2,
        "lean": {"label": signal, "direction": "put"},
        "spread": {"type": "put debit spread", "direction": "put",
                   "long": {"strike": 337.5}, "short": {"strike": 332.5},
                   "per_contract": 189, "max_profit": 3.11, "max_loss": 1.89,
                   "breakeven": 335.61, "risk_reward": 1.65},
        # Real options.probe_plan shape — qualifies / probe.cost / min_pot.
        # An earlier draft of these tests invented {"verdict", "cheapest"} and
        # passed against nothing, which is why the live note rendered a column
        # of dashes. Fixtures must mirror the producer, not the consumer's hope.
        "probe_plan": {"pot": 300, "budget": 60, "direction": "put",
                       "qualifies": False, "min_pot": 1240,
                       "probe": {"strike": 335.0, "cost": 248,
                                 "delta": -0.28, "move_pct": 1.6}},
    }


class TestFrontmatter:
    def test_it_opens_and_closes_the_yaml_block(self):
        fm = vj.frontmatter("2026-08-17", [], [], None)
        assert fm.startswith("---\n")
        assert fm.rstrip().endswith("---")

    def test_it_carries_the_date_for_dataview(self):
        assert "date: 2026-08-17" in vj.frontmatter("2026-08-17", [], [], None)

    def test_it_counts_the_signals_it_saw(self):
        fm = vj.frontmatter("2026-08-17", [a_chain(), a_chain("NVDA", signal="STRONG BUY")], [], None)
        assert "strong_sell: 1" in fm
        assert "strong_buy: 1" in fm

    def test_a_day_with_no_signal_is_still_a_recorded_day(self):
        # The sat-out days are the evidence the engine has discipline.
        fm = vj.frontmatter("2026-08-17", [], [], None)
        assert "date: 2026-08-17" in fm
        assert "watchlist_count: 0" in fm

    def test_it_records_how_many_positions_were_open(self):
        fm = vj.frontmatter("2026-08-17", [], [], [{"id": "a", "net_usd": -540}])
        assert "open_positions: 1" in fm

    def test_a_missing_position_snapshot_is_marked_unknown_not_zero(self):
        # None means "we could not see the book", which is not the same claim
        # as "the book was empty".
        fm = vj.frontmatter("2026-08-17", [], [], None)
        assert "open_positions: unknown" in fm


class TestWatchlistSection:
    def test_every_symbol_asked_for_appears(self):
        body = vj.watch_section([a_chain("TSLA"), a_chain("NVDA"), a_chain("MU")])
        for s in ("TSLA", "NVDA", "MU"):
            assert s in body

    def test_a_name_with_no_spread_is_recorded_as_sat_out(self):
        quiet = {"symbol": "MRVL", "spot": 70.1, "lean": {"label": "NEUTRAL"}}
        body = vj.watch_section([quiet])
        assert "MRVL" in body
        assert "sat out" in body.lower()

    def test_a_failed_fetch_is_recorded_as_unavailable(self):
        body = vj.watch_section([{"symbol": "WDC", "error": "chain fetch failed"}])
        assert "WDC" in body
        assert "unavailable" in body.lower()

    def test_a_probe_that_does_not_fit_the_pot_says_WALK(self):
        # qualifies=False is the discipline signal — the single most useful
        # thing on the row, and it must never render as a dash.
        body = vj.watch_section([a_chain()])
        assert "walk" in body.lower()
        assert "248" in body          # what the cheapest usable probe costs
        assert "1240" in body         # the pot it would actually need

    def test_a_probe_that_fits_says_so(self):
        ch = a_chain()
        ch["probe_plan"] = {"qualifies": True, "budget": 60, "min_pot": 210,
                            "probe": {"strike": 335.0, "cost": 42, "delta": -0.27}}
        assert "fits" in vj.watch_section([ch]).lower()

    def test_no_directional_lean_is_recorded_as_no_lean(self):
        ch = a_chain()
        ch["probe_plan"] = {"qualifies": None, "budget": 60,
                            "note": "No directional lean right now"}
        assert "no lean" in vj.watch_section([ch]).lower()

    def test_a_missing_probe_plan_does_not_crash_the_row(self):
        ch = a_chain()
        ch.pop("probe_plan")
        assert "TSLA" in vj.watch_section([ch])

    def test_it_shows_the_spread_that_was_suggested(self):
        body = vj.watch_section([a_chain()])
        assert "337.5" in body and "332.5" in body

    def test_an_empty_watchlist_says_so_rather_than_rendering_nothing(self):
        assert "no watchlist data" in vj.watch_section([]).lower()


class TestSqueeze:
    """The TTM squeeze is half the read — a coiled squeeze is the setup and a
    fired one is the trigger. Omitting it, as the first version did, leaves the
    journal recording direction with no notion of whether a move is loading."""

    def test_a_coiled_squeeze_shows_ON_and_its_bar_count(self):
        assert "ON·4" in vj.fmt_squeeze(
            {"state": "on", "bars": 4, "mom": "bull", "accel": "rising"})

    def test_a_fired_squeeze_says_FIRED(self):
        assert "FIRED" in vj.fmt_squeeze(
            {"state": "fired", "bars": 1, "mom": "bear", "accel": "falling"})

    def test_bearish_momentum_points_down(self):
        assert "▼" in vj.fmt_squeeze(
            {"state": "off", "bars": 0, "mom": "bear", "accel": "falling"})

    def test_bullish_momentum_points_up(self):
        assert "▲" in vj.fmt_squeeze(
            {"state": "off", "bars": 0, "mom": "bull", "accel": "rising"})

    def test_a_missing_squeeze_is_n_a_not_a_crash(self):
        assert vj.fmt_squeeze(None) == "n/a"

    def test_a_malformed_squeeze_does_not_crash(self):
        assert vj.fmt_squeeze({"state": "on"}) is not None

    def test_the_watchlist_row_carries_weekly_and_biweekly(self):
        ch = a_chain()
        ch["squeeze"] = {
            "weekly": {"state": "off", "bars": 0, "mom": "bear", "accel": "falling"},
            "biweekly": {"state": "fired", "bars": 1, "mom": "bear", "accel": "falling"},
            "coiled": False, "conflict": False,
        }
        body = vj.watch_section([ch])
        assert "FIRED" in body
        assert "W " in body or "2W" in body

    def test_a_coiled_name_is_flagged_because_that_is_the_setup(self):
        ch = a_chain()
        ch["squeeze"] = {
            "weekly": {"state": "on", "bars": 3, "mom": "bull", "accel": "rising"},
            "biweekly": None, "coiled": True, "conflict": False,
        }
        assert "coiled" in vj.watch_section([ch]).lower()

    def test_the_frontmatter_counts_coiled_names_for_dataview(self):
        ch = a_chain()
        ch["squeeze"] = {"weekly": None, "biweekly": None,
                         "coiled": True, "conflict": False}
        assert "coiled: 1" in vj.frontmatter("2026-08-17", [ch], [], None)

    def test_no_squeeze_data_still_renders_the_row(self):
        ch = a_chain()
        ch.pop("squeeze", None)
        assert "TSLA" in vj.watch_section([ch])


class TestPositionsSection:
    def test_a_missing_snapshot_is_stated_plainly(self):
        body = vj.positions_section(None)
        assert "no open-position snapshot" in body.lower()

    def test_an_empty_book_is_different_from_a_missing_one(self):
        body = vj.positions_section([])
        assert "no open positions" in body.lower()
        assert "snapshot" not in body.lower()

    def test_it_renders_the_live_mark_and_pnl(self):
        body = vj.positions_section([{
            "id": "x", "symbol": "TSLA", "contracts": 25, "mark": 1.82,
            "net_usd": -540.0, "dte": 2, "status": "open",
        }])
        assert "TSLA" in body and "-540" in body.replace("−", "-")

    def test_an_unquoted_position_is_not_shown_as_flat(self):
        # net_usd None must never render as 0.00 — that hides a real loss.
        body = vj.positions_section([{
            "id": "x", "symbol": "TSLA", "contracts": 1,
            "mark": None, "net_usd": None, "status": "unquoted",
        }])
        assert "0.00" not in body
        assert "unquoted" in body.lower()


class TestRenderNote:
    def test_it_is_a_complete_note(self):
        note = vj.render_note("2026-08-17", [a_chain()], [], None)
        assert note.startswith("---")
        assert "# Trading Journal" in note
        assert "2026-08-17" in note

    def test_it_always_carries_the_not_advice_line(self):
        assert "not advice" in vj.render_note("2026-08-17", [], [], None).lower()

    def test_it_notes_the_chain_delay_so_a_fill_is_never_over_trusted(self):
        assert "delayed" in vj.render_note("2026-08-17", [a_chain()], [], None).lower()

    def test_a_totally_empty_day_still_produces_a_note(self):
        # A missing file for a trading day is indistinguishable from a crash.
        note = vj.render_note("2026-08-17", [], [], None)
        assert "2026-08-17" in note
        assert len(note) > 100

    def test_malformed_rows_do_not_crash_the_note(self):
        note = vj.render_note("2026-08-17", [{}, {"symbol": None}], [None], None)
        assert "2026-08-17" in note


class TestScanSection:
    def test_it_lists_the_cheap_probes_it_found(self):
        body = vj.scan_section([
            {"symbol": "F", "spot": 11.4, "lean": {"label": "BUY"},
             "probe_plan": {"qualifies": True, "budget": 60,
                            "probe": {"strike": 12.0, "cost": 42, "delta": 0.3}}},
        ])
        assert "F" in body and "42" in body
        assert "fits" in body.lower()

    def test_the_sweep_flags_the_ones_a_small_pot_can_actually_afford(self):
        # This is the entire point of the scan universe: the watchlist runs
        # rich, so a day's only actionable row may be down here.
        body = vj.scan_section([
            {"symbol": "F", "spot": 11.4, "lean": {"label": "BUY"},
             "probe_plan": {"qualifies": True, "budget": 60,
                            "probe": {"strike": 12.0, "cost": 42}}},
            {"symbol": "PLTR", "spot": 175.11, "lean": {"label": "BUY"},
             "probe_plan": {"qualifies": False, "budget": 60, "min_pot": 900,
                            "probe": {"strike": 180.0, "cost": 180}}},
        ])
        assert "fits" in body.lower() and "walk" in body.lower()

    def test_an_empty_sweep_says_nothing_qualified(self):
        assert "nothing" in vj.scan_section([]).lower()


class TestNotePath:
    def test_the_filename_is_the_date_so_reruns_overwrite(self):
        # Re-running the job must update today's note, never append a second one.
        assert vj.note_name("2026-08-17") == "2026-08-17.md"


class TestHeartbeat:
    def test_a_good_run_records_success_and_the_date(self):
        hb = vj.heartbeat_text("2026-08-17", ok=True, detail="6 watch · 20 scan")
        assert "ok" in hb.lower()
        assert "2026-08-17" in hb

    def test_a_failed_run_says_FAILED_loudly(self):
        # This file is the alarm. If it cannot go red it is not a check.
        hb = vj.heartbeat_text("2026-08-17", ok=False, detail="chain fetch failed")
        assert "FAILED" in hb
        assert "chain fetch failed" in hb
