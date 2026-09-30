# MarketPulse Classes — curriculum (draft for owner review)

Four classes, five lessons each, plus a free setup class. Every lesson is taught **on the chart**: the
chart loads, rewinds to a real moment, and draws while Tess teaches and Quantus
asks what the viewer is thinking. Each lesson ends with a **practice Call** on
the replay (Learning Mode), so the student does the thing, not just watches it.

Sold as the **Classes pass ($19/mo)**; also included in **Pro+**.

Ground rules for every script:
- Teach mechanics that are always true. No "this makes money" claims — two
  pre-registered engine studies (09-28/29) found no timing edge, so we never
  imply one.
- Numbers on screen come from the lesson's own chart data, never typed by hand.
- Costs quoted match the app's cost model (backtest.py): stocks 0 bps commission
  + 5 bps slippage per side; crypto 25 + 20 bps per side.
- Close: "Educational, not financial advice."
- **Length: 8-10 minutes per lesson** (owner, 2026-09-30: "we can not SELL classes that short" —
  the first build shipped ten lessons of about 90 seconds). That is 1,350-1,450 words and about
  60 steps. The build stops if any lesson of a class with paid lessons runs under 8:00
  (`lesson_compiler.MIN_PAID_CLASS_LESSON_S`), and `tools/audit_deployed.py` goes red if the live
  catalogue lists one. Fill the time with substance, not padding: several real cases on one
  multi-year tape (a top, a bottom, every window counted), the arithmetic worked slowly, the
  counter-case, the limits, how to do it in the app, a recap and homework.
- Quantus asks yes/no, echo or tag questions, never what/how/why: a wh-question falls flat in TTS.

Lesson 1 of each class matches its free 30-second short, expanded.

**Every lesson teaches the app too** (owner, 2026-09-29: "make sure these lessons include how to use
all the app's tools and settings to get the most accurate and comfortable outcome"). Each lesson
spotlights the real controls it uses — a `spot` step rings the actual button while Tess explains it —
so a student finishes a class knowing both the idea and exactly how to do it in MarketPulse.

---

## Set up MarketPulse — "Get comfortable first"  (free)
The class every other class leans on. Short lessons, each ending with the student doing it.
1. **Find anything.** Search / Ctrl+K, stocks vs crypto, the Market Map.
2. **Timeframes that fit how you trade.** 1m to weekly; swing on daily, never judge a daily
   trend from a 1-minute chart; pre/post-market on or off for stocks.
3. **Indicators without clutter.** EMAs and the TTM squeeze on or off, and their settings; volume;
   why fewer lines read more accurately.
4. **Drawing.** Mark (M), trend line (L), snap to the wick vs Alt for free placement, undo, clear;
   Fit, zoom, and full screen for a comfortable view on a phone or a laptop.
5. **Practice without risk.** Replay the dial, speed, step a candle; make a Call and read your
   record on the Coach tab; paper-trade your rules on real prices. (Price alerts left out: they
   are a Pro feature, and this class is free.)

*Built 2026-09-29: five free lessons on the SPY daily tape; every spotlight is checked on
screen at phone and laptop size (walk: ring visible, ▶ visible).*

---

## DCA — "Stop timing the market"
1. **Same dollars, every period.** Rewind a year, buy on a schedule, draw the
   average-cost line. Why fixed dollars average *below* the average price
   (more coins when it's cheap). *(Pilot short: done.)*
2. **Lump sum vs DCA — the honest version.** Lump sum has historically won about
   two times in three, because markets rise more often than they fall. DCA buys
   you less regret and no timing decision. Shown with the DCA Wizard's backtest.
3. **Living below your line.** Price under your average cost is normal on the
   way; what "underwater" means, and why the plan doesn't change because of it.
4. **Cadence and costs.** Weekly vs monthly; every buy pays fees and slippage,
   so tiny frequent crypto buys leak more. The math on the chart.
5. **Signal-tilt DCA.** MarketPulse's tilt makes each buy bigger when the engine's
   score is positive and smaller when it is negative — still always buying. The
   score is mostly trend, so on the lesson tapes it trimmed buys near the lows and
   boosted them at higher prices, and finished behind plain DCA in every one-year
   window (0 of 49 on BTC, 0 of 48 on SPY). The lesson says so.
   *Practice:* set a plan in the Wizard and replay a year against it.

*Rebuilt 2026-09-30 at full length on five-year tapes (BTC and SPY daily): lessons run
9-10 minutes each.*

## Stocks — "Read the chart"
1. **Candles.** Open, high, low, close; body vs wick; the crosshair reads them.
2. **Trend and structure.** Higher highs and higher lows; draw the trend line
   under the lows; what a break of that line does and doesn't mean.
3. **Support and resistance.** Horizontal levels where price reacted before, and
   why old resistance often becomes support.
4. **Moving averages.** The EMAs on the chart as a trend filter; crosses; lag —
   they confirm late by design.
5. **Volume and the squeeze.** Compression before expansion (TTM squeeze); the
   squeeze tells you *when* a move may come, not *which way*.
   *Practice:* Calls on replay — commit a direction before the next bars reveal.

## Crypto — "The market that never closes"
1. **24/7 charts.** No opening bell; weekends and overnight moves; what a
   "session" means on a crypto replay.
2. **Volatility and size.** Bigger % swings mean smaller positions for the same
   risk; sizing from the distance to your stop.
3. **Costs eat churn.** 25 bps + 20 bps per side in our model: why a scalp has to
   clear ~0.9% round trip before it's worth anything. (Our own 5-minute study
   failed exactly here.)
4. **Timeframes.** The 1h trend inside the daily trend; draw on the higher
   timeframe first.
5. **Calibration.** Confidence vs accuracy: the Call record shows which reads
   you're actually good at.
   *Practice:* 10 Calls on a BTC replay, scored after costs.

## Options — "Know your line before you trade"
1. **Breakeven.** Long put = strike minus premium; long call = strike plus
   premium. Put it on the chart, measure the gap. *(Pilot short: done.)*
2. **Calls and puts.** The right, not the obligation; strike, expiry, premium;
   what you can lose (the premium) when you buy.
3. **Debit spreads.** Buy one strike, sell another: capped cost, capped payoff.
   Max profit, max loss and breakeven drawn on the chart — the spreads the app
   suggests.
4. **Time.** Expiry and time decay; why "1d left" on the strip matters; the
   same price can be a loss today and a win at expiry, or the reverse.
5. **Reading the live estimate.** The strip's delta-gamma estimate, why it's
   capped at max profit/loss, and why it's an estimate, not a quote.
   *Practice:* open a paper spread, set the breakeven, replay the session.
