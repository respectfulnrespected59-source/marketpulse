# MAPLE58 — Quantus + Tess "Honest Sales Reps" Ad Pack
**Goal:** Drive Gumroad purchases (https://quantummelaninmedia.gumroad.com/l/yvsyyg).
**Format:** 9:16 vertical (Shorts / TikTok / Reels). Hero ~36s + 15s cutdown.
**Cast:** Quantus (host_LOCKED.jpg, VO `am_liam`) + Quintessence "Tess" (tess_LOCKED.jpg, VO `af_heart`).
**Tone:** warm, anti-hype, plain-English. THE HOOK IS THE HONESTY. No "get rich." On-brand:
"most options trades lose — survival is the skill." Every claim is a REAL product fact.
**Sign-off:** Àṣẹ ("ah-shay"), on-screen ÀṢẹ. Music: QMM Bay mob-funk, no dirge (per taste lock).
**Upload gate:** assemble → user verifies finished video → THEN upload. Do NOT auto-upload.

---

## HERO (9:16, ~36s) — "We Won't Promise You A Lambo"

| # | Speaker | Line (VO) | On-screen / B-roll |
|---|---------|-----------|--------------------|
| q_intro | Tess (skeptical, arms crossed) | "Most options tools promise you a Lambo. We're not gonna do that." | Tess to camera; hard cut from a fake "🚀💰" hype reel that glitches out |
| q_math | Quantus (talking, level) | "Real talk — most options trades lose. That's the math. So we built a little robot that loses small and survives." | Quantus to camera; MAPLE58 logo / dashboard wakes up |
| q_get | Tess (explaining) | "MAPLE58 finds plays you can actually afford — the cheapest usable probe, not the four-thousand-dollar lottery." | GET: Scan results list (SNAP $9, NIO $14, F $16), "qualifies at a $300 pot" |
| q_keep | Quantus (pointing) | "It shows the price in real dollars — six fifty, not one-seventy-nine — and tells you when a play's too rich. Walk." | KEEP: per-contract $ chain; red "✋ Too rich for a $300 pot" panel |
| q_grow | Tess (hyped) | "Win? Size up the next one. Lose? Fold. The Pot Tracker shows the come-up — three hundred to three thirty-three." | GROW: Pot Tracker stepping $300 → $333, win/loss rows |
| q_proof | Quantus (warm) | "And Proof Mode backtests it over years — and shows you the losses too. No hype. Just receipts." | SHARE: Proof Mode cards (wins AND losses), glossary expanding |
| q_cta | Tess (CTA, smile) | "Runs on your own machine. No account, no monthly fee. Get MAPLE58 on Gumroad." | Gumroad page / link card; QMM footer |
| q_signoff | Quantus (confident) | "Slow and alive beats fast and liquidated. Àṣẹ." | Both hosts; ÀṢẹ stamp |

---

## CUTDOWN (9:16, ~15s) — fast hook for cold scroll

| # | Speaker | Line (VO) | On-screen |
|---|---------|-----------|-----------|
| c_hook | Tess | "Most options tools promise you a Lambo. We won't." | Tess; hype reel glitches out |
| c_math | Quantus | "Most trades lose. We built a robot that loses small and survives." | Quantus; dashboard |
| c_what | Tess | "Finds plays you can afford. Tells you when to walk. Proves it with real backtests — losses and all." | fast GET/KEEP/PROOF cuts |
| c_cta | Quantus | "MAPLE58. On your machine, no monthly fee. Gumroad. Àṣẹ." | Gumroad card + ÀṢẹ stamp |

---

## Production pipeline
1. **VO (free, local):** Kokoro — `bake_ad_vo.py` → `vo/` (Quantus `am_liam`, Tess `af_heart`).
2. **Talking clips (Kling Ultra credits):** Kling Avatar 2.0 — feed locked image + per-line VO → lipsync.
   - Budget: hero ~36s + cutdown ~15s ≈ 51s talking. Pro ~8 cr/s ⇒ ~410 cr. Well inside 5k.
   - Quantus lines → host_LOCKED.jpg; Tess lines → tess_LOCKED.jpg.
3. **B-roll:** real MAPLE58 dashboard screen-caps (GET/KEEP/GROW/SHARE panels) — credit-free.
4. **Assemble:** ffmpeg — talking clip + screen B-roll picture-in-picture/cuts + bold captions + music + ÀṢẹ stamp.
5. **Verify → approve → upload** (Shorts/TikTok/Reels) with Gumroad link in caption + pinned comment.
