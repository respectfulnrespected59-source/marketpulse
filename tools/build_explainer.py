"""Stitch MarketPulse Explainer #1: framed B-roll + Kokoro VO + ducked music.

Captions are baked into 1920x1080 frames with PIL (no ffmpeg drawtext escaping),
then each beat is a Ken-Burns zoom synced to its VO segment. Beats are concatenated
and a Lion of Mali bed is mixed under everything.
"""
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "marketing"
BROLL, VO, WORK = ROOT / "broll", ROOT / "vo", ROOT / "_work"
WORK.mkdir(exist_ok=True)
OUT = ROOT / "MarketPulse_Explainer_01_NVDA.mp4"
MUSIC = Path.home() / "Downloads" / "lion_of_mali_audio" / "battle_of_kirina.mp3"

W, H = 1920, 1080
BG = (10, 13, 18)
GOLD, GREEN, DIM = (217, 176, 97), (47, 209, 128), (138, 153, 171)
FONT = "C:/Windows/Fonts/arialbd.ttf"
FONT_R = "C:/Windows/Fonts/arial.ttf"


def font(path, size):
    return ImageFont.truetype(path, size)


def wav_dur(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()


def frame(img_name, caption, sub, *, title=False, accent=GOLD):
    """Compose a 1920x1080 frame: B-roll image + baked caption."""
    canvas = Image.new("RGB", (W, H), BG)
    img = Image.open(BROLL / img_name).convert("RGB")
    iw, ih = img.size
    if (iw, ih) == (W, H):
        canvas.paste(img, (0, 0))
    else:  # crop/element — scale to fit a centered box with margin
        box_w, box_h = 1640, 760
        scale = min(box_w / iw, box_h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img = img.resize((nw, nh), Image.LANCZOS)
        x, y = (W - nw) // 2, (H - nh) // 2 - 40
        bordered = Image.new("RGB", (nw + 4, nh + 4), (35, 47, 61))
        bordered.paste(img, (2, 2))
        canvas.paste(bordered, (x - 2, y - 2))

    d = ImageDraw.Draw(canvas, "RGBA")
    d.rectangle([0, H - 230, W, H], fill=(6, 8, 11, 200))  # bottom scrim

    if title:
        f1, f2 = font(FONT, 132), font(FONT_R, 46)
        d.text((W / 2, H / 2 - 60), "Market", font=f1, fill=(232, 238, 245), anchor="rm")
        d.text((W / 2, H / 2 - 60), "Pulse", font=f1, fill=GOLD, anchor="lm")
        d.text((W / 2, H / 2 + 60), caption, font=f2, fill=DIM, anchor="mm")
    else:
        if sub and sub.startswith("#"):  # factor index marker
            d.text((80, H - 170), sub, font=font(FONT, 40), fill=accent)
            d.text((150, H - 175), caption, font=font(FONT, 58), fill=(232, 238, 245))
        else:
            d.text((80, H - 170), caption, font=font(FONT, 60), fill=(232, 238, 245))
            if sub:
                d.text((80, H - 96), sub, font=font(FONT_R, 38), fill=accent)
    return canvas


# beat: (vo, img, caption, sub, kwargs)
BEATS = [
    ("S1", "A_crypto.png", "Read the board like a pro", "", dict(title=True)),
    ("S2", "D_proof_full.png", "NVDA  -  $183.91  -  STRONG BUY", "April 9 - why?", {}),
    ("S3", "C_card.png", "MOMENTUM", "#1", dict(accent=GREEN)),
    ("S4", "C_card.png", "MACD", "#2", dict(accent=GREEN)),
    ("S5", "E_chart.png", "GOLDEN CROSS (50 / 200)", "#3", dict(accent=GOLD)),
    ("S6", "D_proof_full.png", "HIGHER TIMEFRAME", "#4", dict(accent=GOLD)),
    ("S7", "C_card.png", "Four green lights. Logic decides - not emotion.", "", {}),
    ("S8", "F_events.png", "NVDA  ->  +19.36% in 30 days", "Educational only - not financial advice - past performance != future results", dict(accent=GREEN)),
    ("S9", "B_stocks.png", "Get MarketPulse - link below", "Crypto + stocks - Proof Mode - A Quantum Melanin Media tool", dict(accent=GOLD)),
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
