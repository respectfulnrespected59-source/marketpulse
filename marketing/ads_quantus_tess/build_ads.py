"""Assemble MAPLE58 Quantus+Tess ads from the 12 Kling talking-head clips.

Pipeline (ffmpeg, all local):
  1. normalize each clips/<id>.mp4 -> norm/<id>.mp4 (1080x1920 navy canvas,
     MAPLE58 wordmark, per-line burned captions). Product lines (q_get/q_keep/
     q_grow/q_proof) use a PiP layout: dashboard B-roll panel on top, talking
     head below, caption at bottom.
  2. make end card (MAPLE58 + ASE + Gumroad).
  3. concat narrative order + end card -> *_nomusic.mp4
  4. mix "I Refuse" as a ducked bed -> hero.mp4 / cutdown.mp4

Re-run safe. Stdlib + ffmpeg only.
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS = os.path.join(HERE, "clips")
NORM = os.path.join(HERE, "norm")
CAPDIR = os.path.join(HERE, "captions")
MUSIC = r"C:/Users/respe/the-years-after/music/i_refuse_master.mp3"
FONT = "C\\:/Windows/Fonts/arialbd.ttf"  # escaped colon for filtergraph
os.makedirs(NORM, exist_ok=True)
os.makedirs(CAPDIR, exist_ok=True)

NAVY = "0x0d1b2a"
GOLD = "0xf2c14e"
TEAL = "0x7fd1c4"
WHITE = "white"
ENC = ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
       "-crf", "20", "-c:a", "aac", "-ar", "44100", "-ac", "2"]

HERO = ["q_intro", "q_math", "q_get", "q_keep", "q_grow", "q_proof", "q_cta", "q_signoff"]
CUT = ["c_hook", "c_math", "c_what", "c_cta"]

# product lines -> dashboard B-roll panel
BROLL = {
    "q_get":   r"C:/Users/respe/dash_main.png",
    "q_keep":  r"C:/Users/respe/dash_options.png",
    "q_grow":  r"C:/Users/respe/dash_pot.png",
    "q_proof": r"C:/Users/respe/dash_proof.png",
}

CAPTIONS = {
    "q_intro": "Most options tools\npromise you a Lambo.",
    "q_math": "Most options trades LOSE.\nWe built a robot that\nloses small & survives.",
    "q_get": "Finds plays you can\nactually afford.",
    "q_keep": "Real-dollar prices.\nIt tells you when to WALK.",
    "q_grow": "Pot Tracker shows\nthe come-up:  $300 -> $333.",
    "q_proof": "Proof Mode shows the\nLOSSES too. Just receipts.",
    "q_cta": "Your machine. No account.\nNo monthly fee.",
    "q_signoff": "Slow & alive beats\nfast & liquidated.",
    "c_hook": "Most tools promise\na Lambo. We won't.",
    "c_math": "Most trades lose.\nWe lose small & survive.",
    "c_what": "Find plays you can afford.\nKnow when to walk.",
    "c_cta": "MAPLE58\nGet it on Gumroad",
}


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{r.stderr[-1800:]}")


def caption_chain(cid: str, bottom: int) -> str:
    """Per-line drawtext filters (separate textfiles avoid \\n-tofu + quoting)."""
    lines = CAPTIONS[cid].split("\n")
    n = len(lines)
    out = []
    for i, line in enumerate(lines):
        lf = os.path.join(CAPDIR, f"{cid}_L{i}.txt")
        with open(lf, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
        lfesc = lf.replace("\\", "/").replace(":", "\\:")
        y = bottom - (n - 1 - i) * 72
        out.append(
            f"drawtext=fontfile='{FONT}':textfile='{lfesc}':fontcolor={WHITE}:fontsize=52:"
            f"box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y={y}"
        )
    return ",".join(out)


WORDMARK = (f"drawtext=fontfile='{FONT}':text='MAPLE58':fontcolor={GOLD}:fontsize=44:"
            f"x=(w-text_w)/2:y=120")


def normalize(cid: str) -> None:
    out = os.path.join(NORM, f"{cid}.mp4")
    vf = (f"scale=1080:-2,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:{NAVY},"
          f"{WORDMARK},{caption_chain(cid, 1690)}")
    run(["ffmpeg", "-y", "-i", os.path.join(CLIPS, f"{cid}.mp4"), "-vf", vf, *ENC, out])


def normalize_pip(cid: str, shot: str) -> None:
    out = os.path.join(NORM, f"{cid}.mp4")
    fc = (f"color=c={NAVY}:s=1080x1920:r=30:d=30[bg];"
          f"[1:v]scale=1000:-1[shot];"
          f"[0:v]scale=600:-2[head];"
          f"[bg][shot]overlay=(W-w)/2:250[a];"
          f"[a][head]overlay=(W-w)/2:810[b];"
          f"[b]{WORDMARK},{caption_chain(cid, 1700)}[v]")
    run(["ffmpeg", "-y", "-i", os.path.join(CLIPS, f"{cid}.mp4"), "-loop", "1", "-i", shot,
         "-filter_complex", fc, "-map", "[v]", "-map", "0:a", "-shortest", *ENC, out])


def make_endcard() -> str:
    out = os.path.join(NORM, "endcard.mp4")
    asefile = os.path.join(CAPDIR, "ase.txt")
    with open(asefile, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("ÀṢẹ")  # ÀṢẹ
    aseesc = asefile.replace("\\", "/").replace(":", "\\:")
    dt = (
        f"drawtext=fontfile='{FONT}':text='MAPLE58':fontcolor={GOLD}:fontsize=120:x=(w-text_w)/2:y=560,"
        f"drawtext=fontfile='{FONT}':text='Honest options research.':fontcolor={WHITE}:fontsize=52:x=(w-text_w)/2:y=730,"
        f"drawtext=fontfile='{FONT}':text='Your machine. No monthly fee.':fontcolor=0xb8c4d0:fontsize=42:x=(w-text_w)/2:y=820,"
        f"drawtext=fontfile='{FONT}':textfile='{aseesc}':fontcolor={GOLD}:fontsize=110:x=(w-text_w)/2:y=1040,"
        f"drawtext=fontfile='{FONT}':text='quantummelaninmedia.gumroad.com':fontcolor={TEAL}:fontsize=40:x=(w-text_w)/2:y=1260"
    )
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={NAVY}:s=1080x1920:r=30:d=3",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-filter_complex", f"[0:v]{dt}[v]", "-map", "[v]", "-map", "1:a", "-t", "3", *ENC, out])
    return out


def concat(ids: list[str], out_name: str) -> str:
    listfile = os.path.join(NORM, f"_{out_name}.txt")
    with open(listfile, "w", encoding="utf-8", newline="\n") as fh:
        for cid in ids + ["endcard"]:
            fh.write(f"file '{os.path.join(NORM, cid + '.mp4')}'\n".replace("\\", "/"))
    out = os.path.join(HERE, f"{out_name}_nomusic.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", out])
    return out


def add_music(silent: str, out_name: str) -> None:
    out = os.path.join(HERE, f"{out_name}.mp4")
    # normalize=0 stops amix's 1/n attenuation; loudnorm lifts VO to social loudness
    fc = ("[1:a]volume=0.18,afade=t=in:st=0:d=1[m];"
          "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mx];"
          "[mx]loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    run(["ffmpeg", "-y", "-i", silent, "-i", MUSIC, "-filter_complex", fc,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", out])


def main() -> None:
    for cid in HERO + CUT:
        if cid in BROLL:
            normalize_pip(cid, BROLL[cid])
        else:
            normalize(cid)
        print(f"norm {cid}")
    make_endcard()
    print("endcard")
    add_music(concat(HERO, "hero"), "hero")
    add_music(concat(CUT, "cut"), "cutdown")
    print("DONE -> hero.mp4, cutdown.mp4")


if __name__ == "__main__":
    main()
