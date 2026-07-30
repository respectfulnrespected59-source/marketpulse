"""MAPLE58 ad-pack VO baker (Quantus am_liam + Tess af_heart).

GOLDEN method (matches qmm-cartoon-host/bake_vo.py): ONE continuous Kokoro read per
line, no splicing/effects, so delivery breathes on its own punctuation pauses.
Full spellings (Kokoro gotcha): "Maple fifty eight", "ah-shay", digits as words.

Usage:
  python bake_ad_vo.py            # bake every line to vo/<id>.wav
  python bake_ad_vo.py q_math     # bake one line
Outputs 24k WAV into ./vo/.
"""
import os
import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SR = 24000
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "vo")

# (id, voice, text) — voice am_liam = Quantus, af_heart = Tess
LINES: list[tuple[str, str, str]] = [
    # ---- HERO ----
    ("q_intro",   "af_heart", "Most options tools promise you a Lambo. We're not gonna do that."),
    ("q_math",    "am_liam",  "Real talk. Most options trades lose. That's the math. So we built a little robot that loses small and survives."),
    ("q_get",     "af_heart", "Maple fifty eight finds plays you can actually afford. The cheapest usable probe, not the four thousand dollar lottery."),
    ("q_keep",    "am_liam",  "It shows the price in real dollars. Six hundred fifty, not one seventy nine. And it tells you when a play's too rich. Walk."),
    ("q_grow",    "af_heart", "Win? Size up the next one. Lose? Fold. The Pot Tracker shows the come up. Three hundred, to three thirty three."),
    ("q_proof",   "am_liam",  "And Proof Mode backtests it over years. And shows you the losses too. No hype. Just receipts."),
    ("q_cta",     "af_heart", "Runs on your own machine. No account, no monthly fee. Get Maple fifty eight on Gumroad."),
    ("q_signoff", "am_liam",  "Slow and alive beats fast and liquidated. ah-shay."),
    # ---- CUTDOWN ----
    ("c_hook",    "af_heart", "Most options tools promise you a Lambo. We won't."),
    ("c_math",    "am_liam",  "Most trades lose. We built a robot that loses small and survives."),
    ("c_what",    "af_heart", "Finds plays you can afford. Tells you when to walk. Proves it with real backtests. Losses and all."),
    ("c_cta",     "am_liam",  "Maple fifty eight. On your machine, no monthly fee. Gumroad. ah-shay."),
]


def say(pipe: KPipeline, text: str, voice: str) -> np.ndarray:
    return np.concatenate([a for _, _, a in pipe(text.strip(), voice=voice)]).astype(np.float32)


def main() -> None:
    os.makedirs(OUTDIR, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None
    pipe = KPipeline(lang_code="a")
    for bid, voice, text in LINES:
        if only and bid != only:
            continue
        wav = say(pipe, text, voice)
        sf.write(os.path.join(OUTDIR, f"{bid}.wav"), wav, SR)
        print(bid, voice, round(len(wav) / SR, 1), "s")


if __name__ == "__main__":
    main()
