# Verification record — unlocked dial + Learning Mode phase 1

**Date:** 2026-07-31. **Scope:** the always-unlocked replay dial, the
historical-price safety state, and Learning Mode phase 1 (Call, stats,
Coach panel, drills).

A record of what was actually exercised and what it returned, kept because
"the tests pass" is not evidence on its own. Every defect in §5 was invisible
to the automated suite.

---

## 1. Automated suites

| Suite | Count | Result |
|---|---|---|
| Python (`pytest tests/`) | 362 | pass |
| Call scoring + no-lookahead (node harness) | 10 | pass |
| Stats / calibration / flags (node harness) | 20 | pass |
| `node --check` on every changed JS file | 4 files | pass |

The node harnesses load the **real** `static/learn.js` into a `vm` context with
`localStorage` and `document` stubbed, so they exercise shipped code rather than
a copy. There is no JS test runner in this repo; that is a known gap, recorded
here rather than glossed over.

## 2. Scoring correctness

Verified against hand-built series where the right answer was known beforehand.

- Round-trip friction matches `backtest.py`: **stock 0.10%**, **crypto 0.90%**.
  A win in the Coach means what a win means in Proof Mode.
- `+1.0%` over 10 bars → UP wins, DOWN loses, STAND loses.
- `+0.5%` on crypto (inside the 0.90% round trip) → UP settles **flat**, and
  STAND **wins** — standing aside is correct when nothing was there to take.
- Not enough tape past the bar → returns `null`. The app **refuses to score**
  rather than inventing a number.

## 3. No-lookahead

The property the whole feature rests on.

- Setup tags computed at bar 39, then **every bar after 39 was overwritten with
  garbage** and recomputed: **identical output**. The future cannot leak into
  the setup a call is filed under.
- Rewound rendering draws only `[from..upto]`; the parked chart shows candles
  stopping dead at the cursor with the rest of the session absent.

**Stated limitation:** the price ladder is scaled to the whole session, so the
day's high and low are on screen before you walk into them — the range, not the
path. A deliberate product decision (a ladder that rescales every step is
unreadable), disclosed in the Coach panel rather than hidden.

## 4. Live-chart behaviour, driven in a real browser

Playwright against a local instance, real market data.

| Check | Result |
|---|---|
| Dial usable while live | range `312–345`, parked at edge, LIVE disabled, clock `live` |
| Scrub back to bar 325 | 14/34 bars drawn; price `$196.59` → `$197.68` |
| **Held through 2 live polls** | cursor did not move (the poll is no longer stopped) |
| Tape grew `345 → 347` while parked | cursor **held at 325**; dial max followed |
| GO LIVE | snapped to 347, price `$198.65`, badge cleared, button disabled |
| Symbol / timeframe change | cursor and drill window dropped, not carried over |

Cursor and session window are anchored by **timestamp**, not index, so they
survive the rolling tape on fast timeframes.

## 5. Defects found and fixed *before* release

Listed because they are the argument for driving the UI, not just the tests.

1. **Fatal:** `const esc` in `learn.js` collided with `app.js:29`. These load as
   classic scripts sharing one global scope, so this was a redeclaration
   `SyntaxError` that killed `app.js` — `init()` never runs, entire dashboard
   blank. Renamed to `learnEsc` / `learnPct`. Verified by loading the app and
   confirming **zero console errors**.
2. **Dial rendered dead** at `min=max=value=0`, undraggable — `_syncReplayUI()`
   only ran on replay actions, never on a live render.
3. **GO LIVE never disabled** while already live (same root cause).
4. **Duplicate control:** an old "✕ Live" button sat beside the new GO LIVE
   doing the identical job. Removed.
5. **Weakest / strongest tag lists overlapped.** With two qualifying tags,
   `slice(0,2)` and `slice(-2)` returned the same rows — the panel named one
   setup as both your best and worst read. Caught by an assertion.
6. **Coach panel had no padding:** heading flush at x=0, reset button overflowed
   off-screen.
7. **Drill session-open resolved by index**, which shifts when the tape grows
   between scan and apply. Changed to carry the timestamp.

Items 2, 3, 4 and 6 were visible only by looking at the rendered page. Item 1
would have taken the whole product down on load.

## 6. Coach panel, against a known record

Seeded with a record whose correct conclusions were determined in advance:

- Headline **53%**, "17 decisive calls" — the 7 that settled inside costs
  correctly excluded from the hit rate and reported separately.
- **"Your conviction is inverted"** — high-confidence 33% vs low-confidence 75%.
- Weakest: coiled 33% over 9. Strongest: RSI mid-range 100%, stacked-down 75%.
- Overtrading flag correctly **did not** fire at 29% (floor is 35%).
- Empty state renders "No calls yet" with **no `NaN`, `undefined` or `null`**.

Nothing prints below its sample floor — 8 calls for a tag, 5 for a confidence
bucket. Under that it says how many more are needed.

## 7. Drills

- Target selection picked `squeeze_on`, the seeded weakest read.
- Landed on NVDA bar 37; tags **recomputed independently** at that bar confirmed
  `squeeze_on` present; 346 candles hidden ahead.
- Second drill landed on a **different bar** (no repeats; last 40 remembered).
- GO LIVE fully tore the drill down: window back to today, cursor cleared, call
  row hidden.

**Sampling honesty:** drills come from a fixed roster of six liquid names,
declared up front and never reordered by results. Candidate bars are selected on
**setup alone** — the outcome is never consulted. Otherwise the tool would train
people on days that were obviously readable.

## 8. Privacy and packaging

- Learning Mode is **entirely local**: one `localStorage` key (`mp_learn`), no
  account, no network calls, nothing leaves the device. It therefore behaves
  identically in the downloadable zip.
- `static/learn.js` registered in all three required places — `index.html`,
  `sw.js` (SHELL_VERSION bumped to v12), and `BASE` in
  `tools/build_buyer_pack.py`. `tests/test_buyer_pack.py` enforces the third.
- Public-repo secret scan over the full diff: no keys, tokens, credentials,
  personal paths or emails.

## 9. What is NOT claimed

- No JS unit-test runner exists in the repo; JS coverage here is the two node
  harnesses plus browser-driven checks.
- Coach statistics come from calls the user chose to make, on days the user
  chose. That is not a random sample, and the panel says so.
- Nothing in Learning Mode grades an instrument or suggests a position. It
  grades process. No returns are promised or implied.
