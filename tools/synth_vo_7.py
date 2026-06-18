"""Synth MarketPulse Explainer #7 VO — UBER Part 5: the clean win (and the regime thesis).

Series Part 5 / finale. First asset where the tool BOTH made money AND beat
buy-and-hold. Crystallizes the whole series: match the tool to the market
regime (bull=lose, crash=defend, rally=trail, chop=WIN). Kokoro am_michael.

Real figures from app.run_proof('stock','UBER'), ~2y Yahoo daily
(2024-06 -> 2026-06):
  net +12.74% ($10k -> $11,274) | gross +13.17% | cost drag 0.43%
  buy&hold +2.56% (beats_buy_hold = TRUE, by ~10 pts) | profit factor 2.4
  4 trades, 50% win, max DD 10.43% | the winner: +24.33% held 142 bars (~7mo)
  37 signals, 22 BUY (63.6% win), directional 61.8%
  walk-forward: out-of-sample no trades (dodged UBER's recent -15%), beat hold 2/4, 3/4 positive
"""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo7"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    "S1": "Four videos. Not one clean win. Nvidia, it lost to holding. Bitcoin, it only won by hiding. Monero, it made money but trailed. So you've been patient. Today, finally, a clean one. The tool beat the market, real profit, and I'll show you the exact kind of market where that actually happens.",
    "S2": "Uber. The tool turned ten thousand dollars into eleven thousand two hundred seventy-four. Up twelve point seven percent, net, after fees. And buy and hold? Up just two and a half. It beat the market by ten points, with a profit factor of two point four, and a worst drawdown of only ten percent. Smooth. And real.",
    "S3": "Here's how. Uber spent two years going basically nowhere. Up a measly two and a half percent, chopping sideways. That's the graveyard for buy and hold. Your money just sits there, bored. But chop is where timing earns its keep. The tool took four trades, ate two small losers, then caught one clean run. It bought Uber and rode it seven months, up twenty-four percent.",
    "S4": "And this is the answer to all four other videos. Watch the pattern. Nvidia, a screaming bull, it lost, because timing just trips a rocket. Bitcoin, a crash, it survived in cash. Monero, a rally, it made money but trailed. Uber, sideways chop, it finally won, clean. The tool isn't good or bad. It's built for one specific job.",
    "S5": "A choppy, trendless market, where buy and hold dies of boredom. That's its weather. Hand it a rocket, it underperforms. Hand it a crash, it plays defense. Hand it chop, it shines. The skill was never finding a magic indicator. It's knowing which weather you're standing in, and whether your tool is built for it.",
    "S6": "Now the honesty tax, same as every video. Out of sample, in the most recent stretch, the tool didn't even trade. Though that is exactly why it dodged Uber's recent fifteen percent slide. And it beat buy and hold in two of four windows, not all four. Twelve point seven percent is real. But it's four trades. Encouraging. Not bulletproof.",
    "S7": "Five videos. One clean win, and now you know exactly when to expect it, and when not to. Nvidia, no. Bitcoin, defense. Monero, close. Uber, yes. That is not a tool that beats every market. It's a tool honest enough to tell you which market it's for. In a space full of people selling you a magic button, that is the whole edge.",
    "S8": "MarketPulse runs this same test, fees, slippage, out of sample, on any ticker you want. So you can read the weather yourself, before you risk a single dollar. Trade the math, not the hype. Link's in the description. Asha.",
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
