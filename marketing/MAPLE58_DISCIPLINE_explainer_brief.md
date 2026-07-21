# MAPLE58 — "The Robot That Refuses" (Discipline Layer Explainer)

**Working title:** *I Built a Trading Robot Whose Main Job Is Saying NO*
**Alt titles:** *The Nine Times My Bot Refuses To Trade* · *Everybody Sells Signals. Nobody Sells Brakes.*
**Series:** MarketPulse / MAPLE58 — third cut. After the conceptual GET·KEEP·GROW·SHARE brief and the HOWTO onboarding brief. **This is the Pro-tier justification video.**
**Runtime target:** **7:30–8:30**
**Cast:** Quantus (`host_LOCKED.jpg`, VO `am_liam`) + Quintessence "Tess" (`tess_LOCKED.jpg`, VO `af_heart`) — same locked faces and voices as the ad pack.
**Build:** bake each line to `vo/<id>.wav` (Kokoro) → Kling Avatar 2.0 talking heads → dashboard/code B-roll PiP → assemble on the `ads_quantus_tess/build_ads.py` pattern. `loudnorm I=-14`.
**Honesty guardrails:** educational tool, not advice; "most options trades lose"; **never promise returns**; every number traceable to real code.

---

## The two-hander dynamic (why it's not just alternating lines)

**Tess names the wound. Quantus shows the stitch.**

Tess owns the human failure mode — she's the audience proxy, the one who says *"yeah, I've done that."* Quantus owns the control — he points at the code that stops it. That split gives every one of the nine beats a natural call-and-response, and it gives the poses something real to do: **Tess points at the chart, Quantus points at the code.**

Never let one host narrate a full guardrail alone. The rhythm is the argument.

---

## Pose vocabulary (emotive gestures — feed these into the Avatar prompt per line)

| Tag | Gesture | Use for |
|---|---|---|
| `POINT-CHART` | points down-left toward the lower-third chart/panel | naming what's on screen |
| `POINT-CODE` | points down-right toward the code panel | citing the actual file |
| `POINT-VIEWER` | index toward camera | direct address, the hard truths |
| `STOP-PALM` | flat palm up, halt | refusals, "it stops" |
| `COUNT-3` | three fingers raised | the three-loss breaker |
| `OPEN-PALMS` | both palms up, level | "straight up," honesty beats |
| `ARMS-CROSSED` | arms folded, skeptical | Tess calling out hype |
| `LEAN-IN` | leans toward camera, confiding | the smart details |
| `HAND-CHOP` | downward chop | hard rules, non-negotiables |
| `HEAD-SHAKE` | slow no | "it will not make you money" |
| `SLOW-NOD` | quiet agreement | landing a point |

**Rule:** one pose per line. Gesture lands on the emphasized word, not the first word.

---

## Music — Lion of Mali score, mixed UNDER the voices

Source: `~/Downloads/lion_of_mali_audio/`. Total **8:54** across three cues — covers an 8-minute cut with headroom.

| Act | Track | File | Length | Why |
|---|---|---|---|---|
| I — Setup | **Nine Witches of Mali** | `nine_witches_of_mali.mp3` | 3:13 | Tension, unease — "here's how people blow up" |
| II — The Nine | **Buffalo Woman Rising** ✅ | `buffalo_woman_rising.mp3` | 2:52 | Steady, building — carries the nine without stealing focus |
| III — Close + outro | **The Lion Rises** | `the_lion_rises.mp3` | 2:49 | Earned lift under the honest close and the drive-off |

### Mix — really low, words never drowned

Ad pack ran the bed at ~0.10. **This cut runs about a third of that**, because the script is wall-to-wall spoken numbers and two voices trading fast.

- **Bed level `volume=0.035`** (≈ −29 dB) under all VO. Atmosphere, never competition.
- **Sidechain-duck** against the VO bus so it drops further on every line — with two hosts trading, the bed must ride *both*.
- **Swell to `0.09`** twice only: the cold-open beat, and the outro drive-off.
- **Full stop under the honest close (S7).** No music at all. Silence reads as sincerity and makes the outro land.
- 1.5s crossfade at act boundaries; never hard-cut between cues.

```
ffmpeg -i vo_bus.wav -i bed.mp3 -filter_complex \
  "[1:a]volume=0.035,afade=t=in:d=1.5[bed]; \
   [bed][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=350[duck]; \
   [duck][0:a]amix=inputs=2:duration=first:dropout_transition=0[mix]; \
   [mix]loudnorm=I=-14:TP=-1.5:LRA=11[out]" \
  -map "[out]" -c:a aac -b:a 192k mixed.m4a
```

Check the export against the AAC click/loudness rule before publishing.

---

## The thesis (say it plain, up top)

> **QUANTUS:** "Everybody out here selling you signals. Nobody's selling you brakes."
> **TESS:** "This robot's main job ain't finding trades. It's refusing them."
> **QUANTUS:** "And the code that says no? It doesn't ask the AI for permission."

Straight from the file header — put it on screen:

> *"Each check is independent: prompt/signal output never decides whether a trade is allowed, these functions do."*

---

## ACT I · THE SETUP (0:00 – 1:20) — bed: Nine Witches of Mali

| id | speaker | pose | line | on-screen / B-roll |
|----|---------|------|------|--------------------|
| `q_open` | QUANTUS | `POINT-CHART` | This is my trading robot finding a setup it likes. Watch what it does next. | terminal, signal fires |
| `q_open2` | QUANTUS | `STOP-PALM` | It said no. To itself. That's not a bug — that's the part I paid the most attention to. | terminal prints the refusal, held 2s |
| `t_wound` | TESS | `ARMS-CROSSED` | Here's how people actually lose money. It's never one bad call. It's a chain. | black card: "IT'S NEVER ONE BAD CALL" |
| `t_wound2` | TESS | `LEAN-IN` | You take a loss, so you size up to make it back. That one loses too. Now you're mad — and mad is expensive. By Friday the account that was supposed to teach you something is just gone. | slow zoom, red candles, no numbers |
| `t_wound3` | TESS | `POINT-VIEWER` | Nobody blows up from being wrong once. They blow up from being wrong, then reaching. | hold on Tess |
| `q_turn` | QUANTUS | `POINT-CODE` | So when I built the agent layer, I didn't spend the time on the part that picks. I spent it on the part that refuses. | `guardrails.py` header comment |
| `q_turn2` | QUANTUS | `HAND-CHOP` | Nine separate controls. Any one of them kills an order on its own. | six exception class names scroll |

---

## ACT II · THE NINE (1:20 – 6:00) — bed: Buffalo Woman Rising

**Pattern per guardrail: Tess names the wound → Quantus shows the control.** ~30s each.

| id | speaker | pose | line | on-screen |
|----|---------|------|------|-----------|
| `t_g1` | TESS | `ARMS-CROSSED` | Most bots start trading the second you turn them on. | competitor-style "auto-trade ON" mock |
| `q_g1` | QUANTUS | `OPEN-PALMS` | Not this one. Out the box it proposes — you approve. Default mode is propose. Default account is paper. Fake money. You have to go out of your way to point it at real cash, and most bots ship the other way around. That's a choice they made about you. | `MODE = "propose"` · `PAPER = True` |
| `t_g2` | TESS | `POINT-VIEWER` | Everybody's got a size they swear they'd never go past. Until the day they do. | — |
| `q_g2` | QUANTUS | `POINT-CODE` | So it's not a promise, it's a ceiling. No single order past one hundred dollars. Not because one hundred is magic — because a cap you set on a calm Tuesday protects you from the version of you that shows up on a red Thursday. | `MAX_SINGLE_TX_USD` |
| `t_g3` | TESS | `LEAN-IN` | And the day you're down? That's the day you want to keep going. | — |
| `q_g3` | QUANTUS | `HAND-CHOP` | Four hundred dollars a day. Rolling twenty-four hours. It counts what you already spent before it lets you spend more. This is the one that kills the death spiral — you cannot revenge-trade past it, because the ledger says no. | `MAX_DAILY_SPEND_USD` |
| `q_g4` | QUANTUS | `STOP-PALM` | One flag. Everything stops. Manual, or automatic when something else trips. There is always a way to make it all stop. | `check_not_halted()` |
| `t_g5` | TESS | `POINT-CHART` | A signal fires. You step away, make a sandwich, come back. | chart moving while away |
| `q_g5` | QUANTUS | `POINT-CODE` | Thirty minutes later that read is old news. The market moved without you. So it expires — thirty minutes, then it's dead and it will not send. A stale plan is a different plan. | `PROPOSAL_TTL` |
| `t_g6` | TESS | `ARMS-CROSSED` | This next one sounds paranoid. | — |
| `q_g6` | QUANTUS | `LEAN-IN` | It is. On purpose. Right before sending, it checks the ticker against the allowed list again — even though it already checked. Because the queue could be corrupted, tampered with, or just wrong. Last thing you want is a bot confidently buying something nobody approved. | quote on screen: *"The chokepoint must not trust the proposal record."* |
| `t_g7` | TESS | `POINT-CHART` | Your edge was at that price. What about this one? | ref price → live price, gap widening |
| `q_g7` | QUANTUS | `HAND-CHOP` | It saves the price from when the signal fired, pulls the live price, compares. Stocks — moved more than half a percent against you, cancel. Crypto, one and a half percent, because crypto's wilder. At a worse price it might not be an edge at all. | `MAX_SLIPPAGE_PCT` |
| `t_g8` | TESS | `POINT-VIEWER` | After three losses in a row, you are not analyzing anymore. You're chasing. | — |
| `q_g8` | QUANTUS | `COUNT-3` | Three losses and it halts itself. Not a suggestion — it stops. The robot doesn't get tilted, so it can notice that you are. | `MAX_CONSECUTIVE_LOSSES` |
| `t_g9` | TESS | `SLOW-NOD` | And the whole day? | — |
| `q_g9` | QUANTUS | `POINT-CODE` | It snapshots your equity when the day starts. Down five percent, everything halts. Five percent is a bad day. Five percent is survivable. It's the tenth bad day in a row that ends you — this makes sure today ends at bad, not fatal. | `MAX_DAILY_LOSS_PCT` |

---

## ACT III · THE PART THAT MAKES IT REAL (6:00 – 8:15) — bed: The Lion Rises

| id | speaker | pose | line | on-screen |
|----|---------|------|------|-----------|
| `q_asym` | QUANTUS | `LEAN-IN` | Now sit with this one. The spend caps only apply to buys. | `if proposal["side"] == "buy"` highlighted |
| `t_asym` | TESS | `OPEN-PALMS` | Selling is never blocked. Never. You can always get out. | comment: *sells reduce exposure; don't spend-cap exits* |
| `q_asym2` | QUANTUS | `HAND-CHOP` | A cap that trapped you in a position would be a cap that hurt you. | hold |
| `t_asym2` | TESS | `POINT-CODE` | Same idea in what it acts on. To enter, it needs STRONG BUY — highest conviction. To exit? Any sell signal at all will do. | `ENTRY_LABELS` vs `EXIT_LABELS` |
| `q_asym3` | QUANTUS | `POINT-VIEWER` | High bar to get in. Low bar to get out. That's not a setting. That's a whole philosophy about being wrong. | big text card |
| `q_fail` | QUANTUS | `STOP-PALM` | One more. If the live price is missing when it goes to send — API down, network hiccup, whatever — it doesn't guess and it doesn't send anyway. It refuses. | quote: *"refusing to send blind"* |
| `t_fail` | TESS | `SLOW-NOD` | When it doesn't know, it does nothing. You know how rare that is? | hold on Tess |
| `q_receipt` | QUANTUS | `POINT-CODE` | None of this is a claim. Every number we said is in the file. Open it yourself. | split: spoken number ↔ real `config.py` line |
| `t_receipt` | TESS | `OPEN-PALMS` | One hundred. Four hundred. Three. Five percent. Thirty minutes. Half a percent. One and a half percent. All of it, right there. | test suite passing — **no P&L, no balances** |

**S7 · The honest close — MUSIC FULLY OUT**

| id | speaker | pose | line | on-screen |
|----|---------|------|------|-----------|
| `t_close1` | TESS | `OPEN-PALMS` | So let's be straight about what this is not. It is not advice. We're not your advisors, and this isn't a recommendation. | plain black card |
| `q_close1` | QUANTUS | `HEAD-SHAKE` | It will not make you money. Most options trades lose. That's not pessimism, that's the math — and any tool telling you different is selling you something. | hold, no motion |
| `t_close2` | TESS | `POINT-VIEWER` | Guardrails aren't a guarantee. They're seatbelts. Seatbelts don't make you a good driver — they make crashing survivable. | — |
| `q_close2` | QUANTUS | `LEAN-IN` | What this is: the discipline you already know you need, written down in code, so it works on the days you don't feel like it. | slow push in |
| `both_bumper` | QUANTUS+TESS | `OPEN-PALMS` | QUANTUM MELANIN MEDIA. Voice and receipts for the unparented diaspora. | ÀṢẹ + gold MAPLE58 wordmark |

## S8 · 3-Bizzle outro (staple) — reuse existing footage

⚠️ **Asset reality check.** There is no existing clip of Quantus and Tess *in* the car. The 3-Bizzle footage on hand is **car-only** — tinted windows, no visible occupants. Confirmed by frame extraction, not by filename.

Available:

| Clip | Length | Size | Shape |
|---|---|---|---|
| `~/Downloads/3bizzle vid1.mp4` | 15s | 864×496 | drives toward camera → **away into the horizon** ✅ |
| `~/Downloads/3 bizzle vid swerve.mp4` | 10s | 864×496 | swerve/drift, stays facing camera |
| `~/Downloads/3bizzle vid2.mp4` | 10s | 640×640 | square — for Shorts |
| `~/Downloads/3bizzle vid3.mp4` | 5s | 640×640 | square — for Shorts |

All four: black Camaro, red stripes, Egyptian temple columns, gold sacred-geometry lattice, sunset. On-brand and reusable as-is.

### The three-beat outro — generate one shot, reuse the rest

| Beat | Source | Direction |
|---|---|---|
| **1 · The walk-off** (~3s) | **generate** | Quantus + Tess (locked faces) walk away from camera toward the Camaro in the temple corridor. Backs to camera — sidesteps face-drift entirely at the one moment we don't need their faces. Match the sunset key light and column geometry of the plate. |
| **2 · The drive-away** (~6s) | ✅ **LOCKED: `~/Downloads/3bizzle vid1.mp4` @ 09:00–15:04** | Hard-cut on the door-close beat. Tinted windows do the work — the audience just watched them walk to it, so the car reads as occupied. |
| **3 · End card** (4s) | **reuse `norm_qt/endcard.mp4`** | ÀṢẹ + gold MAPLE58 wordmark, matching the ad pack. |

### Why that window

`3bizzle vid1.mp4` is **15.046s, 24fps, 864×496**. Frame-sampled across the timeline:

- **t≈6–10s** — low tracking side shot, dust kicking off the rear tyre, car mid-frame
- **t≈12s** — the temple doorway opens onto the **sacred-geometry sun and a city skyline on the horizon** ← the reveal
- **t≈15s** — resolves on that horizon

Cutting at **9.0s** gives ~3 seconds of motion build before the doorway reveal, then resolves out — a 6-second beat that ends on the skyline rather than mid-corridor. *The Lion Rises* swells to `0.09` on the hard cut in, and the horizon reveal lands under the swell.

**⚠️ Do not use `scale=1920:-2` here.** At 864×496 the plate is *narrower* than 16:9 (1.742 vs 1.778), so scaling width to 1920 yields a 1102px height — taller than 1080 — and `pad` then fails with *"Padded dimensions cannot be smaller than input dimensions."* Tested and confirmed broken.

**Option A — pillarbox (safe, tested ✅)**

```
ffmpeg -ss 9.0 -to 15.04 -i ~/Downloads/"3bizzle vid1.mp4" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,\
pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=24" \
  -an -c:v libx264 -crf 18 -pix_fmt yuv420p outro_drive.mp4
```

Verified output: **1920×1080, 6.04s, 145 frames, ~6.8 MB.** Leaves ~20px black bars each side.

**Option B — crop to fill (recommended)**

```
ffmpeg -ss 9.0 -to 15.04 -i ~/Downloads/"3bizzle vid1.mp4" \
  -vf "scale=1920:-2,crop=1920:1080,fps=24" \
  -an -c:v libx264 -crf 18 -pix_fmt yuv420p outro_drive.mp4
```

Trims ~11px off top and bottom to fill the frame edge-to-edge. On a low tracking car shot that loss is invisible, whereas pillarbars are not. **Prefer B unless the crop clips the sacred-geometry lattice** — check the t≈12s reveal frame before committing.

`-an` drops the clip's own audio so *The Lion Rises* owns the outro. Add engine SFX under the swell only if it doesn't fight the bed at `0.09`.

**Final frame** resolves on: Camaro frame-right, temple doorway open to the sacred-geometry sun, ruins and skyline on the horizon. Hold it under the swell before cutting to the end card.

*The Lion Rises* swells to `0.09` on the cut to beat 2, resolving under the end card.

**Render note:** the 864×496 plates are **1.742:1, not 16:9 (1.778)**. Scale to height and pad — do not stretch:
`scale=1920:-2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black`

**If you'd rather have them genuinely visible in the car:** the cheapest honest option is a single generated interior shot — both in the front seats, temple light raking across the windshield — cut *between* beats 1 and 2. That's one extra generation and it makes the staple literal rather than implied. Worth doing once and banking as a reusable outro asset for every future explainer.

---

## Cutdowns (short-per-drop)

| Cut | Source | Hook |
|---|---|---|
| **9:16 #1** | `t_g8` + `q_g8` | Tess: "After three losses you're not analyzing, you're chasing." → Quantus `COUNT-3`: "So it stops itself." |
| **9:16 #2** | `q_asym` → `t_asym` | "The spend cap only blocks buying. Selling is never blocked." |
| **9:16 #3** | `t_g6` + `q_g6` | "This next one sounds paranoid." / "It is. On purpose." |

Each Short closes on the **square** 3-Bizzle plates (`3bizzle vid2.mp4` 10s or `vid3.mp4` 5s, both 640×640) — they crop to 9:16 without the pad the wide plates need.

Post-kit per drop: title, description with disclaimer, pinned comment, 3 tags, thumbnail concept.

---

## Thumbnail concepts

1. Quantus `STOP-PALM`, big red **"NO"** — subtitle: *the feature nobody sells*
2. Split: Tess `ARMS-CROSSED` left "AI PICKS THE TRADE" (dim) / Quantus `POINT-CODE` right "**AI REFUSES THE TRADE**" (lit gold)
3. Quantus `COUNT-3`, big text **"3 LOSSES → IT STOPS ITSELF"**

---

## Description block (must include)

- One-line what it is
- **"Educational tool. Not financial advice. Most options trades lose."**
- Link to `DISCLAIMER.md`
- Free build (PolyForm Noncommercial) + Gumroad Pro link
- "Every number in this video comes from the config file — read it yourself"
- **No performance claims, no P&L, no guaranteed anything.**

---

## Production notes

- **B-roll is credit-free:** the tool's own screens, the terminal, the source files. Only the Quantus/Tess avatar segments need generation.
- **Spell numbers for TTS:** "one hundred dollars," "five percent," "thirty minutes," "half a percent," "one and a half percent."
- **Pose lands on the emphasized word**, not the first word of the line. `COUNT-3` hits on "three," not on "So."
- **Show the code.** Real files, syntax-highlighted, actual comments. The comments carry the honesty — the one thing a competitor can't copy, because they'd have had to write it.
- **Do not animate a rising equity curve anywhere in this video.** Not as decoration, not as background. It is the single visual that would contradict the entire script.
