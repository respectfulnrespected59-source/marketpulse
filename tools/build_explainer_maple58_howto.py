"""Assemble the MAPLE58 'What It Is & How To Run It' onboarding explainer.

Hands-on cut: what it is -> how it lands on your computer (install STEP CARDS,
since the OS unzip/double-click isn't browser-capturable) -> a fast tour of the
real screens (close-ups held still & fit-to-frame) -> the four jobs -> honest
close. VO-paced, ducked lofi bed with an outro swell. 1920x1080. NOT advice.

Mirrors build_explainer_maple58.py (same caption/title/visual_clip/music code);
adds step_png() for the install steps.
"""
import subprocess
import wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "marketing"
VO, ANIM, CU = ROOT / "vo_maple58_howto", ROOT / "anim", ROOT / "closeups"
WORK = ROOT / "_work_maple58_howto"
WORK.mkdir(exist_ok=True)
OUT = ROOT / "MAPLE58_HowTo_Explainer.mp4"

MUSIC = Path.home() / "Downloads" / "beats_for_ads" / "ivory_cassette.mp3"  # lofi hip-hop bed

W, H = 1920, 1080
BG = (10, 13, 18)
GOLD, GREEN, RED, AMBER, WHITE, DIM = (245, 170, 60), (64, 200, 130), (240, 90, 90), (245, 170, 60), (236, 240, 245), (138, 153, 171)
FB, FR = "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"
FM = "C:/Windows/Fonts/consola.ttf"  # monospace for file listings


def font(p, s):
    return ImageFont.truetype(p, s)


def wav_dur(p):
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()


def vdur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def caption_png(caption, sub, accent):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, H - 200, W, H], fill=(6, 8, 11, 215))
    d.rectangle([0, H - 200, W, H - 196], fill=(*accent, 255))
    d.text((80, H - 150), caption, font=font(FB, 54), fill=WHITE)
    if sub:
        d.text((80, H - 78), sub, font=font(FR, 33), fill=accent)
    p = WORK / f"cap_{abs(hash(caption + sub)) % 999999}.png"
    im.save(p)
    return p


def title_png(big1, big2, sub):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((W / 2, H / 2 - 120), big1, font=font(FB, 110), fill=GOLD, anchor="mm")
    d.text((W / 2, H / 2 + 5), big2, font=font(FB, 64), fill=WHITE, anchor="mm")
    d.text((W / 2, H / 2 + 130), sub, font=font(FR, 38), fill=DIM, anchor="mm")
    p = WORK / f"title_{abs(hash(big1 + big2)) % 999999}.png"
    im.save(p)
    return p


def step_png(num, title, detail, lines=None, accent=GOLD):
    """A clean install-step card: big number, title, one detail line, and an
    optional monospace file/list. Held still in the video (no zoom)."""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # left accent rail + step number badge
    d.rectangle([0, 0, 14, H], fill=accent)
    d.ellipse([150, 150, 150 + 150, 150 + 150], outline=accent, width=6)
    d.text((150 + 75, 150 + 75), str(num), font=font(FB, 92), fill=accent, anchor="mm")
    d.text((150, 360), f"STEP {num}", font=font(FB, 34), fill=accent)
    d.text((150, 410), title, font=font(FB, 78), fill=WHITE)
    d.text((150, 520), detail, font=font(FR, 40), fill=DIM)
    if lines:
        box_top = 640
        d.rounded_rectangle([150, box_top, 1770, box_top + 60 + 52 * len(lines)],
                            radius=14, fill=(18, 22, 28))
        for i, ln in enumerate(lines):
            d.text((190, box_top + 30 + 52 * i), ln, font=font(FM, 34), fill=(200, 210, 222))
    p = WORK / f"step_{num}_{abs(hash(title)) % 99999}.png"
    im.save(p)
    return p


def enc(args_in, vf, dur, out):
    subprocess.run(["ffmpeg", "-y", *args_in, "-t", f"{dur:.2f}", "-vf", vf, "-an",
                    "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True)


def visual_clip(item, dur, out):
    """still (.jpg/.jpeg/.png) -> held STILL, scaled to FIT (no zoom); or clip (.mp4)."""
    s = str(item)
    fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
           f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0d12,format=yuv420p")
    if s.lower().endswith((".jpg", ".jpeg", ".png")):
        enc(["-loop", "1", "-i", s], fit, dur, out)
    else:
        cl = vdur(item)
        vf = fit
        if cl < dur - 0.05:
            vf = f"tpad=stop_mode=clone:stop_duration={dur - cl:.2f}," + fit
        enc(["-i", s], vf, dur, out)


# --- install step cards for S3 (generated up front so they slot in as stills) ---
STEPS = [
    step_png(1, "Buy on Gumroad", "You get ONE file — a zip.",
             ["MarketPulse_v2.zip"], GOLD),
    step_png(2, "Unzip it", "You get a folder called MarketPulse/ with everything inside:",
             ["MarketPulse/", "  app.py        run.bat", "  static/       run.sh",
              "  options.py    README.md"], GOLD),
    step_png(3, "Launch it", "No installer. Just open the launcher:",
             ["Windows    >  double-click  run.bat",
              "Mac/Linux  >  bash run.sh"], GREEN),
    step_png(4, "It opens in your browser", "A tiny server runs on YOUR machine.",
             ["http://127.0.0.1:8000",
              "(close the window to stop it)"], GREEN),
    step_png(5, "No Python yet? (Windows)", "One-time, free — then re-run run.bat.",
             ["1.  python.org/downloads",
              "2.  CHECK the box: 'Add Python to PATH'",
              "3.  re-run run.bat"], AMBER),
]

# (vo, caption, sub, accent, [visuals], is_title)
SECTIONS = [
    ("S1_hook", "", "", GOLD,
     [("MAPLE58", "what it is  ·  how to run it", "the part nobody explains — in two minutes")], True),
    ("S2_whatitis", "What it is", "an honest options dashboard · runs on your machine · no account, no fees", GOLD,
     [CU / "cu_stockcard.jpeg", CU / "cu_nudge.jpeg", CU / "cu_strategy.jpeg"], False),
    ("S3_howtorun", "How to get it running", "buy → unzip → run.bat / run.sh → localhost:8000", GREEN,
     STEPS, False),
    ("S4_tour", "The Options tab reads like a funnel", "nudge → strategy → probe → The Read → glossary → chain", GOLD,
     [CU / "cu_nudge.jpeg", CU / "cu_strategy.jpeg", CU / "cu_probe.jpeg", CU / "cu_read.jpeg", CU / "cu_chain.jpeg"], False),
    ("S5_fourjobs", "Four jobs: GET · KEEP · GROW · SHARE", "afford it · be wrong cheaply · grow winners · prove it (losses too)", GREEN,
     [CU / "cu_scan.jpeg", CU / "cu_probe.jpeg", CU / "cu_potrows.jpeg", CU / "cu_proof.jpeg"], False),
    ("S6_close", "", "", GOLD,
     [("MAPLE58", "slow & alive  >  fast & liquidated", "most probes lose · educational, not advice · Quantum Melanin Media")], True),
]


def build_section(vo, caption, sub, accent, visuals, is_title):
    dur = wav_dur(VO / f"{vo}.wav")
    bg = WORK / f"{vo}_bg.mp4"
    if is_title:
        visual_clip(title_png(*visuals[0]), dur, bg)
    else:
        share = dur / len(visuals)
        parts = []
        for i, item in enumerate(visuals):
            pc = WORK / f"{vo}_v{i}.mp4"
            visual_clip(item, share, pc)
            parts.append(pc)
        if len(parts) == 1:
            bg = parts[0]
        else:
            lf = WORK / f"{vo}_seq.txt"
            lf.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lf),
                            "-c", "copy", str(bg)], check=True, capture_output=True)
    out = WORK / f"{vo}.mp4"
    if is_title:
        subprocess.run(["ffmpeg", "-y", "-i", str(bg), "-i", str(VO / f"{vo}.wav"),
                        "-map", "0:v", "-map", "1:a", "-t", f"{dur:.2f}", "-c:v", "libx264",
                        "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-b:a", "160k", str(out)], check=True, capture_output=True)
    else:
        cap = caption_png(caption, sub, accent)
        subprocess.run(["ffmpeg", "-y", "-i", str(bg), "-i", str(cap), "-i", str(VO / f"{vo}.wav"),
                        "-filter_complex", "[0:v][1:v]overlay=0:0[v]", "-map", "[v]", "-map", "2:a",
                        "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(out)],
                       check=True, capture_output=True)
    return out, dur


def main():
    clips, total = [], 0.0
    for vo, cap, sub, accent, visuals, is_title in SECTIONS:
        out, dur = build_section(vo, cap, sub, accent, visuals, is_title)
        clips.append(out); total += dur
        print(f"{vo}: {dur:.1f}s")
    lf = WORK / "concat.txt"
    lf.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    body = WORK / "body.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lf),
                    "-c", "copy", str(body)], check=True, capture_output=True)
    # Lofi bed: WAY down through the body, SWELL over the final RAMP_LEN s, and
    # SIDECHAIN-DUCKED by the VO. (envelope + duck = the locked music lesson.)
    LOW, HIGH, RAMP_LEN = 0.07, 0.30, 28.0
    ramp_start = max(0.0, total - RAMP_LEN)
    env = (f"volume='if(lt(t,{ramp_start:.2f}),{LOW},"
           f"{LOW}+({HIGH}-{LOW})*min(1,(t-{ramp_start:.2f})/{RAMP_LEN}))':eval=frame")
    fc = (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,{env}[bedlvl];"
          "[0:a]aresample=48000,aformat=channel_layouts=stereo[vo];"
          "[bedlvl][vo]sidechaincompress=threshold=0.05:ratio=8:attack=15:release=400[bed];"
          "[vo][bed]amix=inputs=2:duration=first:normalize=0[mix]")
    subprocess.run(["ffmpeg", "-y", "-i", str(body), "-stream_loop", "-1", "-i", str(MUSIC),
                    "-filter_complex", fc, "-map", "0:v", "-map", "[mix]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    "-shortest", str(OUT)], check=True, capture_output=True)
    print(f"\nDONE  {total:.1f}s ({total/60:.1f}min)  ->  {OUT}")


if __name__ == "__main__":
    main()
