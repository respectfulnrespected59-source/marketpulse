# MarketPulse — Live Crypto & Stock Signal Dashboard

A clean, fast market dashboard that pulls **live crypto and stock prices**, computes
real technical signals (**RSI + MACD + trend**), and flags each asset as
**STRONG BUY / BUY / NEUTRAL / SELL / STRONG SELL** — with a watchlist and price alerts.

No account. No API key. No monthly fee. Runs on your own machine.

![signals](static/preview.png)

## Quick start

You only need **Python 3** (already on most computers).

**Windows:** double-click **`run.bat`**
**Mac / Linux:** run **`bash run.sh`**

Then open **http://127.0.0.1:8000** (the launcher opens it for you).

To stop it, close the terminal window (or press `Ctrl+C`).

## What it does

- **Live prices** for top crypto + major stocks, auto-refreshing every 60s.
- **Real signals** — RSI(14), MACD(12/26/9), and price-vs-trend combined into one
  score, with the reasons shown on every card (no black box).
- **Market breadth** — see how many assets are flashing Buy vs Sell at a glance.
- **Watchlist** — star anything to track it on its own tab.
- **Price alerts** — set "rises above / drops below" targets and get a desktop
  notification when they hit.
- **Add any symbol** — type a stock ticker (`NVDA`) or a CoinGecko coin id (`solana`).

## Where the data comes from

- **Crypto:** [CoinGecko](https://www.coingecko.com) public API (no key).
- **Stocks:** Yahoo Finance chart API (no key).

The included Python server fetches this data for you so the browser never hits a
CORS wall, and caches each response for 60 seconds to stay within free limits.

## Important

This is an **educational tool, not financial advice.** Technical signals describe
what price *has done*, not what it *will do*. Markets are risky; trade your own
research and never risk money you can't afford to lose.

---

*A Quantum Melanin Media tool.*
