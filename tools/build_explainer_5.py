"""Stitch MarketPulse Explainer #5 — BTC Part 3: the "beating the market" trap.

Same PIL-baked-caption + ffmpeg Ken-Burns pipeline as build_explainer_4.py,
pointed at vo5/ VO, fresh Bitcoin Proof Mode screenshots in broll5/ (the real
-7.3% vs -42.63% hold + walk-forward cards on screen), and an SCFL bed for
series sonic continuity.
"""
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "marketing"
BROLL5, BROLL1, VO, WORK = ROOT / "broll5", ROOT / "broll", ROOT / "vo5", ROOT / "_work5"
WORK.mkdir(exist_ok=True)
OUT = ROOT / "MarketPulse_Explainer_05_BTC_StressTest.mp4"
MUSIC = Path.home() / "Downloads" / "SCFL8.1.mp3"

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
    p = BROLL5 / name
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
        d.text((W / 2, H / 2 - 70), "We 'beat' Bitcoin.", font=font(FONT, 92), fill=(232, 238, 245), anchor="mm")
        d.text((W / 2, H / 2 + 30), "Here's the catch.", font=font(FONT, 92), fill=RED, anchor="mm")
        d.text((W / 2, H / 2 + 150), caption, font=font(FONT_R, 40), fill=DIM, anchor="mm")
    else:
        d.text((80, H - 170), caption, font=font(FONT, 54), fill=(232, 238, 245))
        if sub:
            d.text((80, H - 96), sub, font=font(FONT_R, 36), fill=accent)
    return canvas


# (vo, img, caption, sub, kwargs)
BEATS = [
    ("S1", "B_stocks.png", "BTC · Part 3 · why it's not the win it looks like", "", dict(title=True)),
    ("S2", "N_stats.png", "Hold -43%   vs   our tool -7%", "we 'beat the market' by 35 points...", dict(accent=GREEN)),
    ("S3", "N_stats.png", "Down 7% and down 43%", "are BOTH down - you can't eat 'relative'", dict(accent=RED)),
    ("S4", "N_chart.png", "It made exactly 1 trade all year", "then sat in cash while BTC bled out", dict(accent=DIM)),
    ("S5", "N_stats.png", "On crypto, the fees actually bite", "~$80 gone on one round trip - that's 0.9%", dict(accent=RED)),
    ("S6", "N_stats.png", "1 trade proves NOTHING", "out-of-sample: 0 winning windows", dict(accent=RED)),
    ("S7", "N_stats.png", "NVDA: lost to holding.  BTC: hid in cash.", "neither is a green light - we show you both", dict(accent=GREEN)),
    ("S8", "B_stocks.png", "Get MarketPulse - link below", "honest stress test on any coin or stock - a Quantum Melanin Media tool", dict(accent=GOLD)),
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
