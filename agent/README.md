# MarketPulse Agent — paper-first, propose-and-approve

A trading **agent** layer on top of the MarketPulse signal engine. It watches
the same RSI/MACD/trend signals the dashboard shows you, turns STRONG entries
and exits into **proposals**, and waits for you to approve each one before a
single order is sent.

> **Defaults are safe on purpose.** Paper money. Propose-only. Tiny caps.
> The agent *cannot* send an order on its own — you approve every trade.

## Why Alpaca (and not Robinhood / Webull)

Robinhood and Webull have **no official trading API**. The unofficial libraries
are against their terms and routinely get accounts locked. Alpaca is an official,
commission-free API for **US stocks + crypto** with a real **paper-trading
sandbox** — fake money, real market data, identical code path. We prove the
agent there first.

## Setup

1. Make a free account at <https://alpaca.markets> → **Paper Trading** → generate
   an API key + secret.
2. Copy the env template and fill in your **paper** keys:
   ```bash
   cp agent/.env.example agent/.env.local   # this file is gitignored
   # edit agent/.env.local, then:
   source agent/.env.local                  # Git Bash
   ```
   (PowerShell: set each `MP_*` with `$env:MP_ALPACA_KEY_ID = "..."`.)
3. From the `agent/` directory:
   ```bash
   cd agent
   python cli.py status     # confirms paper account + caps, no trade
   ```

## Daily loop

```bash
python cli.py scan            # compute signals -> new proposals
python cli.py list            # review what it wants to do, and why
python cli.py approve p-...   # authorize ONE proposal (passes guardrails, sends)
python cli.py reject  p-...   # discard one
python cli.py status          # account, positions, 24h spend, halt state
python cli.py audit 30        # tail the decision log
```

Kill switch (blocks every send until released):
```bash
python cli.py panic "stepping away"
python cli.py resume
```

## The safety layers (from the llm-trading-agent-security skill)

Every approved order passes one chokepoint — `guardrails.authorize_send` — which
runs independent checks before the broker is ever called:

| Control | What it does | Where |
|---|---|---|
| Kill switch | `HALT` file or circuit flag blocks all sends | `store.is_halted` |
| Allow-list | refuses any symbol not in the configured universe, re-checked at send | `check_symbol_allowed`, `config.allowed_symbols` |
| Staleness | refuses proposals older than `PROPOSAL_TTL` | `check_fresh` |
| Live-price slippage gate | pulls a fresh price at approve time and refuses if the market moved against the side beyond `MAX_SLIPPAGE_PCT` (our `min_amount_out`); **fails closed** if no live price | `broker.latest_price`, `check_slippage` |
| Per-trade cap | refuses notional > `MAX_SINGLE_TX_USD` | `check_spend` |
| Daily cap | refuses if 24h spend would exceed `MAX_DAILY_SPEND_USD` | `check_spend` |
| Circuit breaker | halts on daily drawdown or consecutive losses (exits feed `record_trade_result` on approve) | `update_equity_and_check`, `record_trade_result` |
| Audit log | every decision logged, not just sends | `store.audit` |
| Key isolation | keys from env only, never code or logs | `config`, `broker` |

These are enforced **independently of the signal** — a bad signal still can't
spend past the caps.

## Important — this is not a money printer

The signal engine describes what price *has done*. Most of the edge that keeps
an account alive is risk management, not prediction. Run it on **paper for
weeks**, read the audit log, and only consider real money with a tiny allocation
after the paper results actually hold up. Slow and alive beats fast and
liquidated.

## File map

```
agent/
  config.py      caps, venue, universe, mode (env-driven)
  store.py       JSON persistence: proposals / ledger / circuit / audit / HALT
  guardrails.py  independent safety controls + the authorize_send chokepoint
  broker.py      Alpaca paper REST client (pure stdlib)
  proposer.py    signals -> proposals (reuses the dashboard engine)
  cli.py         your control surface (scan/list/approve/reject/panic/...)
  .env.example   environment template (copy, never commit real keys)
  data/          runtime state (gitignored)
```
