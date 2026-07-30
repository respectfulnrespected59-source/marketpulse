"""MarketPulse Quantus+Tess explainer VO baker.

Same GOLDEN method as ads_quantus_tess/bake_ad_vo.py: ONE continuous Kokoro read
per line (no splicing), voices am_liam = Quantus, af_heart = Tess. TTS-tuned text
(full spellings: "Maple fifty eight", spaced abbreviations, digits as words, "ah-shay").

Run FROM this folder (a stray ~/logging.py shadows stdlib logging if cwd=home):
  cd marketpulse/marketing && python bake_vo_explainer.py
  python bake_vo_explainer.py q_hook     # one line
Outputs 24k WAV into ./vo_explainer/.
"""
import os
import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SR = 24000
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "vo_explainer")

# (id, voice, text) — am_liam = Quantus, af_heart = Tess
LINES: list[tuple[str, str, str]] = [
    ("q_hook",   "am_liam",  "Most options trades lose. That's not fear. That's the math. Every tool selling you a green arrow knows it, and hides it."),
    ("t_free",   "af_heart", "Maple fifty eight doesn't hide it. And starting today? It's free. Name your price. Even zero."),
    ("q_what",   "am_liam",  "Maple fifty eight is an honest options dashboard that runs on your machine. No account. No A P I key. No monthly fee. Live option chains, implied volatility, and the Greeks, straight off the C B O E free feed."),
    ("t_what",   "af_heart", "It answers one question. What can I actually afford, and how do I lose small when I'm wrong?"),
    ("q_get",    "am_liam",  "Four jobs. Get: a nudge, a lean, never an order. Keep: the smallest probe that still tells you something, with a delta floor, so you stop buying dead lottery tickets."),
    ("t_grow",   "af_heart", "Grow: escalate only your winners. The Pot Tracker watches three hundred dollars become three thirty three, one disciplined probe at a time."),
    ("q_proof",  "am_liam",  "And share: prove it. Proof Mode backtests the exact signal over years, and shows the losses, not just the wins. Nvidia lost to just holding. Bitcoin only won by hiding in cash. Monero made money, and still trailed."),
    ("t_lesson", "af_heart", "No clean beat-the-market anywhere. That's not a bug. That's the receipt. The edge isn't prediction. It's survival."),
    ("q_close",  "am_liam",  "Slow and alive beats fast and liquidated. It costs nothing to find out if you can read it. The link is below. Nothing behind it but the tool, and the truth."),
    ("b_quantus", "am_liam", "Quantum Melanin Media."),
    ("b_tess",    "af_heart", "Voice and receipts for the unparented diaspora. ah-shay."),
]


def say(pipe: KPipeline, text: str, voice: str) -> np.ndarray:
    return np.concatenate([a for _, _, a in pipe(text.strip(), voice=voice)]).astype(np.float32)


def main() -> None:
    os.makedirs(OUTDIR, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None
    pipe = KPipeline(lang_code="a")
    total = 0.0
    for bid, voice, text in LINES:
        if only and bid != only:
            continue
        wav = say(pipe, text, voice)
        sf.write(os.path.join(OUTDIR, f"{bid}.wav"), wav, SR)
        secs = round(len(wav) / SR, 1)
        total += secs
        print(bid, voice, secs, "s")
    print("total", round(total, 1), "s")


if __name__ == "__main__":
    main()
