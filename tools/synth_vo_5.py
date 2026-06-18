"""Synth MarketPulse Explainer #5 VO — BTC Part 3: the "beating the market" trap.

Series Part 3 (after #1 NVDA basics, #4 NVDA stress test). On Bitcoin the tool
actually BEAT buy-and-hold... and this video debunks our own "win." Honesty in
both directions. Kokoro am_michael.

Real figures from app.run_proof('crypto','bitcoin'), ~1y CoinGecko daily
(2025-06 -> 2026-06):
  buy&hold -42.69% | strategy net -7.3% (beat hold by ~35 pts, but BOTH down)
  only 1 trade (a -7.45% loser) then sat in cash | crypto round-trip cost 0.9%
  fees $45.73 + slippage $36.53 (~$82 on one trade) | cost drag 0.8%
  19 signals (15 SELL, sell win 66.7%; 2 BUY, both lost)
  walk-forward: out-of-sample mostly no trades, 0 winning folds, beat hold 3/4
"""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo5"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    "S1": "Part two, I showed you our own tool getting beaten by just holding Nvidia. Brutal. So you'd think Bitcoin, where the tool actually beat buy and hold, would be the victory lap. It's not. I'm gonna show you why beating the market can be the most dangerous lie of all.",
    "S2": "The last year of Bitcoin was a bloodbath. If you bought and held, you're down about forty-three percent. Almost half your money, gone. Our tool, over that exact same year? Down seven percent. So technically, mathematically, the tool crushed buy and hold by thirty-five points.",
    "S3": "And this is exactly where most channels cut the highlight reel. Our A.I. beat the market by thirty-five percent! Course link below. But stop. Down seven and down forty-three are both down. Beating a benchmark that fell off a cliff isn't winning. It's losing less. You can't eat relative performance. Down is down.",
    "S4": "So how did it lose less? Not genius timing. It basically refused to play. In a full year, the strategy made exactly one trade. One. A seven percent loser. And then it sat in cash while Bitcoin bled out. The tool's edge here wasn't picking winners. It was staying out of a knife fight.",
    "S5": "And on crypto, playing costs you more. The fees and slippage that barely registered on Nvidia? On that one Bitcoin round trip, they ate about eighty dollars. Almost a full percent, gone, on a single trade. Crypto is the casino with the highest table fees. Every extra trade is just the house taking its cut.",
    "S6": "Now the most important number in this whole video. One. One trade. You cannot prove a strategy on one trade. A coin flip goes your way once, that proves nothing. That's why the walk-forward matters. Out of sample, the tool mostly just sat there. Zero winning windows. Beating the market with no trades isn't a strategy. It's an absence.",
    "S7": "So here's the honest scorecard. On Nvidia, it lost to holding. On Bitcoin, it beat holding by hiding in cash. Neither one is a green light. And that, right there, showing you both and refusing to spin either, is the entire point. A tool that only shows you the framing that sells is lying to you. Ours shows you the asterisk on its own win.",
    "S8": "MarketPulse runs this same honest stress test on any coin or any stock. After fees, after slippage, out of sample. It will not sell you a fantasy. It'll show you the asterisks. Trade the math, not the hype. Link's in the description. Asha.",
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
