# MarketPulse — The Full Explainer
### Quantus & Tess · long-form YouTube script

**Runtime target:** 12–16 min · **Hosts:** Quantus (am_liam) · Tess (af_heart)
**B-roll:** live app capture — screener, chart, indicator controls, paper tab, options chain, Proof Mode
**Tone:** two people who actually use the thing, explaining it to a friend. No hype. The honesty *is* the pitch.

---

## COLD OPEN — 0:00

**QUANTUS:** Most trading tools show you their wins.

**TESS:** This one ships a backtest that shows it losing.

**QUANTUS:** On purpose. It's in the product. You can run it right now and watch our own signal get beaten by just holding the stock.

**TESS:** So why would anybody build that?

**QUANTUS:** Because the truth is the only thing here that's actually worth money.

*[TITLE CARD: MarketPulse — the honest options tool]*

---

## ACT 1 — WHAT IT IS · 1:00

**TESS:** Plain version. What is MarketPulse?

**QUANTUS:** A trading dashboard you run on your own machine. Crypto and stocks side by side, real signals, a real chart, an options chain with the actual Greeks — and now it'll paper-trade your own rules for you.

**TESS:** Run on your own machine — meaning what, exactly?

**QUANTUS:** Meaning there's no account. No login, no API key, no subscription, and none of your data leaves your computer. You double-click a file and it opens in your browser.

**TESS:** What do you need installed?

**QUANTUS:** Python 3. That's it. Windows, double-click `run.bat`. Mac or Linux, `bash run.sh`. If you don't have Python it's a free download from python.org — just tick "Add Python to PATH."

**TESS:** And there's a free version.

**QUANTUS:** There's a real free version. Not a demo with everything greyed out — the Pro files literally aren't in the free download. You can't flip a switch and unlock them, because they're not there.

---

## ACT 2 — THE SCREENER · 2:30
*[B-roll: the grid, cards populating]*

**TESS:** Start at the top. What am I looking at?

**QUANTUS:** Every symbol you're watching, with one composite signal on it. RSI, MACD and trend, rolled into a single read — STRONG BUY down to STRONG SELL.

**TESS:** One number instead of four charts.

**QUANTUS:** Right. And under it: a TTM squeeze read, the 5/14/21 moving-average stack, and session VWAP. That's the stuff a disciplined trader checks before every entry, in one place.

**TESS:** How many symbols can I watch?

**QUANTUS:** Anything either venue lists. Every market Coinbase actually trades — that's 406 of them — plus any ticker Yahoo carries. Type a name or a ticker, it finds it.

**TESS:** Including the tiny stuff? The sub-penny coins?

**QUANTUS:** Including those. They price correctly instead of rounding to zero, which is a thing that breaks in a lot of tools.

---

## ACT 3 — THE CHART · 4:30
*[B-roll: timeframe buttons, indicator controls, EMA period edit]*

**TESS:** Chart's the part people judge you on.

**QUANTUS:** Then judge it. Real candles at 1m, 5m, 10m, 15m, 30m, 1h, daily and weekly.

**TESS:** And I can actually change things? Because most of these tools, what you see is what you get.

**QUANTUS:** You set the EMA periods yourself. 9 and 20, or 50 and 200, whatever your system uses. Squeeze on or off. Volume on or off — and when volume's off, the candles take the space back.

**TESS:** What about drawing on it?

**QUANTUS:** Click to mark an entry and it snaps to the candle's actual open, high, low or close — not wherever your mouse landed. Drag to draw a trend line. Scroll to zoom, drag to pan.

**TESS:** And the indicators match what I'm looking at?

**QUANTUS:** *[beat]* They do now. They didn't used to. The EMAs and the squeeze were being calculated on daily bars no matter which timeframe you had open — so on a one-minute chart you were staring at daily lines that never moved.

**TESS:** That sounds like it would look completely random.

**QUANTUS:** It *was* random. It was unrelated to the chart underneath it. It's fixed — every overlay is now measured on the exact candles you're looking at, and the squeeze chip tells you which timeframe it measured.

---

## ACT 4 — PAPER TRADING · 7:00
*[B-roll: paper tab, rules editor, validate, positions opening]*

**TESS:** Okay. This is the new part.

**QUANTUS:** This is the part that matters. You write your own rules — not ours — and the app trades them on paper.

**TESS:** Define "your own rules."

**QUANTUS:** Entry conditions and exit conditions, over the same readings that are on the chart. "Enter when the squeeze fires, the MA stack is bullish, and RSI is under 70." "Exit on a SELL signal, or an eight percent stop, or a fifteen percent target."

**TESS:** And it just… runs?

**QUANTUS:** You press start. It checks real prices on a timer and opens and closes paper positions by itself. No broker, no API key. **No real order is ever placed.**

**TESS:** So the prices are real but the money isn't.

**QUANTUS:** Exactly. And here's the part I want people to hear — the fills get charged real commission and slippage. Same costs the backtest uses.

**TESS:** Why does that matter? It's fake money either way.

**QUANTUS:** Because a paper record that fills at the perfect price is a lie you tell yourself. Then you go live with real money, get worse fills, and wonder why it stopped working. Flattering numbers are how people talk themselves into risking money on a system that never worked.

**TESS:** *[beat]* So it's deliberately harder than it needs to be.

**QUANTUS:** It's deliberately *honest*. At the end of a week you can answer the only question that counts — did my rules do what I thought they'd do? — with data instead of hope.

**TESS:** And most people find out…

**QUANTUS:** That the answer's no. That's the week doing its job. Finding that out on paper costs you a week. Finding it out live costs you the pot.

---

## ACT 5 — WHAT'S PAID · 10:00
*[B-roll: options chain, Greeks, probe plan, Proof Mode]*

**TESS:** So what's behind the $39?

**QUANTUS:** The options engine. A real chain with implied volatility and all five Greeks, priced in what one contract actually costs — not per-share premium you have to multiply in your head.

**TESS:** That's a small thing that isn't small.

**QUANTUS:** It's the difference between "one seventy-nine" and "six hundred and fifty dollars." Then there's a spread builder and a strangle builder that pick the legs by delta.

**TESS:** And the probe thing.

**QUANTUS:** The probe sizer. It finds the cheapest position that can still *tell you something*. Below about a quarter delta you're buying a lottery ticket — it won't react to a normal move, so you learn nothing. The tool says so and refuses to pretend.

**TESS:** Plus the scanner.

**QUANTUS:** Scans liquid names against the pot you actually have and tells you which ones fit. And Proof Mode — the backtest that shows the losses, after fees and slippage, with a walk-forward test on top.

**TESS:** And the agent.

**QUANTUS:** The agent runs your rules on your own broker account, with your own key. It proposes; you approve. It ships locked to paper and it cannot place an order on its own — that's not a missing feature, that's the feature.

---

## ACT 6 — WHY THIS ONE · 12:30

**TESS:** Give me the honest version. Why this and not the fifty other ones?

**QUANTUS:** Three things, and none of them are features.

**QUANTUS:** One — it costs you once. The tools it competes with are twenty to a hundred dollars a *month*.

**QUANTUS:** Two — it runs on your machine. No account, no data collection, no subscription that dies when they change their pricing.

**QUANTUS:** Three — and this is the real one — it tells you when it's wrong. Proof Mode will show you our own signal losing to buy-and-hold. The paper tracker charges you costs that make your numbers worse. Every part of this is built to stop you fooling yourself.

**TESS:** Which is not how anybody sells a trading tool.

**QUANTUS:** Because it's not what people want to hear. It's just what's true. And if you're the kind of person who'd rather know — this was built for you.

---

## CLOSE · 14:30

**TESS:** Where do people start?

**QUANTUS:** Free edition. Screener, full chart, paper trading, all of it real. Write your rules, run them a week, read your own record.

**TESS:** And if the thinking's useful?

**QUANTUS:** Then the rest is thirty-nine dollars, once.

**TESS:** Last word.

**QUANTUS:** Most people don't lose because they were wrong. They lose because they were too big when they were wrong.

**TESS:** You can't compound from zero.

**QUANTUS:** This won't pick winners for you. It's built to keep you sized like somebody who intends to still be trading next year.

*[CARD: Free — gumroad.com/l/mzwrgk · Pro $39 — gumroad.com/l/yvsyyg]*
*[CARD: Educational tool. Not financial advice. Most probes lose — that's the design.]*
*[CARD: A Quantum Melanin Media tool]*

---

## PRODUCTION NOTES

**Claims that are safe to make — every one verified this build:**
- 406 live Coinbase markets; any Yahoo ticker
- 8 timeframes: 1m / 5m / 10m / 15m / 30m / 1h / 1D / 1W
- EMA periods user-set (2–400, up to 4 lines); squeeze and volume toggle
- 22 rule fields available to the strategy engine
- Paper fills charged 5bps stock / 25bps + 20bps crypto
- 362 automated tests passing
- Free edition physically excludes options.py, backtest.py, dca.py, agent/

**Never say:** any figure for what a user will earn; that the tool predicts;
that paper results imply live results. Scope every claim to **discipline,
sizing and survival** — never returns. See `feedback_no_guaranteed_returns`.

**Assets:** reuse the candlestick animation engine (`tools/animate_maple58.py`)
for the Act 4 paper-trading beat; capture fresh close-ups of the indicator
control bar and the paper tab — both are new since the last explainer.
