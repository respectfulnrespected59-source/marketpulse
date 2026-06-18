"""Stitch MarketPulse Explainer #6 — XMR Part 4: the coin that actually made money.

Same PIL-baked-caption + ffmpeg Ken-Burns pipeline as build_explainer_5.py,
pointed at vo6/ VO, fresh Monero Proof Mode screenshots in broll6/ (the real
GREEN +7.51% net vs +15.78% hold + walk-forward cards), and an SCFL bed.
"""
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "marketing"
BROLL6, BROLL1, VO, WORK = ROOT / "broll6", ROOT / "broll", ROOT / "vo6", ROOT / "_work6"
WORK.mkdir(exist_ok=True)
OUT = ROOT / "MarketPulse_Explainer_06_XMR_Win.mp4"
MUSIC = Path.home() / "Downloads" / "SCFL10-2.mp3"

W, H = 1920, 1080
BG = (10, 13, 18)
GOLD, GREEN, RED, DIM = (217, 176, 97), (47, 209, 128), (255, 93, 108), (138, 153, 171)
FONT = "C:/Windows/Fonts/arialbd.ttf"
FONT_R = "C:/Windows/Fonts/arial.ttf"


def font(p, s):
    return ImageFont.truetype(p, s)


def wav_dur(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()


def resolve(name):
    p = BROLL6 / name
    return p if p.exists() else BROLL1 / name


def frame(img_name, caption, sub, *, title=False, accent=GOLD):
    canvas = Image.new("RGB", (W, H), BG)
    img = Image.open(resolve(img_name)).convert("RGB")
    iw, ih = img.size
    if (iw, ih) == (W, H):
        canvas.paste(img, (0, 0))
    else:
        bw, bh = 1640, 760
        s = min(bw / iw, bh / ih)
        nw, nh = int(iw * s), int(ih * s)
        img = img.resize((nw, nh), Image.LANCZOS)
        x, y = (W - nw) // 2, (H - nh) // 2 - 40
        bd = Image.new("RGB", (nw + 4, nh + 4), (35, 47, 61))
        bd.paste(img, (2, 2))
        canvas.paste(bd, (x - 2, y - 2))

    d = ImageDraw.Draw(canvas, "RGBA")
    d.rectangle([0, H - 230, W, H], fill=(6, 8, 11, 205))
    if title:
        d.text((W / 2, H / 2 - 70), "It actually made money.", font=font(FONT, 88), fill=GREEN, anchor="mm")
        d.text((W / 2, H / 2 + 30), "(with one asterisk.)", font=font(FONT, 80), fill=GOLD, anchor="mm")
        d.text((W / 2, H / 2 + 150), caption, font=font(FONT_R, 40), fill=DIM, anchor="mm")
    else:
        d.text((80, H - 170), caption, font=font(FONT, 54), fill=(232, 238, 245))
        if sub:
            d.text((80, H - 96), sub, font=font(FONT_R, 36), fill=accent)
    return canvas


# (vo, img, caption, sub, kwargs)
BEATS = [
    ("S1", "B_stocks.png", "XMR · Part 4 · the honest win", "", dict(title=True)),
    ("S2", "N_stats.png", "+7.5% net — REAL profit", "$10k became $10,751 · profit factor 1.84", dict(accent=GREEN)),
    ("S3", "N_chart.png", "One great trade: +20%, held ~3 months", "14 buy signals, 79% of them right", dict(accent=GREEN)),
    ("S4", "N_stats.png", "...but Monero itself was up ~16%", "it made money - and STILL trailed just holding", dict(accent=RED)),
    ("S5", "N_stats.png", "That's trend-following: late in, early out", "what saved you in the BTC crash caps you in a rally", dict(accent=DIM)),
    ("S6", "N_stats.png", "Only 2 trades. Fees took ~2 points.", "a story, not proof - out-of-sample it didn't trade", dict(accent=RED)),
    ("S7", "N_stats.png", "NVDA lost · BTC hid · XMR trailed", "4 videos, not one clean 'beats the market'", dict(accent=GOLD)),
    ("S8", "B_stocks.png", "Get MarketPulse - link below", "the honest tool in a space full of liars - a Quantum Melanin Media tool", dict(accent=GOLD)),
]


def build_beat(vo, img, caption, sub, kw):
    dur = wav_dur(VO / f"{vo}.wav")
    fr = frame(img, caption, sub, **kw)
    fpng = WORK / f"{vo}.png"
    fr.save(fpng)
    out = WORK / f"{vo}.mp4"
    df = max(1, int(dur * 30))
    vf = (f"scale={W}:{H},zoompan=z='min(zoom+0.0006,1.08)':d={df}"
          f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=30,format=yuv420p")
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(fpng), "-i", str(VO / f"{vo}.wav"),
        "-vf", vf, "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "medium",
        "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    return out, dur


def main():
    clips, total = [], 0.0
    for vo, img, cap, sub, kw in BEATS:
        out, dur = build_beat(vo, img, cap, sub, kw)
        clips.append(out)
        total += dur
        print(f"{vo}: {dur:.1f}s")
    listf = WORK / "concat.txt"
    listf.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    body = WORK / "body.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-c", "copy", str(body)], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(body), "-stream_loop", "-1", "-i", str(MUSIC),
        "-filter_complex", "[1:a]volume=0.09[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(OUT),
    ], check=True, capture_output=True)
    print(f"\nDONE  {total:.1f}s  ->  {OUT}")


if __name__ == "__main__":
    main()
