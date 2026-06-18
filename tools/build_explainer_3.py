"""Stitch MarketPulse Explainer #3 (crypto winner: tool called the top of Bitcoin).
Framed B-roll + vo3 VO + 'It Is What It Is' bed. Same pipeline as build_explainer_2.py.
"""
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "marketing"
BROLL3, BROLL1, VO, WORK = ROOT / "broll3", ROOT / "broll", ROOT / "vo3", ROOT / "_work3"
WORK.mkdir(exist_ok=True)
OUT = ROOT / "MarketPulse_Explainer_03_BTC.mp4"
MUSIC = Path.home() / "Downloads" / "IT IS WHAT IT S WHEW.mp3"

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
    p = BROLL3 / name
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
        d.text((W / 2, H / 2 - 55), "Sell", font=font(FONT, 120), fill=(232, 238, 245), anchor="rm")
        d.text((W / 2, H / 2 - 55), " the top.", font=font(FONT, 120), fill=GREEN, anchor="lm")
        d.text((W / 2, H / 2 + 70), caption, font=font(FONT_R, 42), fill=DIM, anchor="mm")
    else:
        d.text((80, H - 170), caption, font=font(FONT, 58), fill=(232, 238, 245))
        if sub:
            d.text((80, H - 96), sub, font=font(FONT_R, 38), fill=accent)
    return canvas


# (vo, img, caption, sub, kwargs)
BEATS = [
    ("S1", "X_crypto.png", "the call most people never make", "", dict(title=True)),
    ("S2", "B_proof_full.png", "BITCOIN  -  $97,000  -  STRONG SELL", "Jan 2026 - peak euphoria", dict(accent=RED)),
    ("S3", "B_chart.png", "Overbought. Momentum rolling over.", "the confluence flipped", dict(accent=RED)),
    ("S4", "B_stats.png", "30 days later:  -29%", "the tool had you OUT at $97K", dict(accent=GREEN)),
    ("S5", "B_proof_full.png", "A sell signal is DISCIPLINE", "BTC sell signals hit ~69% over 2 years", dict(accent=GOLD)),
    ("S6", "B_events.png", "Every call, on the record", "no cherry-picking - 2 years back", dict(accent=GREEN)),
    ("S7", "X_crypto.png", "Get MarketPulse - link below", "buy the bottom AND sell the top - a Quantum Melanin Media tool", dict(accent=GOLD)),
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
