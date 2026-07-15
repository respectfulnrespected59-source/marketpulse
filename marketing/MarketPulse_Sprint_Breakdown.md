::: cover

**QUANTUM MELANIN MEDIA**
*presents*

# MarketPulse
## From Screener to Trading App

*The Build Log — Sprint by Sprint*

A Quantum Melanin Media Production
*v1.0 — 2026*

*"We didn't guess our way here. Every sprint: build it, verify it, ship it, prove it."*

:::

# The Vision

> *Center it on the two things that actually build wealth for regular people:
> dollar-cost averaging and options.*

## The epiphany

The goal: turn **MarketPulse** — already an honest signal + DCA + options dashboard — into a real **trading site and app, the way Robinhood started**, centered on **dollar-cost averaging (DCA)** and **options**.

## The honest reality (and the smart route)

Robinhood is a **licensed broker-dealer**. You can't let people trade real money through a site by just building a UI. There are three routes:

| Route | What it means | Verdict |
|-------|---------------|---------|
| Become a broker-dealer | Full FINRA license, net-capital minimums, compliance staff | Years + six figures — not now |
| **Build on a Broker-as-a-Service API** | **Alpaca** is the broker of record (KYC, custody, clearing, SIPC); we're the tech + brand | **The move** — this is how Robinhood started |
| Connect-your-own-brokerage | Users link an account they already have | Too limited |

**The plan:** build the full Robinhood-shaped app **now** (no license needed while it's paper + planning + education), and wire **real money via the Alpaca Broker API** as a later phase.

---

## The build cycle

Every sprint runs the same repeatable loop. This is the cycle the whole project turns on:

<table class="cream">
<tr><th>Step</th><th>What happens</th></tr>
<tr><td>1 · RESEARCH</td><td>Search proven open-source before writing anything new</td></tr>
<tr><td>2 · BUILD</td><td>Ship the smallest increment that delivers real value</td></tr>
<tr><td>3 · VERIFY</td><td>Run tests + drive the real UI in a browser; 0 errors</td></tr>
<tr><td>4 · SHIP</td><td>Branch → commit → PR → merge → auto-deploy to Render</td></tr>
<tr><td>5 · PROVE</td><td>Verify on the live HTTPS URL — receipts, not claims</td></tr>
<tr><td>6 · REPEAT</td><td>Lock the lesson, pick the next increment</td></tr>
</table>

{: .center .muted } Live app · marketpulse-22bi.onrender.com · auto-deploys on every merge to main

---

# Sprint 1 — The Installable App

::: hero
### Sprint 1 · Progressive Web App
*Make MarketPulse a real app you install on your phone.*

**Goal:** Home-screen icon, full-screen, offline-capable — no app store.
**Licensing:** None required.
**Status:** LIVE
:::

## What we built

A full **Progressive Web App (PWA)**: a web manifest, a custom app icon (gold diamond + green pulse), Apple/Android install support, and a service worker so it opens instantly and works offline.

## How it works

- **Service worker = network-first, cache fallback.** Always serves the freshest code when online (stale code could mean stale money logic), but still opens offline like a native app.
- **Never caches live prices.** Market data always comes fresh — no pretending old numbers are current.
- **iOS handled.** iPhone has no auto-install prompt, so it shows a "tap Share → Add to Home Screen" hint.

## The receipt

| Check | Result |
|-------|--------|
| Service worker registers over HTTPS | Pass |
| Installable (manifest + icons valid) | Pass |
| Home-screen shortcuts (DCA / Options / Live) | Pass |
| Console errors | 0 |

---

# Sprint 1.5 — Candlestick Charts

::: hero
### Charts · Candlesticks + Bright Lines
*"We need nice, easily readable candle charts."*

**Goal:** Replace dim, hard-to-read lines with real candlesticks.
**Status:** LIVE
:::

## What we built

Real **candlestick charts** on the Proof view — bright green up-candles, red down-candles with wicks, and hollow rings marking every BUY / SELL signal. Every other chart got brightened and thickened.

## How it works

The Yahoo price feed already carried full **open / high / low / close** data — the app was throwing away everything but the close. We now pass the full OHLC through, aligned one-to-one with the signal dates, and render it with a reusable candlestick engine.

## The receipt

| Check | Result |
|-------|--------|
| Real candlesticks on stock Proof charts | 502 candles |
| Bright line fallback for crypto | Pass |
| Every dim gray line brightened | Pass |
| Tests passing | 101 |

---

# Sprint 1.6 — Crypto Fix + Default to Stocks

::: hero
### Reliability · Coinbase Fallback
*Fix the crypto tab breaking on the live server.*

**Goal:** Crypto data that works on the cloud, and a first screen that always loads.
**Status:** LIVE
:::

## What we built

CoinGecko's free API rate-limits cloud data-center IPs (a `429` error), so the crypto tab broke live. We added a **keyless Coinbase fallback** (works on data-center IPs) and made the app **open on the Stocks tab** — the DCA / options core.

## How it works

- Try CoinGecko first; on failure, fall back to Coinbase's public candles API — real prices, signals, sparklines.
- Coins Coinbase doesn't list drop out gracefully instead of crashing the whole tab.
- Optional CoinGecko demo key supported for later (`MP_CG_KEY`).

## The receipt

| Check | Result |
|-------|--------|
| Crypto grid live on Render | 10 coins, real prices |
| Crypto Proof / DCA history | 350 daily candles |
| App opens on Stocks by default | Pass |

---

# Sprint 2a — The Order Ticket

::: hero
### Sprint 2a · Quick-Fill Ticket
*Make it feel like Robinhood.*

**Goal:** A fast, precise, tap-to-size amount control.
**Status:** LIVE
:::

## What we built

A **Robinhood-style order ticket** on the Live Tracker: a big tap-to-edit dollar amount, one-tap chips ($50 / $100 / $250 / $500 / $1k), plus/minus steppers, and a **live conversion** as you type.

## How it works

- Money math runs through **big.js** — zero floating-point drift (verified `0.1 + 0.2 = 0.3`).
- Live readout: `≈ 1.41 shares · NVDA @ $212.50` for stocks, fractional units for crypto.
- Self-hosted single file — stays offline-capable, no external dependencies.

## The receipt

| Check | Result |
|-------|--------|
| Quick-fill amount + chips + steppers | Pass |
| Live shares / units conversion | Pass |
| Precise money math (no float drift) | Pass |
| Console errors | 0 |

---

# Sprint 2.5 — Live Trading Chart

::: hero
### Live Chart · Real Intraday Candles
*"We need a live trading chart, bruh."*

**Goal:** A real, live-updating candlestick chart of intraday price action.
**Status:** LIVE
:::

## What we built

A proper **live trading chart** on the Live tab: real intraday candlesticks that refresh every 20 seconds, with a live price header, a current-price line, and a **gold entry line** that drops in the moment you pin a play.

## How it works

- New backend endpoint pulls intraday candles — Yahoo 15-minute bars for stocks, Coinbase hourly for crypto (both keyless, both work on Render).
- Reuses the same candlestick engine from the Proof charts, so the whole app looks like one system.

## The receipt

| Check | Result |
|-------|--------|
| Stock intraday candles | 131 (5 days · 15m) |
| Crypto intraday candles | 350 (hourly) |
| Gold entry line on pin | Pass |
| Auto-refresh every 20s | Pass |

---

# Sprint 2b — Quick-Fill Everywhere + Timeframe Toggle

::: hero
### Sprint 2b · Reusable Widget + TF Toggle
*Spread the ticket, add chart zoom.*

**Goal:** Quick-fill on Pot + DCA, and a 1D / 5D chart toggle.
**Status:** LIVE
:::

## What we built

The quick-fill widget became **reusable** and now lives on the **Pot probe** and **DCA** inputs too — each with a custom readout. Plus a **timeframe toggle** on the live chart.

## How it works

- **Pot probe:** readout shows `$50 = 16.7% of your $300 pot`, turns red if you exceed the 20% probe budget.
- **DCA:** readout shows the annualized total — `$200 monthly = $2,400/yr` — recomputing when you change cadence.
- **Timeframe toggle:** 1D / 5D for stocks (5m ⇄ 15m candles), 1D / 1W for crypto.

## The receipt

| Check | Result |
|-------|--------|
| Pot % of pot + budget warning | Pass |
| DCA annualized readout | Pass |
| Timeframe toggle (candles swap) | 79 ⇄ 131 |
| Tests passing | 101 |

---

# Where It Stands Today

> *A real, polished, installable trading app — honest by design,
> DCA and options at the center. No license needed for any of it.*

## The full stack — everything live

| Layer | What it does |
|-------|--------------|
| Installable PWA | Home-screen app, offline-capable |
| Candlestick charts | Proof + live intraday, timeframe toggle |
| Quick-fill tickets | Live · Pot · DCA — precise money math |
| DCA Wizard | Plain vs lump vs signal-tilt, money-flow charts |
| Options engine | Chains, IV, Greeks, spreads, probe sizer |
| Live tracker | Real prices, honest simulated fills, P&L |
| Safety | 101 tests, honest-by-design framing throughout |

---

# The Road Ahead

::: row
::: hero
### Sprint 3 — The Cockpit
*Make it persistent.*

**Server-side portfolio + DCA plans**
**Unified Portfolio home**
**DCA automation scheduler** (propose → you approve)

*No license required.*
:::
::: villain
### Sprint 4 — Real Money
*Turn on the rails.*

**Apply for the Alpaca Broker API**
**Account-open + funding** (Alpaca = broker of record)
**Graduate the paper agent** to real orders

*Alpaca handles KYC + custody.*
:::
:::

{: .center .gold } The pattern never changes: research · build · verify · ship · prove · repeat.

::: end-credits
**— MARKETPULSE · BUILD LOG v1.0 —**

*Built, verified, and shipped by Quantum Melanin Media*

*Educational tool — not financial advice. Most probes lose; survival is the edge.*

*"Voice and receipts. Every sprint, we brought both."*

:::
