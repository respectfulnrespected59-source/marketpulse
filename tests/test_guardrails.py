"""Tests for agent/guardrails.py — the independent safety controls that stand
between a proposal and a real order. These protect money, so every gate is
tested for both the allow path and the refuse path.

State (ledger / circuit / HALT / audit) is redirected to a per-test tmp dir via
the autouse `isolated_state` fixture, so tests never read or write the agent's
real agent/data/ directory and never leak state between tests.
"""
from __future__ import annotations

import time
from decimal import Decimal

import pytest

import config
import guardrails as gr
import store

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point all persistence at a throwaway directory for the duration of a test.

    store._path() reads config.DATA_DIR at call time, so patching the attribute
    is enough to fully isolate ledger.json / circuit.json / HALT / audit log.
    """
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    yield


def _proposal(**overrides):
    base = {
        "id": "p1",
        "symbol": "AAPL",
        "side": "buy",
        "kind": "stock",
        "notional": "50",
        "ref_price": 100.0,
        "ts": time.time(),
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------- spend limits
def test_check_spend_within_caps_passes():
    gr.check_spend(Decimal("50"))  # under per-trade 100 and daily 400


def test_check_spend_rejects_nonpositive():
    with pytest.raises(gr.SpendLimitError):
        gr.check_spend(Decimal("0"))


def test_check_spend_rejects_over_single_cap():
    with pytest.raises(gr.SpendLimitError):
        gr.check_spend(config.MAX_SINGLE_TX_USD + Decimal("1"))


def test_check_spend_rejects_when_daily_cap_breached():
    store.record_spend("350", "AAPL", "o1")     # 350 already spent today
    with pytest.raises(gr.SpendLimitError):
        gr.check_spend(Decimal("60"))           # 350 + 60 = 410 > 400


def test_check_spend_allows_up_to_daily_cap():
    store.record_spend("350", "AAPL", "o1")
    gr.check_spend(Decimal("40"))               # 350 + 40 = 390 <= 400


# ----------------------------------------------------------------- kill switch
def test_check_not_halted_passes_when_clear():
    gr.check_not_halted()


def test_check_not_halted_raises_after_halt():
    store.engage_halt("manual test halt")
    with pytest.raises(gr.HaltError):
        gr.check_not_halted()


# ----------------------------------------------------------------- staleness
def test_check_fresh_passes_for_recent_proposal():
    gr.check_fresh(_proposal(ts=time.time()))


def test_check_fresh_raises_for_stale_proposal():
    old = time.time() - (config.PROPOSAL_TTL + 60)
    with pytest.raises(gr.StaleProposalError):
        gr.check_fresh(_proposal(ts=old))


# ----------------------------------------------------------------- allow-list
def test_check_symbol_allowed_for_universe_stock():
    gr.check_symbol_allowed(_proposal(symbol="AAPL"))


def test_check_symbol_allowed_for_universe_crypto_pair():
    gr.check_symbol_allowed(_proposal(symbol="BTC/USD"))


def test_check_symbol_rejects_off_universe():
    with pytest.raises(gr.DisallowedSymbolError):
        gr.check_symbol_allowed(_proposal(symbol="FAKE"))


# ----------------------------------------------------------------- slippage
def test_check_slippage_buy_within_band_passes():
    # stock band 0.5%; +0.4% move is tolerable for a buy
    gr.check_slippage(_proposal(side="buy", ref_price=100.0), current_price=100.4)


def test_check_slippage_buy_adverse_move_raises():
    with pytest.raises(gr.SlippageError):
        gr.check_slippage(_proposal(side="buy", ref_price=100.0), current_price=100.6)


def test_check_slippage_sell_adverse_move_raises():
    # a sell is hurt by a lower price; -0.6% is beyond the band
    with pytest.raises(gr.SlippageError):
        gr.check_slippage(_proposal(side="sell", ref_price=100.0), current_price=99.4)


def test_check_slippage_no_reference_price_raises():
    with pytest.raises(gr.SlippageError):
        gr.check_slippage(_proposal(ref_price=0), current_price=100.0)


def test_check_slippage_no_live_price_raises():
    with pytest.raises(gr.SlippageError):
        gr.check_slippage(_proposal(ref_price=100.0), current_price=0)


def test_check_slippage_crypto_band_is_wider():
    # 1% move would trip the 0.5% stock band but not the 1.5% crypto band
    gr.check_slippage(_proposal(kind="crypto", side="buy", ref_price=100.0),
                      current_price=101.0)


# ----------------------------------------------------------------- circuit breaker
def test_circuit_first_call_sets_baseline_no_raise():
    gr.update_equity_and_check(1000.0)
    assert store.load_circuit()["day_start_equity"] == 1000.0


def test_circuit_small_drawdown_does_not_halt():
    gr.update_equity_and_check(1000.0)      # baseline
    gr.update_equity_and_check(960.0)       # -4% < 5% limit
    assert not store.is_halted()


def test_circuit_breach_halts_and_raises():
    gr.update_equity_and_check(1000.0)      # baseline
    with pytest.raises(gr.CircuitBreakerError):
        gr.update_equity_and_check(940.0)   # -6% breaches the -5% limit
    assert store.is_halted()


# ----------------------------------------------------------------- consecutive losses
def test_consecutive_losses_halt_at_threshold():
    for _ in range(config.MAX_CONSECUTIVE_LOSSES):
        gr.record_trade_result(is_win=False)
    assert store.is_halted()


def test_a_win_resets_loss_streak():
    gr.record_trade_result(is_win=False)
    gr.record_trade_result(is_win=False)
    gr.record_trade_result(is_win=True)     # reset
    assert store.load_circuit()["consecutive_losses"] == 0
    assert not store.is_halted()


# ----------------------------------------------------------------- full gate
def test_authorize_send_happy_path_passes_and_audits():
    gr.authorize_send(_proposal(), current_price=100.2)
    events = [a["event"] for a in store.read_audit()]
    assert "authorized" in events


def test_authorize_send_without_live_price_fails_closed():
    with pytest.raises(gr.SlippageError):
        gr.authorize_send(_proposal(), current_price=None)


def test_authorize_send_blocks_when_halted():
    store.engage_halt("test")
    with pytest.raises(gr.HaltError):
        gr.authorize_send(_proposal(), current_price=100.0)


def test_authorize_send_blocks_off_universe_symbol():
    with pytest.raises(gr.DisallowedSymbolError):
        gr.authorize_send(_proposal(symbol="FAKE"), current_price=100.0)


def test_authorize_send_blocks_oversized_buy():
    big = _proposal(notional=str(config.MAX_SINGLE_TX_USD + Decimal("1")))
    with pytest.raises(gr.SpendLimitError):
        gr.authorize_send(big, current_price=100.2)


def test_authorize_send_sell_skips_spend_cap():
    # A sell reduces exposure; an oversized notional must NOT be spend-capped.
    sell = _proposal(side="sell",
                     notional=str(config.MAX_SINGLE_TX_USD + Decimal("500")))
    gr.authorize_send(sell, current_price=100.0)  # passes other gates, no raise
