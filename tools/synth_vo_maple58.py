"""Synth the MAPLE58 explainer VO (v2) — longer 5-10min cut, no personal lore.

MAPLE = MArket PuLsE (the contraction). A free, honest options research tool.
Four jobs: GET · KEEP · GROW · SHARE. Kokoro am_michael, 24kHz. Numbers spelled
for TTS. Honest framing: most trades lose; survival is the skill. NOT advice.
"""
import numpy as np
import soundfile as sf
from pathlib import Path
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "marketing" / "vo_maple58"
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.wav"):   # clear stale clips so the assembler never grabs old names
    old.unlink()

SECTIONS = {
    "S1_hook": "This is MAPLE58 — a free, honest options research tool. It's got one rule it never breaks: "
               "it will not lie to you about getting rich. Instead, it does four quiet jobs. It helps you GET "
               "a play you can actually afford. KEEP your money when you're wrong. GROW it slowly. And SHARE "
               "the whole method, so you're never trading blind. Let me show you all of it.",
    "S2_name": "Quick note on the name. MAPLE is just Market Pulse, squeezed together. Ma — ple. And everything "
               "you're about to see is built on one idea: most trades lose. So survival is the real skill.",
    "S3_tour": "First, the layout, so nothing's confusing. Up top, six tabs. Crypto and Stocks are live signal "
               "grids. Each card gives you the signal — from strong buy down to sell — the RSI, the moving "
               "averages, and the TTM squeeze. The Options tab is the heart of the tool, and that's where we'll "
               "spend most of our time. Watchlist holds your saved names. The Pot is your money tracker. And Proof "
               "runs honest backtests. Now watch an Options page, top to bottom, because it's built to read like a "
               "story. First, it tells you which way the data leans. Then it lays out a play. Then it sizes that "
               "play to your pot. Then it walks you through how to think about it, step by step. Then a glossary "
               "defines every term. And at the very bottom, the full chain — every strike, in real dollars.",
    "S4_get": "Superpower one. GET — find a play you can actually afford. It starts with the nudge. This banner "
              "reads the data and tells you which way a seasoned trader would lean. Bullish. Bearish. Or, a move "
              "is coming but the direction isn't clear. It's a lean, not an order — the decision is always yours. "
              "Next, the squeeze. When a stock's volatility coils up tight, a breakout is loading. Watch the bands "
              "squeeze in, then fire. The expected-move cone shows how far a normal week actually reaches, so "
              "you're not chasing a sixty-percent miracle. And finally, the scanner. One button sweeps a basket of "
              "volatile, low-dollar stocks and crypto, and tells you which ones have a setup that fits your pot — "
              "and which ones to skip.",
    "S5_keep": "Superpower two. KEEP — be wrong cheaply, because most of the time, you will be. This is where the "
               "tool earns its keep. A probe is a small first bet that just asks, am I right? But here's the trap "
               "beginners fall into. They buy the cheapest option on the board, way out of the money, and it never "
               "moves. A dead lottery ticket. So MAPLE58 uses a formula. Watch this curve. As you go further out, "
               "the option gets cheaper — but its delta, how much it actually reacts to the stock, collapses. "
               "Below a delta of zero point two five, it's a lottery, not a read. So the formula finds the cheapest "
               "option that can still tell you something real. Then it checks your pot. If that probe costs more "
               "than twenty percent of your money, it says one word. Walk. And every price is in real dollars. Not "
               "a dollar seventy. Six hundred fifty dollars — because a contract is a hundred shares, and beginners "
               "blow up not knowing that.",
    "S6_grow": "Superpower three. GROW — and this is the part you can finally see. The method is three steps. "
               "Probe. Read. Escalate. You place a small probe. You read it — is it working, or dying? If it's "
               "working, you escalate: you add to the winner with a bigger, closer-to-the-money position. If it's "
               "dying, you flip, or you fold. The tool builds the whole plan for you. A debit spread when there's a "
               "clear direction. A strangle when a move is coming but the direction isn't. These diagrams show "
               "exactly what each trade does, and where it breaks even. And then, the Pot Tracker. You log every "
               "probe, win or lose, and it shows your pot moving. Three hundred becomes three thirty-three, one "
               "disciplined probe at a time. But watch the red line. That's the trader who revenge-sizes, doubling "
               "down to get even. That line goes to zero. Discipline is the entire come-up.",
    "S7_example": "Let me put it all together on one name. The tool flags a stock. The nudge says bullish. The "
                  "squeeze is firing that way. So you go to size it. The probe formula picks a strike that's cheap "
                  "but still reacts, and checks it against your three-hundred-dollar pot. If it fits, you place it — "
                  "maybe a sixty-dollar call. Now you read it. It climbs. So you escalate: two bigger, closer "
                  "positions, on a confirmed direction, capped so you never risk more than the plan. And you log all "
                  "of it in the Pot Tracker. Win or lose, it's defined risk, sized small, and recorded. That's the "
                  "whole loop — and the tool held your hand through every step, without ever telling you what to do.",
    "S8_share": "Superpower four — and the one that matters most. SHARE. Proof Mode runs the exact signal backward "
                "over years of real history, and shows you every single trade it would have made. The winners, and "
                "the losers, net of fees. No cherry-picking. The glossary explains every term on the screen, so "
                "nothing is a mystery. And the whole thing stays free — for everybody who never had somebody at the "
                "table to show them how this actually works. That's the why.",
    "S9_close": "That's MAPLE58. Not a money printer. An honest tool that finds what you can afford, keeps you in "
                "the game, grows it slowly, and shares the method. Slow and alive beats fast and liquidated. "
                "Everything's free. The link is in the description. Tap in.",
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
