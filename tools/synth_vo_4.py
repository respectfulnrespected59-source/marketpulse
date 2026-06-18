"""Synth MarketPulse Explainer #4 VO — NVDA Part 2: the honest stress test.

Sequel to explainer #1 (the NVDA "4 things pros check" video). This one runs
the new realistic backtest (fees + slippage) and the walk-forward out-of-sample
test on the SAME stock, and shows every ugly number. Kokoro am_michael.

Every figure below is real, pulled from app.run_proof('stock','NVDA') over
~2y of Yahoo daily closes (2024-06 -> 2026-06):
  signal 30d hit-rate 56% | actual trades won 2/7 (28.6%)
  net strategy -10.15% ($10k->$8,985) vs buy&hold +63.19% | cost drag 0.6%
  profit factor 0.68 | worst drawdown -24.82% | avg win +14% avg loss -7.1%
  walk-forward test -2.8% vs hold +15.8% | beat hold in 0 of 4 folds
"""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo4"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    "S1": "Part one, I showed you the four things our tool checks before it ever calls a buy, using Nvidia as the example. And a lot of you asked the only question that matters: okay, but does it actually make money? So I did something most trading channels will never do. I tried to break my own tool. Same stock. And I'm gonna show you every number, especially the ugly ones.",
    "S2": "First, the number that looks amazing. Over two years of Nvidia, our Strong Buy signals were right fifty-six percent of the time over the next month. Fifty-six percent. On FinTok, that's where the video ends and somebody sells you a course. But a win rate is a vanity metric. Watch what happens when you actually trade it.",
    "S3": "Because I added the stuff backtests love to hide. Real trading costs. Every entry and every exit pays the spread and the slippage. On Nvidia that drag was tiny, about half a percent. So remember that. The costs are not the villain in this story. The strategy is.",
    "S4": "Here's the number that actually matters. Trading every signal, after costs, turned ten thousand dollars into about eight thousand nine hundred. Down ten percent over two years. And Nvidia, that same stretch? If you had just bought it and done absolutely nothing, you'd be up sixty-three percent. Our clever signals lost to a guy who fell asleep.",
    "S5": "How is that even possible at a fifty-six percent hit rate? Because the signal looking right and the trade making money are two different things. When you actually traded it, entry to exit, only two of seven round trips made a dime. The average winner was up fourteen percent, but one drawdown hit twenty-five. Profit factor, zero point six eight. Anything under one means you bleed. Your losers were eating your winners alive.",
    "S6": "Then the real test. The walk-forward. You train on the old data, then you test on months the strategy has never seen. No cheating. Out of sample on Nvidia, the strategy was down three percent, while just holding was up almost sixteen. Four separate time windows. It beat buy and hold in zero of them. Zero.",
    "S7": "So why would I show you my own tool getting smoked? Because this, right here, is the product. Anybody can cherry-pick a winning trade. Ours runs the fees, the slippage, and an out-of-sample test, and then it puts the ugly truth right on your screen. The lesson Nvidia just taught us is the one nobody sells: a high win rate means nothing if you can't beat buy and hold. Sometimes the smartest trade is no trade.",
    "S8": "MarketPulse runs this exact honest stress test on any ticker, two years back. Winners and losers, after costs, out of sample. It will not promise you a Lambo. It will tell you the truth. Trade the math, not the hype. Link's in the description. Asha.",
}

pipeline = KPipeline(lang_code="a")
durations = {}
for name, text in SECTIONS.items():
    segs = [audio for _, _, audio in pipeline(text, voice="am_michael")]
    wav = np.concatenate(segs)
    path = OUT / f"{name}.wav"
    sf.write(str(path), wav, 24000)
    durations[name] = round(len(wav) / 24000, 2)
    print(f"{name}: {durations[name]}s")
print("TOTAL", round(sum(durations.values()), 1), "s")
print("DONE")
