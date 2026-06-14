"""Synth MarketPulse Explainer #1 VO — Kokoro am_michael (QMM how-to voice)."""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    "S1": "Ninety percent of people who invest are gambling. They buy because a video told them to, and they sell because they're scared. The other ten percent? They read the same four things before every single entry. Today I'm gonna show you those four things, on one real trade, and by the end, you'll know which group you're actually in.",
    "S2": "April ninth. NVIDIA. A hundred and eighty-three dollars and ninety-one cents. The tool flags it: Strong Buy. Now, anybody can flash a green light. The question a serious trader asks is why. So let's read the board the way a pro reads it. Four factors. They all have to agree.",
    "S3": "First, momentum. R-S-I sitting in the mid fifties, coming up off the floor, not stretched. Stochastic crawling out of oversold. Translation: the selling pressure just got exhausted, and buyers are stepping back in. That's not a top. That's a turn.",
    "S4": "Second, M-A-C-D. The momentum lines just crossed back up. On its own? Noise. But stacked on that R-S-I turn, now you've got two independent signals saying the same thing. That's how confluence is built. Agreement from indicators that measure different things.",
    "S5": "Third, and this is the one amateurs skip. The fifty day average is above the two hundred. The golden cross. The big, slow tide is going up. You never want your short term entry fighting the long term tide. Here, they're rowing the same direction.",
    "S6": "Fourth, the higher timeframe. Zoom out to the weekly. Still up. So now the daily setup, the weekly trend, and the long term average are all aligned. Four green lights, measuring four different things, all pointing the same way. That is a Strong Buy. Not one indicator. Four in agreement.",
    "S7": "An advanced trader doesn't feel this. He reads it, sizes his risk, and acts, calm, because the logic did the deciding, not the emotion. That's the whole game.",
    "S8": "So what happened? Over the next thirty days, up nineteen percent. And here's the part nobody else will tell you: it doesn't win every time. Backtest two years of these signals and the strong buys land a little over half. That's it. Because trading isn't about being right every time. It's about a repeatable edge you can actually see, on every ticker, going back years.",
    "S9": "That's what MarketPulse does. The same four factor read, automated across crypto and stocks, plus Proof Mode, so you can run any ticker back through two years of history and see every signal it ever fired. Link's in the description. Stop gambling. Start reading the board. Asha.",
}

pipeline = KPipeline(lang_code="a")
durations = {}
for name, text in SECTIONS.items():
    segs = [audio for _, _, audio in pipeline(text, voice="am_michael")]
    wav = np.concatenate(segs)
    path = OUT / f"{name}.wav"
    sf.write(str(path), wav, 24000)
    durations[name] = round(len(wav) / 24000, 2)
    print(f"{name}: {durations[name]}s -> {path}")
print("TOTAL", round(sum(durations.values()), 1), "s")
print("DONE")
