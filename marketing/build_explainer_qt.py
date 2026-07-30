"""Assemble the MarketPulse Quantus+Tess explainer (no-credit cut).

Each line = a STILL (speaker locked face, or dashboard B-roll PiP) + the baked VO
wav (vo_explainer/<id>.wav) + burned caption. Concat in script order + end card,
then mix a ducked "I Refuse" bed. ffmpeg + stdlib only, re-run safe.

Run FROM this folder:  cd marketpulse/marketing && python build_explainer_qt.py
Output: marketpulse/marketing/MarketPulse_QT_Explainer.mp4  (1080x1920)
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
VO = os.path.join(HERE, "vo_explainer")
NORM = os.path.join(HERE, "norm_qt")
CAPDIR = os.path.join(HERE, "captions_qt")
MUSIC = r"C:/Users/respe/the-years-after/music/i_refuse_master.mp3"
QUANTUS = r"C:/Users/respe/qmm-cartoon-host/host_LOCKED.jpg"
TESS = r"C:/Users/respe/qmm-cartoon-host/tess_LOCKED.jpg"
FONT = "C\\:/Windows/Fonts/arialbd.ttf"
os.makedirs(NORM, exist_ok=True)
os.makedirs(CAPDIR, exist_ok=True)

NAVY, GOLD, TEAL, WHITE = "0x0d1b2a", "0xf2c14e", "0x7fd1c4", "white"
ENC = ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
       "-crf", "20", "-c:a", "aac", "-ar", "44100", "-ac", "2"]

ORDER = ["q_hook", "t_free", "q_what", "t_what", "q_get", "t_grow",
         "q_proof", "t_lesson", "q_close", "b_quantus", "b_tess"]

FACE = {"q_hook": QUANTUS, "t_free": TESS, "q_what": QUANTUS, "t_what": TESS,
        "q_get": QUANTUS, "t_grow": TESS, "q_proof": QUANTUS, "t_lesson": TESS,
        "q_close": QUANTUS, "b_quantus": QUANTUS, "b_tess": TESS}

BROLL = {"q_what": r"C:/Users/respe/dash_options.png",
         "q_get":  r"C:/Users/respe/dash_main.png",
         "t_grow": r"C:/Users/respe/dash_pot.png",
         "q_proof": r"C:/Users/respe/dash_proof.png"}

CAPTIONS = {
    "q_hook":   "Most options trades\nLOSE. That's the math.",
    "t_free":   "MarketPulse won't hide it.\nNow it's FREE.",
    "q_what":   "Live chains, IV & Greeks.\nRuns on YOUR machine.",
    "t_what":   "What can I afford -\nand lose small when wrong?",
    "q_get":    "GET + KEEP: affordable\nprobes, a delta floor.",
    "t_grow":   "GROW: $300 -> $333,\none probe at a time.",
    "q_proof":  "PROOF MODE shows\nthe LOSSES too.",
    "t_lesson": "No clean 'beats the market.'\nThe edge is survival.",
    "q_close":  "Slow & alive beats\nfast & liquidated.",
    "b_quantus": "QUANTUM MELANIN MEDIA",
    "b_tess":   "Voice + receipts for the\nunparented diaspora.",
}

WORDMARK = (f"drawtext=fontfile='{FONT}':text='MAPLE58':fontcolor={GOLD}:fontsize=44:"
            f"x=(w-text_w)/2:y=120")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{r.stderr[-1800:]}")


def caption_chain(cid: str, bottom: int) -> str:
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
            f"box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y={y}")
    return ",".join(out)


def seg_face(cid: str) -> None:
    out = os.path.join(NORM, f"{cid}.mp4")
    vf = (f"[0:v]scale=1080:-2,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:{NAVY},"
          f"{WORDMARK},{caption_chain(cid, 1690)}[v]")
    run(["ffmpeg", "-y", "-loop", "1", "-i", FACE[cid], "-i", os.path.join(VO, f"{cid}.wav"),
         "-filter_complex", vf, "-map", "[v]", "-map", "1:a", "-shortest", *ENC, out])


def seg_pip(cid: str) -> None:
    out = os.path.join(NORM, f"{cid}.mp4")
    fc = (f"color=c={NAVY}:s=1080x1920:r=30:d=60[bg];"
          f"[1:v]scale=1000:-1[shot];"
          f"[0:v]scale=520:-2[head];"
          f"[bg][shot]overlay=(W-w)/2:250[a];"
          f"[a][head]overlay=(W-w)/2:1000[b];"
          f"[b]{WORDMARK},{caption_chain(cid, 1720)}[v]")
    run(["ffmpeg", "-y", "-loop", "1", "-i", FACE[cid], "-loop", "1", "-i", BROLL[cid],
         "-i", os.path.join(VO, f"{cid}.wav"), "-filter_complex", fc,
         "-map", "[v]", "-map", "2:a", "-shortest", *ENC, out])


def make_endcard() -> None:
    out = os.path.join(NORM, "endcard.mp4")
    asefile = os.path.join(CAPDIR, "ase.txt")
    with open(asefile, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("ÀṢẹ")
    aseesc = asefile.replace("\\", "/").replace(":", "\\:")
    dt = (
        f"drawtext=fontfile='{FONT}':text='MAPLE58':fontcolor={GOLD}:fontsize=120:x=(w-text_w)/2:y=520,"
        f"drawtext=fontfile='{FONT}':text='Honest options research.':fontcolor={WHITE}:fontsize=50:x=(w-text_w)/2:y=690,"
        f"drawtext=fontfile='{FONT}':text='FREE - name your price.':fontcolor={GOLD}:fontsize=58:x=(w-text_w)/2:y=800,"
        f"drawtext=fontfile='{FONT}':textfile='{aseesc}':fontcolor={GOLD}:fontsize=110:x=(w-text_w)/2:y=1010,"
        f"drawtext=fontfile='{FONT}':text='quantummelaninmedia.gumroad.com/l/yvsyyg':fontcolor={TEAL}:fontsize=34:x=(w-text_w)/2:y=1240")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={NAVY}:s=1080x1920:r=30:d=4",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-filter_complex", f"[0:v]{dt}[v]", "-map", "[v]", "-map", "1:a", "-t", "4", *ENC, out])


def concat_all() -> str:
    listfile = os.path.join(NORM, "_list.txt")
    with open(listfile, "w", encoding="utf-8", newline="\n") as fh:
        for cid in ORDER + ["endcard"]:
            fh.write(f"file '{os.path.join(NORM, cid + '.mp4')}'\n".replace("\\", "/"))
    out = os.path.join(HERE, "MarketPulse_QT_nomusic.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", out])
    return out


def add_music(silent: str) -> None:
    out = os.path.join(HERE, "MarketPulse_QT_Explainer.mp4")
    fc = ("[1:a]volume=0.10,afade=t=in:st=0:d=1[m];"
          "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mx];"
          "[mx]loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    run(["ffmpeg", "-y", "-i", silent, "-i", MUSIC, "-filter_complex", fc,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", out])


def main() -> None:
    for cid in ORDER:
        if cid in BROLL:
            seg_pip(cid)
        else:
            seg_face(cid)
        print("seg", cid)
    make_endcard()
    print("endcard")
    add_music(concat_all())
    print("DONE -> MarketPulse_QT_Explainer.mp4")


if __name__ == "__main__":
    main()
