# MAPLE58 — "What It Is & How To Run It" (Onboarding Explainer)

**Why this video exists (user's words):** *"a large part of why things like this don't sell is because people don't even know exactly what it is or how to use it when they do get it."* This is the hands-on counterpart to the conceptual GET·KEEP·GROW·SHARE cuts — the video a buyer (or a fence-sitter) watches to see *exactly* how the thing lands on their computer and runs.

**Target length:** ~2:30–3:00 (tight, practical, no fluff).
**Voice:** Kokoro `am_michael`, honest QMM tone.
**Music:** low lofi bed, sidechain-ducked under VO, body ~0.07 + small outro swell (per the locked envelope lesson).
**Honesty guardrails:** educational tool, not advice; "most probes lose"; never promise returns.

---

## The spine (what makes this different)
1. **WHAT it is** — plain, in one breath.
2. **HOW you get it** — the Gumroad download → unzip → run flow, shown as clean steps.
3. **WHAT you see** — a fast guided tour of the actual screens (reuse close-ups/walkthrough B-roll).
4. **HOW to read it** — the GET·KEEP·GROW·SHARE funnel in 20 seconds.
5. **The honest close** — what it is NOT.

---

## Script (VO sections — numbers spelled for TTS)

**S1 · Hook (≈15s)**
> "You found a tool called MarketPulse — codename MAPLE58. Maybe you bought it, maybe you're deciding. Either way, here's the part nobody explains: exactly what it is, and exactly how to get it running on your own computer. No tech degree required."

**S2 · What it is (≈20s)**
> "MAPLE58 is an honest options-research dashboard. It pulls live market data, reads the technicals, and walks you through one question — what's a play I can actually afford, and how do I lose small when I'm wrong. It runs on your machine. No account, no subscription, no data leaves your computer."

**S3 · How you get it onto your computer (≈35s)** — the key part
> "Here's how it lands on your computer. When you buy on Gumroad, you get one file: a zip. Download it, then unzip it — that gives you a folder called MarketPulse. Inside is everything: the program, and a launcher.
> On Windows, you double-click run-dot-bat. On Mac or Linux, you run bash run-dot-sh. That's it. The launcher starts a tiny web server on your own machine and opens the dashboard in your browser at localhost, port eight thousand. To stop it, just close the window. The whole thing is written so you don't have to install anything fancy — you only need Python, which is free from python-dot-org."

**S4 · The tour — what you're looking at (≈40s)** — reuse close-ups
> "Open it up and here's what you've got. Up top, tabs: Stocks, Options, your Pot, and Proof Mode.
> The Options tab is the heart of it. It reads top to bottom like a funnel. First, the Nudge — plain English, which way the data leans, framed as a read, never an order. The choice is always yours. Below that, the strategy card — the actual structure and what one contract costs in real dollars. Then the Probe plan — the smallest first bet that still tells you something. Then The Read — a six-step breakdown of trend, coil, signal, volatility, the play, and the catch. And a glossary, so every number on screen has a plain definition."

**S5 · The four jobs (≈25s)**
> "Everything maps to four jobs: GET — find a play you can afford. KEEP — be wrong cheaply, with spend caps and a readability floor so you're not buying dead lottery tickets. GROW — escalate only your winners, tracked in the Pot. And SHARE — Proof Mode backtests the exact signal over years and shows you the losses too, not just the wins."

**S6 · Honest close (≈20s)**
> "Here's what it is NOT: it's not a money printer, and it will never tell you you're about to get rich. Most options trades lose — that's not a bug, that's the math, and this tool is built to keep you alive long enough to learn. Educational, not financial advice. Slow and alive beats fast and liquidated. That's MAPLE58."

---

## Visuals plan (per section)
- **S1/S2:** title card (MAPLE58 + "what it is / how to run it") + a clean app hero shot.
- **S3:** step cards (1 download zip · 2 unzip → folder · 3 run.bat / run.sh · 4 opens localhost:8000) — animated reveal; show the actual `MarketPulse/` folder contents + `run.bat`. *(OS-level unzip/double-click is not browser-capturable; render as clean numbered step cards, not a fake screen recording.)*
- **S4:** the existing close-ups (`marketing/closeups/cu_nudge/strategy/probe/read/chain`) held STILL & fit-to-frame (per the no-Ken-Burns-on-dense-UI lesson).
- **S5:** four limb cards GET/KEEP/GROW/SHARE (reuse thumb motif) + Pot Tracker + Proof close-ups.
- **S6:** dark title card, honest framing.

## Build pipeline (proven)
1. `tools/synth_vo_maple58_howto.py` (Kokoro am_michael → `marketing/vo_maple58_howto/`)
2. capture/refresh any missing close-ups via Playwright on the live app (1920×1080)
3. `tools/build_explainer_maple58_howto.py` (step cards + close-ups + title cards, VO-paced, ducked lofi bed w/ outro swell)
4. `tools/build_thumb_maple58_howto.py` ("HOW TO RUN IT" + MAPLE58)
5. **STOP — ear-confirm audio with user, get go-ahead, THEN** upload via `quantus-autoposter`.

## Title / desc (draft)
- **Title:** "MAPLE58 / MarketPulse — What It Is & How To Run It On Your Computer (2 min setup)"
- **Desc:** plain setup steps + needs Python (python.org) + Gumroad `yvsyyg` + honest "most probes lose / not advice".
