"""Stitch MarketPulse Explainer #4 — NVDA Part 2: the honest stress test.

Same PIL-baked-caption + ffmpeg Ken-Burns pipeline as build_explainer.py,
pointed at the vo4/ VO, fresh NVDA Proof Mode screenshots in broll4/ (the new
strategy + walk-forward cards, with the real -10% vs +63% numbers on screen),
and the SCFL bed used on the part-1 NVDA video for continuity.
"""
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "marketing"
BROLL4, BROLL1, VO, WORK = ROOT / "broll4", ROOT / "broll", ROOT / "vo4", ROOT / "_work4"
WORK.mkdir(exist_ok=True)
OUT = ROOT / "MarketPulse_Explainer_04_NVDA_StressTest.mp4"
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
    p = BROLL4 / name
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
        d.text((W / 2, H / 2 - 70), "We tried to break", font=font(FONT, 92), fill=(232, 238, 245), anchor="mm")
        d.text((W / 2, H / 2 + 30), "our own tool", font=font(FONT, 92), fill=RED, anchor="mm")
        d.text((W / 2, H / 2 + 150), caption, font=font(FONT_R, 40), fill=DIM, anchor="mm")
    else:
        d.text((80, H - 170), caption, font=font(FONT, 56), fill=(232, 238, 245))
        if sub:
            d.text((80, H - 96), sub, font=font(FONT_R, 36), fill=accent)
    return canvas


# (vo, img, caption, sub, kwargs)
BEATS = [
    ("S1", "B_stocks.png", "NVDA · Part 2 · the honest stress test", "", dict(title=True)),
    ("S2", "N_stats.png", "Signal hit-rate: 56%", "looks amazing... right?", dict(accent=GREEN)),
    ("S3", "N_stats.png", "We added real fees + slippage", "cost drag: just 0.6% - not the villain here", dict(accent=DIM)),
    ("S4", "N_stats.png", "Traded -10%   vs   just Holding +63%", "the clever signals lost to doing nothing", dict(accent=RED)),
    ("S5", "N_chart.png", "Only 2 of 7 trades won", "profit factor 0.68 - the losers ate the winners", dict(accent=RED)),
    ("S6", "N_stats.png", "Out-of-sample: -2.8%  vs  +15.8% hold", "beat buy & hold in 0 of 4 time windows", dict(accent=RED)),
    ("S7", "N_stats.png", "The ugly truth, right on your screen", "fees + slippage + an out-of-sample test", dict(accent=GREEN)),
    ("S8", "B_stocks.png", "Get MarketPulse - link below", "honest stress test on any ticker - a Quantum Melanin Media tool", dict(accent=GOLD)),
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
