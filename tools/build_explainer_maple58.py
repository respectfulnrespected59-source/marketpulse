"""Assemble the MAPLE58 master explainer (v2) — 5-10min, close-ups, no personal lore.

Each VO section gets a SEQUENCE of motion backgrounds (readable close-ups +
animated graphs + title cards), time-split evenly across the VO, with a baked
lower-third caption, then concatenated under a Lion-of-Mali bed. 1920x1080.
MAPLE = MArket PuLsE. Honest framing, NOT advice.
"""
import subprocess
import wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent / "marketing"
VO, ANIM, WALK, CU = ROOT / "vo_maple58", ROOT / "anim", ROOT / "walkthrough", ROOT / "closeups"
WORK = ROOT / "_work_maple58"
WORK.mkdir(exist_ok=True)
OUT = ROOT / "MAPLE58_Explainer.mp4"

MUSIC = Path.home() / "Downloads" / "beats_for_ads" / "ivory_cassette.mp3"  # lofi hip-hop bed

W, H = 1920, 1080
BG = (10, 13, 18)
GOLD, GREEN, RED, AMBER, WHITE, DIM = (245, 170, 60), (64, 200, 130), (240, 90, 90), (245, 170, 60), (236, 240, 245), (138, 153, 171)
FB, FR = "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"


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


def enc(args_in, vf, dur, out):
    subprocess.run(["ffmpeg", "-y", *args_in, "-t", f"{dur:.2f}", "-vf", vf, "-an",
                    "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True)


def visual_clip(item, dur, out):
    """item = still (.jpg/.jpeg/.png) -> held STILL, scaled to FIT (no zoom — the
    slow zoom magnified past the frame edge & strained the eyes); or clip (.mp4)."""
    s = str(item)
    fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
           f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0d12,format=yuv420p")
    if s.lower().endswith((".jpg", ".jpeg", ".png")):
        enc(["-loop", "1", "-i", s], fit, dur, out)
    else:
        cl = vdur(item)
        vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0d12,format=yuv420p"
        if cl < dur - 0.05:
            vf = f"tpad=stop_mode=clone:stop_duration={dur - cl:.2f}," + vf
        enc(["-i", s], vf, dur, out)


# (vo, caption, sub, accent, [visuals], is_title)
SECTIONS = [
    ("S1_hook", "MAPLE58 — an honest options tool", "GET · KEEP · GROW · SHARE · it won't lie to you about getting rich", GOLD,
     [ANIM / "candle_run.mp4", CU / "cu_stockcard.jpeg", CU / "cu_nudge.jpeg"], False),
    ("S2_name", "", "", GOLD, [("MAPLE58", "= MArket PuLsE", "most trades lose — survival is the real skill")], True),
    ("S3_tour", "The layout — where everything lives", "tabs · cards · the Options story · scan · pot · proof", GOLD,
     [CU / "cu_stockcard.jpeg", CU / "cu_nudge.jpeg", CU / "cu_strategy.jpeg", CU / "cu_probe.jpeg", CU / "cu_read.jpeg", CU / "cu_chain.jpeg"], False),
    ("S4_get", "GET — find a play you can afford", "nudge · squeeze · scanner (stocks + crypto)", GREEN,
     [CU / "cu_nudge.jpeg", ANIM / "candle_squeeze.mp4", ANIM / "candle_move.mp4", CU / "cu_scan.jpeg"], False),
    ("S5_keep", "KEEP — be wrong cheaply", "Δ0.25 floor · 'too rich → walk' · real dollars · most probes lose", AMBER,
     [ANIM / "candle_probe.mp4", ANIM / "probe_curve.mp4", CU / "cu_probe.jpeg", CU / "cu_chain.jpeg"], False),
    ("S6_grow", "GROW — escalate the winners", "probe → read → escalate · $300 → $333 · discipline vs ruin", GREEN,
     [ANIM / "payoff_call.mp4", ANIM / "payoff_strangle.mp4", ANIM / "pot_ladder.mp4", CU / "cu_potrows.jpeg"], False),
    ("S7_example", "One name, start to finish", "nudge → probe → read → escalate → log it", GOLD,
     [ANIM / "candle_run.mp4", CU / "cu_strategy.jpeg", CU / "cu_probe.jpeg", CU / "cu_potrows.jpeg"], False),
    ("S8_share", "SHARE — the method is the gift", "Proof Mode · glossary · stays free · educational, not advice", GOLD,
     [ANIM / "candle_backtest.mp4", CU / "cu_proof.jpeg", CU / "cu_read.jpeg"], False),
    ("S9_close", "", "", GOLD, [("MAPLE58", "slow & alive  >  fast & liquidated", "free · educational, not advice · a Quantum Melanin Media tool")], True),
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
    # Hip-hop bed with a VOLUME ENVELOPE (user feedback: bed was too constant /
    # "nonstop noise" through the body). Keep it WAY down during the teaching body
    # (LOW), then SWELL up over the final RAMP_LEN seconds for an outro feel. Still
    # SIDECHAIN-DUCKED by the VO so speech stays clear. amix normalize=0 = VO full.
    LOW, HIGH, RAMP_LEN = 0.07, 0.34, 38.0
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
    print(f"\nDONE  {total:.1f}s ({total/60:.1f}min)  ->  {OUT}  (bed: low body -> end swell)")


if __name__ == "__main__":
    main()
