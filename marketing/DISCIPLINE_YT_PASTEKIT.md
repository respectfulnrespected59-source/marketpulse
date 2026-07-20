# YouTube paste-kit — "The Robot That Refuses"

**Upload from YOUR Chrome** (profile `absonation2339@gmail.com` = QMM YouTube).
NOT the automation browser — that one is `respectfulnrespected59` = N.O. DABOSS.

**File:** `C:\Users\respe\marketpulse\marketing\DISCIPLINE_the_robot_that_refuses.mp4`
**Runtime:** 4:41 · 1920×1080 · 18.5 MB
**Visibility:** PUBLIC · **Audience:** No, it's not made for kids

---

## TITLE

```
I Built a Trading Robot Whose Main Job Is Saying NO
```

**Alternates**
```
The 9 Times My Trading Bot Refuses To Trade
```
```
Everybody Sells Signals. Nobody Sells Brakes.
```

---

## DESCRIPTION

```
Everybody sells you signals. Nobody sells you brakes.

MarketPulse (codename MAPLE58) has an agent layer, and its main job isn't finding
trades - it's refusing them. Nine independent controls, and any one of them can kill
an order on its own. In this one Quantus and Tess walk through all nine, straight
from the source file.

The nine:
00:00  It finds a setup it likes - then says no
01:00  1 - Propose, don't execute (paper money by default)
01:30  2 - $100 per-trade ceiling
02:00  3 - $400/day rolling cap, kills the death spiral
02:20  4 - The kill switch
02:40  5 - Signals expire after 30 minutes
03:00  6 - It re-checks its own ticker list
03:20  7 - Slippage bands: 0.5% stocks, 1.5% crypto
03:40  8 - Three losses in a row, it halts itself
04:00  9 - Down 5% on the day, everything halts
04:15  The asymmetry: buys are capped, selling is NEVER blocked
04:30  Fail closed: no live price, no order

Every number in this video comes out of the actual config file. Open it and check.

- WHAT THIS IS NOT -
This is an educational tool. It is not financial advice, and nothing here is a
recommendation to buy or sell anything. Quantum Melanin Media is not a registered
investment adviser or broker-dealer. Most options trades lose - that's the math, not
pessimism. Guardrails are seatbelts: they don't make you a good driver, they make
crashing survivable. Never trade money you can't afford to lose entirely.

Full risk disclosures: see DISCLAIMER.md in the repo.

- GET IT -
Free build (PolyForm Noncommercial): https://github.com/respectfulnrespected59-source/marketpulse
MarketPulse on Gumroad: https://quantummelaninmedia.gumroad.com

Runs on your own machine. No account, no API key, no monthly fee, no data leaves
your computer.

QUANTUM MELANIN MEDIA - voice + receipts for the unparented diaspora.
```

---

## TAGS

```
risk management, trading discipline, algorithmic trading, trading bot, python, options trading, circuit breaker, guardrails, fintech, open source, marketpulse, maple58, quantum melanin media, not financial advice, trading psychology
```

---

## PRE-PUBLISH CHECKLIST

- [ ] Chrome profile is **absonation2339** (QMM) — not N.O. DABOSS
- [ ] Visibility **PUBLIC**
- [ ] Audience: **not made for kids**
- [ ] Disclaimer paragraph present in the description (non-negotiable)
- [ ] No performance claims, no P&L figures anywhere
- [ ] Timestamps land correctly once processing finishes
- [ ] Pinned comment posted (below)

## PINNED COMMENT

```
Every number in this video is in the config file - MAX_SINGLE_TX_USD, MAX_DAILY_SPEND_USD,
MAX_CONSECUTIVE_LOSSES, MAX_DAILY_LOSS_PCT, PROPOSAL_TTL, MAX_SLIPPAGE_PCT. Don't take my
word for it, read it yourself. Educational tool, not financial advice. Most options trades lose.
```

---

## NOTE ON THE SAVED TOKEN

`quantus-manim/youtube_token.pkl` is valid and refreshes, but its scope is
`youtube.upload` only — which means the API will not report which channel it
belongs to. Since N.O. DABOSS also hosts QMM content, a blind API upload could
land on the wrong channel, and upload-only scope cannot delete it afterward.

Manual upload from the `absonation2339` Chrome profile avoids that entirely.

If you want API uploads in future, re-run the OAuth consent for the token adding
`https://www.googleapis.com/auth/youtube.readonly`, then `channels().list(mine=True)`
can confirm the channel before any upload runs.
