# MarketPulse — "MAPLE58"

An **honest options-research dashboard**. It pulls live market data, reads the
technicals, and walks you through one question: *what's a play I can actually
afford, and how do I lose small when I'm wrong?*

Runs on **your own machine**. No account. No API key. No monthly fee. No data
leaves your computer.

> **MAPLE58 = MArket PuLsE.** Brand rule: it will **not** lie to you about
> getting rich. Most options trades lose — *survival* is the real skill.

---

## Quick start

You need **Python 3** installed.

- **Windows:** double-click **`run.bat`**
- **Mac / Linux:** run **`bash run.sh`**

It opens **http://127.0.0.1:8000** in your browser automatically.
To stop it, close the terminal window (or press `Ctrl+C`).

### Windows: don't have Python?
If `run.bat` flashes open and closes, you don't have Python yet. Install it once:

1. Go to **https://www.python.org/downloads/** and install Python 3.
2. **Important:** on the first installer screen, check **“Add Python to PATH.”**
3. Re-run `run.bat`.

That's the only setup. Everything else is built in — no `pip install`, no extra
downloads.

---

## What you get — the four jobs: GET · KEEP · GROW · SHARE

**GET — find a play you can afford.**
A plain-English *direction nudge* (a lean, never an order — the choice is yours),
the TTM squeeze, an expected-move read, and a scanner for volatile, low-dollar
names you can actually trade.

**KEEP — be wrong cheaply.**
The *probe*: the smallest first bet that still tells you something. A delta-based
readability floor so you're not buying dead lottery tickets, prices shown in
**real per-contract dollars** (premium × 100), and a 20%-of-pot rule that says
*walk* when a play is too rich.

**GROW — escalate only your winners.**
Probe → Read → Escalate, tracked in the **Pot Tracker** (e.g. $300 → $333).
Never revenge-size.

**SHARE — prove it, don't sell hype.**
**Proof Mode** backtests the exact signal over years and shows the **losses** too,
not just the wins. Plus a built-in glossary so every number on screen has a plain
definition. The tool stays honest.

### The Options tab reads top-to-bottom like a funnel
**Nudge** (which way it leans) → **Strategy card** (the structure + $/contract) →
**Probe plan** (smallest readable bet) → **The Read** (6-step: trend · coil ·
signal · volatility · the play · the catch) → **Glossary** → full **chain** with
IV + Greeks in per-contract dollars.

---

## Where the data comes from
- **Options chains, IV & Greeks:** CBOE free delayed quotes (no key).
- **Stocks:** Yahoo Finance chart API (no key).
- **Crypto:** CoinGecko public API (no key).

The included Python server fetches this for you (so the browser never hits a CORS
wall) and caches responses to stay within free limits. Data is delayed (~15 min)
— this is a research tool, not a live trading terminal.

---

## Folders
- **`/` + `static/`** — the dashboard (this is what `run.bat` / `run.sh` launches).
- **`agent/`** *(optional, advanced)* — a **paper-first, propose-and-approve**
  trading layer for Alpaca's free paper account. It never auto-fires real money;
  a human approves every order, behind independent safety guardrails (spend caps,
  kill switch, slippage gate, circuit breaker). See `agent/README.md`.
- **`tests/`** — the automated test suite for the math and the safety gates.
  Run `python -m pytest` if you have pytest. (You don't need this to use the app.)

---

## Important
This is an **educational tool, not financial advice.** Technical signals describe
what price *has done*, not what it *will do*. **Most options trades lose — that's
the math, and this tool is built to keep you alive long enough to learn.** Trade
your own research; never risk money you can't afford to lose. Slow and alive beats
fast and liquidated.

---

*A Quantum Melanin Media tool.*
