"""Agent configuration — paper-first, propose-and-approve trading layer.

Everything here is conservative on purpose. The numbers below are the *hard
ceilings* the agent will refuse to cross; they are enforced in guardrails.py
independently from any signal the model produces (see the security skill:
"Spend limits are enforced independently from model output").

All real secrets come from environment variables, never this file.
"""
from __future__ import annotations

import os
from decimal import Decimal

# ----------------------------------------------------------------- mode
# "propose"  -> agent only writes proposals; a human must `approve` to send.
# "auto"     -> agent submits within guardrails (DO NOT use until paper-proven).
MODE = os.environ.get("MP_AGENT_MODE", "propose").lower()

# Paper vs live. We hard-default to paper. Going live is a deliberate env flip
# AND requires live keys; there is no accidental path to real money.
PAPER = os.environ.get("MP_ALPACA_PAPER", "true").lower() != "false"

ALPACA_BASE = (
    "https://paper-api.alpaca.markets" if PAPER
    else "https://api.alpaca.markets"
)
ALPACA_DATA_BASE = "https://data.alpaca.markets"

# Keys: env only. Empty string when unset so the CLI can warn cleanly.
ALPACA_KEY_ID = os.environ.get("MP_ALPACA_KEY_ID", "")
ALPACA_SECRET = os.environ.get("MP_ALPACA_SECRET", "")

# ----------------------------------------------------------------- universe
# Symbols the agent is allowed to consider. Stocks use plain tickers; crypto
# uses Alpaca's PAIR form ("BTC/USD"). The CoinGecko id is what the existing
# MarketPulse engine needs, so we map crypto pair -> coingecko id here.
STOCK_UNIVERSE = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SPY", "QQQ"]

# alpaca pair : coingecko id
CRYPTO_UNIVERSE = {
    "BTC/USD": "bitcoin",
    "ETH/USD": "ethereum",
    "SOL/USD": "solana",
    "LTC/USD": "litecoin",
    "LINK/USD": "chainlink",
}

# ----------------------------------------------------------------- risk caps
# Per-trade and per-day spend ceilings (USD). Start tiny. These are the single
# most important safety numbers in the whole system.
MAX_SINGLE_TX_USD = Decimal(os.environ.get("MP_MAX_SINGLE_TX_USD", "100"))
MAX_DAILY_SPEND_USD = Decimal(os.environ.get("MP_MAX_DAILY_SPEND_USD", "400"))

# Notional sized per proposal (kept <= MAX_SINGLE_TX_USD).
PER_TRADE_USD = Decimal(os.environ.get("MP_PER_TRADE_USD", "50"))

# Circuit breaker thresholds.
MAX_CONSECUTIVE_LOSSES = int(os.environ.get("MP_MAX_CONSECUTIVE_LOSSES", "3"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MP_MAX_DAILY_LOSS_PCT", "0.05"))  # 5%

# Pre-send slippage band — the stock/crypto analog of the skill's mandatory
# `min_amount_out`. At approve time we pull a LIVE price and refuse the order if
# it has moved against us by more than this fraction since the signal was
# computed. Crypto is noisier, so it gets a wider band. Enforced in
# guardrails.check_slippage, independently of the signal.
MAX_SLIPPAGE_PCT = {
    "stock": float(os.environ.get("MP_MAX_SLIPPAGE_STOCK", "0.005")),    # 0.5%
    "crypto": float(os.environ.get("MP_MAX_SLIPPAGE_CRYPTO", "0.015")),  # 1.5%
}

# Only act on these signal labels. We deliberately ignore weak "BUY"/"SELL"
# on entry and only enter on STRONG conviction; we exit a position on any
# SELL-side flip.
ENTRY_LABELS = {"STRONG BUY"}
EXIT_LABELS = {"SELL", "STRONG SELL"}

# A proposal older than this (seconds) is considered stale and won't be sent —
# the market has moved since the signal was computed.
PROPOSAL_TTL = int(os.environ.get("MP_PROPOSAL_TTL", "1800"))  # 30 min

# Where the agent keeps its state (proposals, ledger, audit log, halt flag).
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


def keys_present() -> bool:
    return bool(ALPACA_KEY_ID and ALPACA_SECRET)


def allowed_symbols() -> set[str]:
    """Every symbol the agent is ever permitted to trade. Used by the guardrail
    chokepoint to re-validate a proposal's symbol independently of how the
    proposal was produced — a tampered queue cannot route an order off-universe.
    Stocks are plain tickers; crypto are Alpaca pairs (the dict KEYS)."""
    return set(STOCK_UNIVERSE) | set(CRYPTO_UNIVERSE.keys())
