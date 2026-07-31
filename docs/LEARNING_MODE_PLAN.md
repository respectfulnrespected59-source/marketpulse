# Learning Mode — Implementation Plan

**Status:** proposed, not built. **Owner:** QMM. **Drafted:** 2026-07-31.

The ask: *"add learning mode to MarketPulse that way it literally LEARNS from
EVERYONE USING IT and keeps gettin better."*

This document says what "learns" is allowed to mean here, what it must never
mean, and the order to build it in.

---

## 0. The fork in the road (decide this first)

There are three different products hiding inside "it learns from everyone."

| | What it learns | Verdict |
|---|---|---|
| **A. Learns YOU** | your personal blind spots, from your own replay calls | **BUILD FIRST** — zero infra, zero privacy surface, ships in the zip |
| **B. Learns TEACHING** | which setups fool the most people, in aggregate | **BUILD SECOND** — needs a server, consent, and a k-anonymity floor |
| **C. Learns to PREDICT** | pools users' calls into a crowd entry signal | **DO NOT BUILD** — see below |

### Why C is refused

Turning pooled user behaviour into a "the crowd says BUY" signal breaks the
product on four separate axes:

1. **It becomes advice.** A number derived from other people's positions,
   displayed before you commit, is a recommendation — regardless of the
   disclaimer under it. Everything else in this app is a *read*, never an order.
2. **It is probably backwards.** Retail consensus is a well-documented
   contrarian/noise indicator. We would be shipping a signal we have no evidence
   works, into the exact audience least able to absorb the loss.
3. **Consent and data protection.** Aggregating individuals' trading behaviour
   into a product feature is a materially different data relationship than
   "an app that draws charts."
4. **It contradicts the brand.** The entire MarketPulse thesis is *prove the
   logic, never claim the returns* (Proof Mode exists to show the losses). A
   crowd signal is a returns claim wearing a lab coat.

**The honest use of the same data is inversion:** show the crowd was *wrong*,
*after* the user has committed their own call. "68% of players bought this
candle. The session closed down 1.9%." That is a hindsight-bias lesson, and it
is exactly on-brand. Same data, opposite direction, no recommendation.

**Hard product rule:** aggregate crowd data may only ever be revealed
**after** the user's own call is locked in. Never before, never as an entry cue.

---

## 1. Where this plugs into the existing app

Learning Mode rides on **Replay** (`static/chart.js`, `static/chart-tools.js`),
which already does the hard part: `enterReplay()`, `replayStep(±1)`,
`replaySeek()`, and a bar cursor that guarantees the user only sees what the
market knew at that bar. That no-lookahead property is the entire foundation —
without it there is nothing honest to learn from.

The missing piece is that replay currently produces **no record**. You walk the
day and the experience evaporates.

### The one new primitive: a Call

Before stepping to the next bar, the user commits a **Call**:

```
{ dir: "up" | "down" | "stand",   // stand aside is a first-class answer
  conf: 1 | 2 | 3,                // low / medium / high
  bar:  <index>,                  // resolved against the NEXT n bars
  tags: [...] }                   // the setup, from the existing engine
```

`stand` being a real option matters: an app that only scores directional calls
teaches overtrading, which is the single most expensive retail habit.

### Setup tags come free from code we already have

This is the key reuse — no new market logic is needed. Every tag is already
computed:

| Tag | Source |
|---|---|
| `squeeze_on` / `squeeze_fired` | `indicators.ttm_squeeze` |
| `stack_bull` / `stack_bear` / `stack_mixed` | `indicators.ma_stack` |
| `rsi_hot` / `rsi_cold` / `rsi_mid` | `indicators` RSI band |
| `above_vwap` / `below_vwap` | `indicators.session_vwap` |
| `iv_high` / `iv_modest` | `options.py` ATM IV regime |

A Call is scored against forward bars using the same cost realism already in
`backtest.py` (`COMMISSION_BPS` / `SLIPPAGE_BPS`) so a "win" means a win after
friction — consistent with Proof Mode.

---

## 2. Phase 1 — Learns YOU (local, no server)

**Ships in the hosted demo AND the downloadable zip. No infra. No consent
question, because nothing leaves the machine.**

- New `static/learn.js`; storage key `mp_learn` (same pattern as `mp_pot`).
- Records Calls, resolves them N bars forward, accumulates per-tag stats.

**What it computes:**

- **Per-tag hit rate.** *"Coiled-squeeze breakouts: 38% over 21 calls.
  Trend continuation: 71% over 34."*
- **Calibration.** Confidence vs. reality — the most useful and least flattering
  number in the app. *"On high-confidence calls you're 44%. On low-confidence,
  61%. Your conviction is inverted."*
- **Behavioural flags**, each earned from the record, not vibes:
  - *overtrading* — took a directional call on >X% of bars where `stand` scored better
  - *revenge sizing* — confidence rises immediately after a loss
  - *hindsight drift* — accuracy collapses when replay speed is high (pattern-matching the shape instead of reading the bar)
- **Drill generator.** Finds historical sessions matching the user's *weakest*
  tags and serves them as replays. This is the "keeps gettin better" loop, and
  it is fully local.

**UI:** a "Coach" panel — the same shape as the existing Pot tab. One headline
grade, the calibration curve, the two weakest tags, and a **Run a drill** button.

**Effort:** ~2 sessions. **Risk:** low. **Dependencies:** none.

---

## 3. Phase 2 — Learns TEACHING (aggregate, opt-in)

Only after Phase 1 is producing clean local records.

### Storage — the real constraint

The server writes nothing today, Render's free tier has an ephemeral disk and
spins down when idle, and the zip must stay pip-free. So:

- **Not** a local file (wiped on every deploy).
- **Not** a Postgres/MySQL driver (breaks the no-pip-installs promise).
- **Yes:** an **HTTP-API database over `urllib`** — TiDB Cloud's serverless data
  API (already in use on Alignment 365) or Supabase PostgREST. HTTPS + JSON is
  stdlib, so `app.py` stays dependency-free.

Isolate it in a new `telemetry.py`, imported **only** when
`MP_LEARN_AGGREGATE=1`. The downloadable zip never sets it, so buyers ship a
build with the code path inert. Fails closed like `config.TIER`: no env var, no
aggregation.

### Consent and payload

- **Default OFF.** Explicit opt-in toggle with the payload shown verbatim before
  the first send. Opting out later purges the remote record.
- **Sent:** random install UUID (localStorage, resettable), setup tag vector,
  the call, the resolved outcome, replay speed.
- **Never sent:** watchlist, pot size, positions, alerts, symbols the user
  searched, IP retention, or anything resembling identity.
- **k-anonymity floor:** no aggregate stat is displayed unless it is computed
  from **≥30 distinct install ids**. This doubles as a statistical guard — it
  stops us teaching lessons drawn from four people.

### What it unlocks

- *"Across everyone who played this setup, 68% bought. It closed down."* —
  revealed **after** the user's own call. Never before.
- A ranked list of **the setups that fool the most people**, which is a genuine
  moat: nobody else has it, and it gets better with every session played.

**Effort:** ~2–3 sessions plus a storage decision. **Risk:** medium — this is
the phase where consent and honesty have to be designed in, not bolted on.

---

## 4. Phase 3 — The loop closes into content

The "setups that fool the most people" ranking is an **explainer-topic queue
that generates itself**, feeding the QMM content engine with receipts:
*"73% of players read this coil as a breakout. Here's what it actually did."*
Real data, honest framing, endlessly renewable. The tool teaching people
becomes the content that brings people to the tool.

---

## 5. Honest risks

- **Selection bias.** Only people who *finish* replays report — likely the more
  engaged and more skilled. Aggregate stats skew optimistic. State this in the UI.
- **Small-N noise.** The k-anonymity floor is the mitigation; do not lower it.
- **Survivorship in drill selection.** Drills must be sampled from a fixed
  historical universe, not from sessions that happen to be interesting.
- **Scope creep into C.** Every future request of the form "can it just tell me
  what the crowd thinks *before* I call it" is the refused product wearing a new
  hat. The answer is no.
- **Coaching is not advice.** Everything here grades *the user's process*. It
  never grades an instrument or suggests a position. Positioning stays locked by
  the no-guaranteed-returns rule.

---

## 6. Build order

1. **Call primitive + local recording** on top of existing Replay (`learn.js`)
2. **Per-tag stats + calibration** — the honest mirror
3. **Coach panel** — one grade, calibration curve, two weakest tags
4. **Drill generator** — closes the personal improvement loop
5. *(gate: is Phase 1 producing clean records?)*
6. **Storage decision + `telemetry.py`** behind `MP_LEARN_AGGREGATE`
7. **Consent UI + opt-in/purge**
8. **Crowd-was-wrong reveal**, post-call only, k≥30
9. **Fooled-the-most-people ranking** → content queue

Steps 1–4 ship a complete, honest, self-contained Learning Mode with **no
server, no consent burden, and no new dependencies** — and it works in the
downloadable zip, which the aggregate version never will.
