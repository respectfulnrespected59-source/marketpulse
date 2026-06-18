"""Tests for options.py — Black-Scholes Greeks + the strategy builders that
turn a chain into a defined-risk play. The chain() fetch is mocked so nothing
touches CBOE during tests.
"""
from __future__ import annotations

import pytest

import options as opt

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------- Greeks
def test_greeks_atm_call_delta_near_half():
    # spot=strike=100, t=1y, sigma=20%, r=4% -> d1=0.3, delta=N(0.3)~0.618
    g = opt.greeks(100, 100, 1.0, 0.20, "call")
    assert g["delta"] == pytest.approx(0.618, abs=0.005)
    assert 0 < g["delta"] < 1
    assert g["gamma"] > 0 and g["vega"] > 0


def test_greeks_put_call_delta_parity():
    call = opt.greeks(100, 100, 1.0, 0.20, "call")["delta"]
    put = opt.greeks(100, 100, 1.0, 0.20, "put")["delta"]
    # with q=0, call_delta - put_delta == 1
    assert call - put == pytest.approx(1.0, abs=0.01)
    assert put < 0


def test_greeks_reject_nonpositive_inputs():
    assert opt.greeks(0, 100, 1.0, 0.20, "call") == {}
    assert opt.greeks(100, 100, 0.0, 0.20, "call") == {}
    assert opt.greeks(100, 100, 1.0, 0.0, "call") == {}


def test_greeks_theta_is_negative_for_long_options():
    # Long options bleed time value -> theta < 0 on both sides.
    assert opt.greeks(100, 100, 0.5, 0.30, "call")["theta"] < 0
    assert opt.greeks(100, 100, 0.5, 0.30, "put")["theta"] < 0


# ----------------------------------------------------------------- suggest_spread
def test_suggest_spread_builds_call_debit_spread():
    ch = {
        "calls": [
            {"strike": 100, "delta": 0.40, "ask": 5.0, "bid": 4.8, "last": 4.9},
            {"strike": 105, "delta": 0.25, "ask": 2.0, "bid": 1.8, "last": 1.9},
        ],
        "puts": [],
    }
    s = opt.suggest_spread(ch, "call")
    assert s["type"] == "call debit spread"
    assert s["long"]["strike"] == 100 and s["short"]["strike"] == 105
    assert s["debit"] == 3.2          # 5.0 ask - 1.8 bid
    assert s["width"] == 5
    assert s["max_profit"] == 1.8     # width - debit
    assert s["breakeven"] == 103.2    # long strike + debit (call)
    assert s["per_contract"] == 320.0
    assert s["risk_reward"] == 0.56


def test_suggest_spread_rejects_bad_direction():
    assert opt.suggest_spread({"calls": [], "puts": []}, "sideways") is None


def test_suggest_spread_returns_none_on_chain_error():
    assert opt.suggest_spread({"error": "boom"}, "call") is None


# ----------------------------------------------------------------- suggest_strangle
def test_suggest_strangle_either_way_play():
    ch = {
        "spot": 100,
        "calls": [{"strike": 105, "delta": 0.20, "ask": 2.0, "last": 1.9}],
        "puts": [{"strike": 95, "delta": -0.20, "ask": 1.5, "last": 1.4}],
    }
    s = opt.suggest_strangle(ch)
    assert s["type"] == "long strangle"
    assert s["debit"] == 3.5
    assert s["per_contract"] == 350.0
    assert s["upper_breakeven"] == 108.5   # call strike + debit
    assert s["lower_breakeven"] == 91.5    # put strike - debit
    assert s["move_up_pct"] == 8.5
    assert s["move_down_pct"] == 8.5


def test_suggest_strangle_none_without_spot():
    ch = {"spot": 0, "calls": [], "puts": []}
    assert opt.suggest_strangle(ch) is None


# ----------------------------------------------------------------- probe_plan
def test_probe_plan_picks_cheapest_readable_otm():
    ch = {
        "lean": {"direction": "call"},
        "spot": 100,
        "calls": [
            {"strike": 105, "delta": 0.30, "ask": 0.50, "last": 0.5},
            {"strike": 110, "delta": 0.10, "ask": 0.20, "last": 0.2},  # below Δ floor
        ],
        "puts": [],
    }
    plan = opt.probe_plan(ch, pot=300, probe_frac=0.20, min_delta=0.25)
    assert plan["budget"] == 60
    assert plan["direction"] == "call"
    assert plan["probe"]["strike"] == 105   # 110 excluded: |delta| 0.10 < 0.25 floor
    assert plan["probe"]["cost"] == 50      # 0.50 * 100
    assert plan["qualifies"] is True
    assert plan["min_pot"] == 250           # cost / probe_frac


def test_probe_plan_no_lean_returns_wait_note():
    plan = opt.probe_plan({"lean": {}, "spot": 100, "calls": [], "puts": []})
    assert plan["qualifies"] is None
    assert "lean" in plan["note"].lower()


def test_probe_plan_none_without_spot():
    assert opt.probe_plan({"lean": {"direction": "call"}, "spot": 0}) is None


def test_probe_plan_floor_unreachable_is_disqualified():
    ch = {
        "lean": {"direction": "call"},
        "spot": 100,
        "calls": [{"strike": 110, "delta": 0.10, "ask": 0.20}],  # all below floor
        "puts": [],
    }
    plan = opt.probe_plan(ch, min_delta=0.25)
    assert plan["qualifies"] is False


# ----------------------------------------------------------------- direction_nudge
def test_direction_nudge_no_lean_is_none():
    assert opt.direction_nudge({}) is None


def test_direction_nudge_either_way():
    out = opt.direction_nudge({"lean": {"label": "x"}, "either_way": True})
    assert out["dir"] == "either-way"


def test_direction_nudge_bullish():
    out = opt.direction_nudge({"lean": {"label": "BUY", "direction": "call"}})
    assert out["dir"] == "bullish"


def test_direction_nudge_bearish():
    out = opt.direction_nudge({"lean": {"label": "SELL", "direction": "put"}})
    assert out["dir"] == "bearish"


def test_direction_nudge_stand_aside_when_no_direction():
    out = opt.direction_nudge({"lean": {"label": "NEUTRAL"}})
    assert out["dir"] == "stand-aside"


# ----------------------------------------------------------------- decision_read
def _chain_with_spread():
    return {
        "spot": 100,
        "calls": [{"strike": 100, "iv": 30.0, "delta": 0.5}],
        "puts": [],
        "squeeze": {"weekly": {"state": "off"}, "biweekly": {"state": "off"},
                    "coiled": False, "conflict": False},
        "either_way": False,
        "dte": 30,
        "spread": {"direction": "call", "type": "call debit spread",
                   "long": {"strike": 100}, "short": {"strike": 105},
                   "per_contract": 320, "max_profit": 1.8, "risk_reward": 0.56},
    }


def test_decision_read_six_steps_and_rules():
    sig = {"label": "BUY", "rsi": 55, "htf": 1,
           "reasons": ["above SMA50", "golden cross (50>200)"]}
    read = opt.decision_read(_chain_with_spread(), sig)
    assert len(read["steps"]) == 6
    assert len(read["risk"]) == 3
    assert "call" in read["bottom_line"].lower()
    assert "not a recommendation" in read["disclaimer"].lower()


def test_decision_read_none_on_error_or_missing_signal():
    assert opt.decision_read({"error": "x"}, {"label": "BUY"}) is None
    assert opt.decision_read(_chain_with_spread(), None) is None


# ----------------------------------------------------------------- chain (mocked)
def _fake_payload():
    return {"data": {
        "current_price": 100.0,
        "options": [
            {"option": "TEST300117C00100000", "bid": 4.8, "ask": 5.0,
             "last_trade_price": 4.9, "iv": 0.30, "delta": 0.5, "gamma": 0.02,
             "theta": -0.05, "vega": 0.1, "rho": 0.03,
             "open_interest": 10, "volume": 5},
            {"option": "TEST300117P00100000", "bid": 4.6, "ask": 4.8,
             "last_trade_price": 4.7, "iv": 0.30, "delta": -0.5, "gamma": 0.02,
             "theta": -0.05, "vega": 0.1, "rho": -0.03,
             "open_interest": 8, "volume": 4},
        ],
    }}


def test_chain_parses_occ_and_greeks(monkeypatch):
    monkeypatch.setattr(opt, "_get", lambda url: _fake_payload())
    ch = opt.chain("test")
    assert ch["symbol"] == "TEST"
    assert ch["spot"] == 100.0
    assert ch["expiry"] == "2030-01-17"
    assert ch["source"] == "CBOE delayed"
    assert len(ch["calls"]) == 1 and len(ch["puts"]) == 1
    call = ch["calls"][0]
    assert call["strike"] == 100.0
    assert call["delta"] == 0.5
    assert call["iv"] == 30.0          # 0.30 * 100, 1dp
    assert call["itm"] is False        # strike 100 not < spot 100


def test_chain_fetch_failure_returns_error(monkeypatch):
    def boom(url):
        raise RuntimeError("network down")
    monkeypatch.setattr(opt, "_get", boom)
    assert "error" in opt.chain("test")


def test_chain_empty_options_returns_error(monkeypatch):
    monkeypatch.setattr(opt, "_get", lambda url: {"data": {"options": []}})
    assert "error" in opt.chain("test")


def test_chain_backfills_missing_greeks_with_black_scholes(monkeypatch):
    # CBOE sometimes omits Greeks; with only IV present the chain must fall back
    # to the Black-Scholes computation rather than returning null Greeks.
    payload = {"data": {
        "current_price": 100.0,
        "options": [
            {"option": "TEST300117C00100000", "bid": 4.8, "ask": 5.0,
             "last_trade_price": 4.9, "iv": 0.30,  # no delta/gamma/theta/vega/rho
             "open_interest": 10, "volume": 5},
        ],
    }}
    monkeypatch.setattr(opt, "_get", lambda url: payload)
    call = opt.chain("test")["calls"][0]
    assert call["delta"] is not None and 0 < call["delta"] < 1
    assert call["gamma"] is not None and call["vega"] is not None


# ---- decision_read alternate branches (either-way strangle / no-trade) ----
def _chain_coiled_either_way():
    return {
        "spot": 100,
        "calls": [{"strike": 100, "iv": 65.0, "delta": 0.5}],  # high-IV regime
        "puts": [],
        "squeeze": {"weekly": {"state": "on", "bars": 4},
                    "biweekly": {"state": "on", "bars": 2},
                    "coiled": True, "conflict": True},
        "either_way": True,
        "dte": 30,
        "strangle": {"move_up_pct": 8.5, "move_down_pct": 8.5, "per_contract": 350},
    }


def test_decision_read_either_way_recommends_strangle():
    sig = {"label": "NEUTRAL", "rsi": 50, "htf": 0, "reasons": ["RSI 50"]}
    read = opt.decision_read(_chain_coiled_either_way(), sig)
    assert "strangle" in read["bottom_line"].lower()
    # high IV regime should be flagged in the volatility step
    assert any("implied vol" in s["v"].lower() for s in read["steps"])


def test_decision_read_no_edge_recommends_standing_aside():
    ch = {
        "spot": 100,
        "calls": [{"strike": 100, "iv": 20.0, "delta": 0.5}],
        "puts": [],
        "squeeze": {"weekly": {"state": "off"}, "biweekly": {"state": "off"},
                    "coiled": False, "conflict": False},
        "either_way": False,
        "dte": 30,
        # no spread, no strangle -> no clean edge
    }
    sig = {"label": "NEUTRAL", "rsi": 50, "htf": 0, "reasons": ["RSI 50"]}
    read = opt.decision_read(ch, sig)
    assert "aside" in read["bottom_line"].lower()
