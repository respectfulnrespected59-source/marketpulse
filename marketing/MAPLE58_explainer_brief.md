# MAPLE58 — YouTube Explainer Brief & Script
**Working title:** *MAPLE58: The Lil Money Robot We Built — GET · KEEP · GROW · SHARE*
**Series:** MarketPulse how-to (credit-free; B-roll = the tool's own screens)
**Tone:** warm, honest, anti-hype. Voltron energy, but the lion is *discipline*, not prediction.
**Codename lore:** MAPLE58 = the affectionate name for this MarketPulse build. **5** (Rob — Enneagram 5, the
investigator/builder) **+ 8** (his wife — Enneagram 8, the protector/force). Two spirits breathing life into
a "lil financial family member." MAPLE = family tree, rooted, grows season over season.

---

## The thesis (say it plain, up top)
"We didn't build a money-printer — those are lies. We built a **disciplined little robot** that does four jobs:
**finds** setups we can actually afford, **keeps** the pot alive by losing small, **grows** it by escalating only
the winners, and most importantly **shares** the whole method — free — with people nobody ever handed this to."

---

## VOLTRON STRUCTURE (the 4 limbs = the 4 acts)

### 🦁 GET — find the money (the GETTERS)
- **VO:** "First it finds plays you can actually afford — not the $4,600 lottery, the cheapest *usable* probe."
- **Superpowers to show:** the **Signal engine** (RSI/MACD/trend), the **TTM squeeze** (W/2W coiling), the
  **direction nudge** ("the data leans BULLISH — a pro would lean up; the choice is yours"), and the
  **Probe Scanner** sweeping volatile low-dollar stocks + crypto → "Qualifies at a $300 pot."
- **B-roll:** Options tab nudge banner; the 🔍 Scan results list (SNAP $9, NIO $14, F $16…).

### 🛡️ KEEP — don't blow it (the SHIELD)
- **VO:** "The unsexy part that actually matters. Most probes LOSE. The whole point is to be wrong *cheaply*."
- **Superpowers:** the **probe formula** (Δ≥0.25 readability floor, 20%-of-pot budget), the **'too rich — walk'**
  verdict, **defined-risk** structures, **no revenge sizing**, the per-contract **$ readout** ("$650, not 1.79").
- **B-roll:** the red "✋ Too rich for a $300 pot" probe panel; the dollar-priced chain; The Read step 6 (the catch).

### 🌱 GROW — compound it (the COME-UP)
- **VO:** "Probe → read → escalate. Win? Size up the next one. Lose? Flip or fold. And now you can SEE it grow."
- **Superpowers:** the **strangle / debit-spread helpers**, the **Probe → Read → Escalate** sizer, and the new
  **Pot Tracker** — $300 → $333, win-rate, the ladder.
- **B-roll:** the Pot Tracker ($333, the win/loss rows); the strategy cards; "needs ~$X pot" unlocking bigger names.

### 🤝 SHARE — the why (the HEART — most important)
- **VO:** "Here's the part most won't do: we're giving the method away. Free tool, honest math, the receipts —
  for the kids who never had somebody at the table to show 'em. That's the whole reason MAPLE58 exists."
- **Superpowers:** **Proof Mode** (honest backtests — every win AND loss), the **glossary** (explains every term),
  the **'not advice, you decide'** ethos baked into every screen.
- **B-roll:** Proof Mode cards; the glossary expanding; the footer "A Quantum Melanin Media tool."

---

## 🎬 ANIMATED GRAPHS (show what's ACTUALLY going on)
Build with the QMM animated-chart stack (matplotlib FuncAnimation per `make_animated_charts_pt2.py`, or
manim-video skill for the slick ones). Each animation = a concept made visible:

1. **Payoff diagrams (the hero set)** — animate P/L vs stock price at expiry, drawn left→right:
   - **Call debit spread** — rising line that caps (defined risk floor + capped top).
   - **Put debit spread** — mirror.
   - **Long strangle** — the "V": loses in the middle (it sat), wins on a big move EITHER way. Animate the two
     breakeven posts (+3.1% / −3.2%) lighting up. *This is the single clearest "what does this trade do."*
2. **The probe Δ/cost curve (the KEEP money-shot)** — x = strike OTM%, two lines: premium (drops fast) and
   delta (collapses). Slide a marker further OTM; shade the **"dead lottery zone" (Δ<0.25)** red and the
   **"usable probe" band** green. Lands *why $60 on a $2k stock is a +60% Hail Mary.*
3. **Expected-move cone** — price line + a widening ±1σ weekly cone; drop the probe strike on the cone edge so
   viewers see "this is roughly how far a normal week reaches."
4. **IV → premium** — same option, slide IV from 30%→120%; premium balloons. Lands *why 114% IV prices a small
   pot out.*
5. **The Pot Ladder (the GROW come-up)** — animated step line: $300 → small losses (tiny dips) → a winner (step
   up) → escalate → higher. Then a SECOND ghost line: the revenge-sizer who oversizes and craters to $0. Two
   paths, same start. *Discipline vs ruin, side by side.*
6. **TTM squeeze coil→fire** — Bollinger bands contracting INSIDE the Keltner channel (coiling), then popping
   back outside as it "fires." Lands what "squeeze ON" means at a glance.

## 🧭 APP WALKTHROUGH (the navigation tour — where things are)
A guided screen-tour so a first-timer knows how to drive it. Capture as screen-recording (or stitched
screen-caps with a moving cursor highlight + callout labels). Sequence:
1. **The tabs (the map):** Crypto · Stocks · **Options** · Watchlist · **🫙 Pot** · Proof — "here's the whole house."
2. **Stocks tab:** the cards — price, signal badge, the **TTM (W/2W)** chips, the **MA 5/14/21 + VWAP** row. "Read a card."
3. **Options tab — top to bottom (the core):** type a ticker + set your **pot $** → Load chain. Then scroll the
   stack and label each: **① the nudge** (which way it leans) → **② strategy cards** ($ + structure) →
   **③ Probe Plan** (qualifies / "too rich, walk") → **④ The Read** (the 6 steps) → **⑤ glossary** (what every
   term means) → **⑥ the chain** (in real per-contract dollars).
4. **🔍 Scan my pot:** click it → the qualifiers list → click a name → it loads that chain. "Find a play you can afford."
5. **🫙 Pot tab:** log a probe → close it win/loss → watch the pot move + the 20% budget update. "Track the come-up."
6. **◆ Proof tab:** run a backtest → "here's the receipts — every win AND loss."
- Keep callouts SHORT and on-screen-synced with VO ("THIS is the nudge", arrow points to it). Slow cursor, no rush.

## SCRIPT BEATS (≈ 5–7 min)
1. **HOOK (0:00–0:25):** "Meet MAPLE58 — the lil money robot me and my wife built. 5 and 8: a thinker and a
   protector. Four superpowers, and it will NOT lie to you about getting rich." (cold open on the dashboard)
2. **Why it's named that (0:25–0:55):** the family story — 5 + 8, breathing life into a financial family member.
3. **🧭 THE TOUR (0:55–2:10):** the navigation walkthrough — the tabs (the map) + where each feature lives, so
   nothing later is confusing. ("Before powers, here's the house.") *Uses the APP WALKTHROUGH sequence.*
4. **GET (2:10–3:10):** nudge + squeeze + scanner. Land "find what you can afford."
   *Animations: TTM squeeze coil→fire; expected-move cone.*
5. **KEEP (3:10–4:30):** probe formula + 'walk' verdict + dollar readout. Land "be wrong cheaply; most probes lose."
   *Animations: the probe Δ/cost curve (dead-lottery zone vs usable band); IV→premium balloon.*
6. **GROW (4:30–5:50):** Probe→Read→Escalate + Pot Tracker $300→$333. Land "watch it compound, with discipline."
   *Animations: payoff diagrams (spread + strangle V); the Pot Ladder — disciplined vs revenge-sizer ghost line.*
7. **SHARE (5:50–6:50):** Proof Mode + glossary + the mission. Land "the method is the gift."
8. **CLOSE (6:50–end):** "MAPLE58 stays free. Slow and alive beats fast and liquidated. Tap in." (Gumroad/links)

> Runtime grows to ~7 min with the tour + animations — fine for a how-to. Keep VO tight; let the animations breathe.

## On-screen / production notes
- **VO:** Kokoro `am_michael` (per series). Music: Lion of Mali / SCFL bed, low.
- **B-roll:** fresh screen-caps of nudge, scanner, probe panel ('too rich'), Pot Tracker, Proof Mode, glossary.
- **Captions:** PIL-baked (per build_explainer_N pipeline). Ken-Burns on stills.
- **Disclaimer card:** "Educational. Not financial advice. Most probes lose — that's the design."
- **Thumbnail:** "MAPLE58 🍁" + four lil lion/limb icons (GET·KEEP·GROW·SHARE) + "$300 → ?" honest, not flexy.

## Pipeline to produce (next step)
`tools/synth_vo_maple58.py` (Kokoro VO from the beats) → `tools/build_explainer_maple58.py` (caps + Ken-Burns
+ music + the fresh B-roll) → `tools/build_thumb_maple58.py` → upload via quantus-autoposter. Honest-hook + the
proof-of-work comparison gate per the QMM standards.
