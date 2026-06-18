"""Synth MarketPulse Explainer #6 VO — XMR Part 4: the coin that actually made money.

Series Part 4. After NVDA (lost to hold) and BTC ("won" by hiding), Monero is
the genuine profit — AND we still show the asterisk (it trailed buy & hold).
Wraps the series honestly. Kokoro am_michael.

Real figures from app.run_proof('crypto','monero'), ~1y CoinGecko daily
(2025-06 -> 2026-06):
  net +7.51% ($10k -> $10,751) | gross +9.37% | cost drag 1.86% (~$166 fees+slip)
  profit factor 1.84 | 2 trades, 50% win (one -9.98% loser, one +20.36% winner held 96 bars)
  buy&hold +15.07% (beats_buy_hold = FALSE — made money but trailed holding)
  19 signals, 14 BUY, buy win-rate 78.6% | max drawdown 42.31%
  walk-forward: out-of-sample no trades, 1/4 positive folds
"""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo6"
OUT.mkdir(parents=True, exist_ok=True)

SECTIONS = {
    "S1": "Three videos, three gut-punches. Nvidia lost to just holding. Bitcoin only won by hiding in cash. People started saying I just hate my own tool. So today, finally, a coin where MarketPulse actually made money. Real profit. And then the asterisk I will never hide from you.",
    "S2": "Monero. Over the last year, the tool turned ten thousand dollars into about ten thousand seven hundred fifty. Up seven and a half percent, net, after every single fee. Profit factor one point eight four. For every dollar it lost, it made a dollar eighty-four. That's not a moral victory. That's money.",
    "S3": "How'd it do it? It nailed one trade. It bought Monero and held for about three months, riding it up twenty percent, ignoring all the noise in between. And the engine was genuinely bullish here. Fourteen buy signals, and seventy-nine percent of them were right. For once, the signal and the asset agreed.",
    "S4": "But here's the part I refuse to hide. Monero itself was up fifteen percent this year. So even when our tool won, just buying and holding won bigger. Seven and a half, versus fifteen. The tool made money. And it still trailed the asset.",
    "S5": "And that is not a bug. That's how trend-following breathes. It buys after the trend confirms, and it sells the moment that trend wobbles. Late in, early out. The exact discipline that saved you in the Bitcoin crash is the discipline that caps you in the Monero rally. Every rule that protects you somewhere costs you somewhere else. There is no free lunch.",
    "S6": "And stay honest about the size of this. Two trades. The entire profit is basically one good hold. Out of sample, it didn't even trade. And crypto's fees still bit, almost two full points gone to commissions and slippage. Two trades is a story. It is not proof.",
    "S7": "So here's the whole scorecard. Nvidia, lost to holding. Bitcoin, beat the market by hiding. Monero, finally made money, and still trailed holding. Four videos, and not one clean beats-the-market green light. That's not the tool failing. That's the tool telling you the truth: beating the market, consistently, is brutally hard. And anyone who says their little indicator just does it is selling you something.",
    "S8": "MarketPulse will never promise you it beats the market. It shows you exactly when it would have, when it wouldn't have, after fees, out of sample, on any coin or any stock you want. The honest tool, in a space full of liars. Link's in the description. Asha.",
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
