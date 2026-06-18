"""Synth MarketPulse Explainer #3 VO — crypto winner: the tool called the top of Bitcoin. Kokoro am_michael."""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo3"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    "S1": "Everybody wants to know when to buy. The pros? They obsess over when to sell. Because in this game, the money you keep matters more than the money you make. Let me show you the day this tool called the top of Bitcoin.",
    "S2": "January fifteenth, twenty twenty-six. Bitcoin, ninety-seven thousand dollars. The timeline is euphoric. Everybody's buying, everybody's a genius. And MarketPulse does the opposite. It flashes Strong Sell.",
    "S3": "Why? The confluence flipped. R-S-I pinned up near seventy, deep in overbought. Momentum rolling over. Price stretched way above its bands. Every factor that screamed buy on the way up was now screaming exhaustion. The crowd was greedy. The signal was cold.",
    "S4": "So what happened? Thirty days later, Bitcoin was down twenty-nine percent. The diamond hands crowd watched a third of their stack evaporate. The people who respected that sell signal? They were already out, at ninety-seven K, with their gains intact.",
    "S5": "Here's the lesson. A sell signal isn't fear. It's discipline. The tool doesn't fall in love with a coin. It doesn't hope. It reads the board, and it acts. And calling tops is exactly where this thing shines. Across two years of Bitcoin, the sell signals hit nearly seventy percent.",
    "S6": "And Proof Mode lets you see all of it. Every sell it ever called, on any coin, two years back, with what happened next. No cherry picking. The receipts are right there on the screen.",
    "S7": "Because winning isn't just buying the bottom. It's having the discipline to sell the top. MarketPulse calls both, on any ticker, crypto or stocks. Link's in the description. Protect your gains. Asha.",
}

pipeline = KPipeline(lang_code="a")
durations = {}
for name, text in SECTIONS.items():
    segs = [audio for _, _, audio in pipeline(text, voice="am_michael")]
    wav = np.concatenate(segs)
    sf.write(str(OUT / f"{name}.wav"), wav, 24000)
    durations[name] = round(len(wav) / 24000, 2)
    print(f"{name}: {durations[name]}s")
print("TOTAL", round(sum(durations.values()), 1), "s")
print("DONE")
