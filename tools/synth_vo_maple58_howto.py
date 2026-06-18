"""Synth the MAPLE58 'What It Is & How To Run It' onboarding VO.

The hands-on cut: what the tool is, how it lands on your computer, a fast tour of
the screens, the four jobs, and the honest close. Kokoro am_michael, 24kHz.
Numbers spelled + file names voiced (run-dot-bat) for clean TTS. Honest framing:
most trades lose; survival is the skill. NOT advice. Mirrors synth_vo_maple58.py.
"""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo_maple58_howto"
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.wav"):   # clear stale clips so the assembler never grabs old names
    old.unlink()

SECTIONS = {
    "S1_hook": "You found a tool called MarketPulse — codename MAPLE58. Maybe you bought it, "
               "maybe you're deciding. Either way, here's the part nobody explains: exactly what "
               "it is, and exactly how to get it running on your own computer. No tech degree required.",
    "S2_whatitis": "MAPLE58 is an honest options research dashboard. It pulls live market data, reads "
                   "the technicals, and walks you through one question — what's a play I can actually "
                   "afford, and how do I lose small when I'm wrong. It runs on your machine. No account, "
                   "no subscription, and no data leaves your computer.",
    "S3_howtorun": "Here's how it lands on your computer. When you buy on Gumroad, you get one file — a "
                   "zip. Download it, then unzip it. That gives you a folder called MarketPulse. Inside "
                   "is everything: the program, and a launcher. On Windows, you double-click run-dot-bat. "
                   "On Mac or Linux, you run bash run-dot-sh. That's it. The launcher starts a tiny web "
                   "server on your own machine and opens the dashboard in your browser, at localhost, port "
                   "eight thousand. To stop it, just close the window. The whole thing is built so you don't "
                   "have to install anything fancy — you only need Python, which is free from python-dot-org. "
                   "On Windows, when you install it, just check the box that says add Python to PATH.",
    "S4_tour": "Open it up, and here's what you're looking at. Up top, tabs — Stocks, Options, your Pot, "
               "and Proof Mode. The Options tab is the heart of it, and it reads top to bottom like a "
               "funnel. First, the nudge — plain English, which way the data leans, framed as a read, never "
               "an order. The choice is always yours. Below that, the strategy card — the actual play, and "
               "what one contract costs in real dollars. Then the probe plan — the smallest first bet that "
               "still tells you something. Then The Read — a six-step breakdown of trend, coil, signal, "
               "volatility, the play, and the catch. And a glossary, so every number on screen has a plain "
               "definition.",
    "S5_fourjobs": "Everything maps to four jobs. GET — find a play you can afford. KEEP — be wrong cheaply, "
                   "with spend caps and a readability floor, so you're not buying dead lottery tickets. GROW "
                   "— escalate only your winners, tracked in the Pot. And SHARE — Proof Mode backtests the "
                   "exact signal over years, and shows you the losses too, not just the wins.",
    "S6_close": "Here's what it is not. It's not a money printer, and it will never tell you you're about to "
                "get rich. Most options trades lose — that's not a bug, that's the math, and this tool is "
                "built to keep you alive long enough to learn. Educational, not financial advice. Slow and "
                "alive beats fast and liquidated. That's MAPLE58.",
}

pipeline = KPipeline(lang_code="a")
durations = {}
for name, text in SECTIONS.items():
    segs = [audio for _, _, audio in pipeline(text, voice="am_michael")]
    wav = np.concatenate(segs)
    sf.write(str(OUT / f"{name}.wav"), wav, 24000)
    durations[name] = round(len(wav) / 24000, 2)
    print(f"{name}: {durations[name]}s")
print("TOTAL", round(sum(durations.values()), 1), "s ->", OUT)
print("DONE")
