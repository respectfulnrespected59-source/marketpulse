"""Synth MarketPulse Explainer #2 VO — honest 'loser' breakdown (META). Kokoro am_michael."""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo2"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    "S1": "Every trading channel shows you the wins. The Lambos, the green screenshots. I'm gonna do the opposite. I'm gonna show you a trade my own tool got dead wrong. Because this, right here, is the lesson that actually keeps your account alive.",
    "S2": "February twenty-fifth, twenty twenty-five. Meta. Six hundred fifty-seven dollars. And MarketPulse lights up Strong Buy. Same four factor read I showed you last time. Momentum, trend, the works. All aligned. A textbook signal.",
    "S3": "So what happened? Thirty days later, Meta was down twenty-two percent. The signal was wrong. Flat wrong. Now, most people, right here, rage quit. They blame the tool, they swear off trading. And they miss the entire point.",
    "S4": "Here's the truth nobody sells you: no signal is a crystal ball. These strong buys hit a little over half the time. That means almost half the time, they don't. If you need every trade to win, you already lost. The pros don't avoid losers. They survive them.",
    "S5": "And surviving is a skill. One: position sizing. You never bet the farm on a single read, so one bad trade is a scratch, not a knockout. Two: the stop loss. A disciplined trader was out of that Meta trade down eight percent, not twenty-two. The signal gets you in. Your risk plan gets you out.",
    "S6": "Because trading isn't about that one trade. It's about a hundred trades. A slight edge, sized right, with losses cut short, that's what compounds. The winners take care of themselves. Your only job is to make the losers small.",
    "S7": "And this is why Proof Mode matters. It does not hide the losers. Worst drawdown, right there on the screen, minus twenty-two percent. A tool that only shows you green is lying to you. Real edge looks honest.",
    "S8": "So if anybody sells you a signal that never loses, run. MarketPulse shows you every signal, winners and losers, on any ticker, two years back. Trade the math, not the hype. Link's in the description. Asha.",
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
