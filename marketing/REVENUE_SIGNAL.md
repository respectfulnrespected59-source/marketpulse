# Revenue Signal — MarketPulse / MAPLE58

**Loop ID:** cybernetic-revenue-loop-01 · **Defined:** 2026-06-24

## The ONE signal we track
**Gumroad sales of `/l/yvsyyg`** (units + gross USD), with **views** as the leading indicator.

Why this one: it is the closest measurable point to cash, and it tells us whether the proof drops convert. Views rising + sales flat = funnel problem. Views flat = distribution problem. Both rising = scale it.

## Funnel being measured
daily proof drop (marketing/proof_drops/*.md) -> Gumroad page views -> sales

## How to read it (weekly, every market Friday)
1. Gumroad dashboard -> Products -> MarketPulse (`/l/yvsyyg`) -> note **views** and **sales** since last check.
2. Append a row to `reports/revenue_signal_log.csv`.
3. Compare to prior week. Decision rule:
   - **Sales up** -> repeat what drove traffic that week (double the winning channel).
   - **Views up, sales flat** -> fix the page (price, top copy, first cover).
   - **Views flat** -> distribution failed; change channel or cadence, not the product.

## Baseline
Captured in `reports/revenue_signal_log.csv` (2026-06-24 row). The numeric baseline must be read off the Gumroad dashboard — not guessed.

## Schema (`reports/revenue_signal_log.csv`)
`date` (YYYY-MM-DD) · `gumroad_views` (int) · `gumroad_sales` (int) · `gross_usd` (decimal) · `source_note` (text)
