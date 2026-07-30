"""Two Quantus+Tess explainers for the MarketPulse Robinhood build:
   1) rollout  — the build stages, why each has its place
   2) howto    — how to best use the app

Uses the FULL emo-pose catalog (qmm-cartoon-host poses + library), not just the
locked face: each beat picks a pose that matches the emotion. VO = Kokoro
(am_liam = Quantus, af_heart = Tess), one continuous read per line. Dashboard
B-roll (broll_qt/*.png) drops in as a PiP under the host on product beats.

Run FROM this folder (a stray ~/logging.py shadows stdlib logging if cwd=home):
  cd marketpulse/marketing
  python build_qt_explainers.py bake            # bake all VO (Kokoro)
  python build_qt_explainers.py build rollout   # render video 1
  python build_qt_explainers.py build howto     # render video 2
  python build_qt_explainers.py all             # bake + build both
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BROLL = os.path.join(HERE, "broll_qt")
CH = "C:/Users/respe/qmm-cartoon-host"
# New beats (downloaded 2026-07-15). One per video for variety.
MUSIC_MAP = {
    "rollout": r"C:/Users/respe/Downloads/Concrete Fist.mp3",
    "howto": r"C:/Users/respe/Downloads/Ring of Bone.mp3",
}
MUSIC = r"C:/Users/respe/the-years-after/music/i_refuse_master.mp3"  # fallback
FONT = "C\\:/Windows/Fonts/arialbd.ttf"
NAVY, GOLD, TEAL, WHITE = "0x0d1b2a", "0xf2c14e", "0x7fd1c4", "white"
ENC = ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
       "-crf", "20", "-c:a", "aac", "-ar", "44100", "-ac", "2"]

# Orientation: LAND=True -> 16:9 (1920x1080, YouTube); False -> 9:16 (Shorts).
LAND = False


def canvas():
    return (1920, 1080) if LAND else (1080, 1920)

# ---- the full emo-pose catalog (speaker -> mood -> image) -------------------
Q = {
    "neutral": f"{CH}/poses/01_neutral.png",
    "talking": f"{CH}/poses/02_talking.png",
    "pointing": f"{CH}/poses/03_pointing.png",
    "hyped": f"{CH}/poses/04_hyped.png",
    "thinking": f"{CH}/poses/05_thinking.png",
    "arms": f"{CH}/poses/06_arms_crossed.png",
    "explaining": f"{CH}/poses/07_explaining.png",
    "skeptical": f"{CH}/poses/08_skeptical.png",
    "laptop": f"{CH}/library/quantus/11_laptop_deepdive.jpeg",
    "investigator": f"{CH}/library/quantus/12_investigator.jpeg",
    "whiteboard": f"{CH}/library/quantus/15_whiteboard.jpeg",
}
T = {
    "neutral": f"{CH}/library/tess/01_neutral.jpeg",
    "talking": f"{CH}/library/tess/02_talking.jpeg",
    "pointing": f"{CH}/library/tess/03_pointing.jpeg",
    "hyped": f"{CH}/library/tess/04_hyped.jpeg",
    "thinking": f"{CH}/library/tess/05_thinking.jpeg",
    "arms": f"{CH}/library/tess/06_arms_crossed.jpeg",
    "explaining": f"{CH}/library/tess/07_explaining.jpeg",
    "skeptical": f"{CH}/library/tess/08_skeptical.jpeg",
    "laptop": f"{CH}/library/tess/11_laptop_deepdive.jpeg",
    "whiteboard": f"{CH}/library/tess/15_whiteboard.jpeg",
}
COHOST = f"{CH}/library/cohost/cohost_A.jpeg"


def pose(speaker: str, mood: str) -> str:
    if mood == "cohost":
        return COHOST
    return (Q if speaker == "quantus" else T)[mood]


def broll(name):
    return os.path.join(BROLL, name + ".png") if name else None


# segment = (id, speaker, mood, broll_name|None, vo_text, caption)
# VO text is Kokoro-tuned: digits as words, spaced abbreviations, no clipped -in'.
ROLLOUT = [
    ("r_intro", "quantus", "cohost", None,
     "We built a whole trading app. Here is how we did it. Stage, by stage.",
     "How we built it\nStage by stage"),
    ("r_pwa", "quantus", "hyped", None,
     "Stage one. We made it an app you install right on your phone. Because a tool you carry is a tool you actually use.",
     "1 · Installable app\nCarry it. Use it."),
    ("r_charts", "tess", "explaining", "broll_proof",
     "Then the charts. Real candlesticks. Green for up, red for down. You cannot read the market through a dim little line.",
     "2 · Real candles\nGreen up. Red down."),
    ("r_fix", "quantus", "thinking", None,
     "Stage three was a fix. The crypto feed broke on the server, so we rerouted it, and made the app open on your strongest screen.",
     "3 · Keep it reliable\nFix, then open smart."),
    ("r_ticket", "tess", "pointing", "broll_live",
     "Then the order ticket. Tap a dollar amount, and it shows you the shares, live. That is the Robinhood feel.",
     "4 · Quick-fill ticket\nDollars to shares, live."),
    ("r_livechart", "quantus", "laptop", "broll_live",
     "Then a live trading chart. Real candles, ticking every twenty seconds, with your entry marked in gold.",
     "5 · Live trading chart\nYour entry, in gold."),
    ("r_spread", "tess", "explaining", "broll_dca",
     "We spread that quick fill everywhere. Your pot. Your plans. And added a one day, five day zoom.",
     "6 · Quick-fill everywhere\nplus timeframe zoom"),
    ("r_cockpit", "quantus", "whiteboard", "broll_home",
     "Then the cockpit. One home screen. Your pot, your play, your plans. The second you open it.",
     "7 · The cockpit\nEverything, one glance."),
    ("r_rule", "tess", "skeptical", None,
     "Every stage had one rule. Build it. Prove it works. Ship it. Verify it live. No guessing.",
     "The rule, every stage:\nProve it. Ship it."),
    ("r_close", "quantus", "explaining", None,
     "Nine stages. Each one earned its place. Next up. Real money, the honest way.",
     "Nine stages.\nEach earned its place."),
]

HOWTO = [
    ("h_intro", "quantus", "cohost", None,
     "You got MarketPulse. Now what? Let us walk it, together.",
     "How to use it\nA quick walk-through"),
    ("h_home", "quantus", "pointing", "broll_home",
     "Start on your Home cockpit. Your pot, your live play, your saved plans. All in one glance.",
     "Start: Home cockpit\nEverything at a glance"),
    ("h_options", "tess", "explaining", "broll_options",
     "Options tab. It reads the chain and gives you a lean. Never an order. Which way it leans, and the play.",
     "Options: read the lean\nA read, not an order"),
    ("h_probe", "quantus", "investigator", "broll_pot",
     "The golden rule. Probe small. The Pot Tracker shows what percent of your pot you are risking. Stay under twenty.",
     "Rule: probe small\nStay under 20% of pot"),
    ("h_dca", "tess", "pointing", "broll_dca",
     "For the long game, the D C A wizard. Plain, lump, or signal tilt. It shows you exactly where the money is going.",
     "Long game: DCA wizard\nSee where money goes"),
    ("h_live", "quantus", "laptop", "broll_live",
     "Testing a call? Pin it on the Live tab. Real prices, honest fills, and a gold entry line right on the chart.",
     "Test it: Live tab\nReal prices, honest fills"),
    ("h_proof", "tess", "thinking", "broll_proof",
     "Doubt it? Proof Mode backtests the signal for years. And it shows the losses, not just the wins.",
     "Prove it: Proof Mode\nShows the losses too"),
    ("h_save", "quantus", "talking", "broll_home",
     "Found a plan you like? Save it. It lands on your cockpit. Load it any time.",
     "Save your plans\nLoad them any time"),
    ("h_backup", "tess", "hyped", None,
     "And back it up. One tap exports everything, so your pot and your plans are always safe.",
     "Back it up\nOne-tap export"),
    ("h_close", "quantus", "explaining", None,
     "That is it. Read the lean, size it small, prove it, keep your receipts. Slow, and alive.",
     "Read · Size small\nProve · Keep receipts"),
]

VIDEOS = {"rollout": ROLLOUT, "howto": HOWTO}


# ---- VO baking (Kokoro) ----------------------------------------------------
def vodir(video: str) -> str:
    d = os.path.join(HERE, f"vo_{video}")
    os.makedirs(d, exist_ok=True)
    return d


def bake(only_video=None) -> None:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a")
    for video, segs in VIDEOS.items():
        if only_video and video != only_video:
            continue
        out = vodir(video)
        for cid, speaker, _mood, _br, text, _cap in segs:
            voice = "am_liam" if speaker == "quantus" else "af_heart"
            wav = np.concatenate([a for _, _, a in pipe(text.strip(), voice=voice)]).astype("float32")
            sf.write(os.path.join(out, f"{cid}.wav"), wav, 24000)
            print(video, cid, voice, round(len(wav) / 24000, 1), "s")


# ---- rendering (ffmpeg) ----------------------------------------------------
def run(cmd) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{r.stderr[-1800:]}")


def wordmark() -> str:
    y = 40 if LAND else 110
    return (f"drawtext=fontfile='{FONT}':text='MarketPulse':fontcolor={GOLD}:fontsize=44:"
            f"x=(w-text_w)/2:y={y}")


def caption_chain(capdir, cid, cap, bottom) -> str:
    lines = cap.split("\n")
    n = len(lines)
    out = []
    for i, line in enumerate(lines):
        lf = os.path.join(capdir, f"{cid}_L{i}.txt")
        with open(lf, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
        lfesc = lf.replace("\\", "/").replace(":", "\\:")
        y = bottom - (n - 1 - i) * 72
        out.append(
            f"drawtext=fontfile='{FONT}':textfile='{lfesc}':fontcolor={WHITE}:fontsize=50:"
            f"box=1:boxcolor=black@0.62:boxborderw=16:x=(w-text_w)/2:y={y}")
    return ",".join(out)


def seg_face(norm, capdir, vo, cid, img, cap) -> None:
    out = os.path.join(norm, f"{cid}.mp4")
    W, H = canvas()
    if LAND:
        vf = (f"[0:v]scale=-2:940,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:{NAVY},"
              f"{wordmark()},{caption_chain(capdir, cid, cap, H - 120)}[v]")
    else:
        vf = (f"[0:v]scale=1080:-2,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:{NAVY},"
              f"{wordmark()},{caption_chain(capdir, cid, cap, 1700)}[v]")
    run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", os.path.join(vo, f"{cid}.wav"),
         "-filter_complex", vf, "-map", "[v]", "-map", "1:a", "-shortest", *ENC, out])


def seg_pip(norm, capdir, vo, cid, img, br, cap) -> None:
    out = os.path.join(norm, f"{cid}.mp4")
    W, H = canvas()
    if LAND:
        # 16:9 — dashboard B-roll on the left, host on the bottom-right.
        fc = (f"color=c={NAVY}:s={W}x{H}:r=30:d=60[bg];"
              f"[1:v]scale=1150:-1[shot];"
              f"[0:v]scale=-2:720[head];"
              f"[bg][shot]overlay=60:(H-h)/2-30[a];"
              f"[a][head]overlay=W-w-70:H-h-20[b];"
              f"[b]{wordmark()},{caption_chain(capdir, cid, cap, H - 120)}[v]")
    else:
        fc = (f"color=c={NAVY}:s=1080x1920:r=30:d=60[bg];"
              f"[1:v]scale=1000:-1[shot];"
              f"[0:v]scale=520:-2[head];"
              f"[bg][shot]overlay=(W-w)/2:230[a];"
              f"[a][head]overlay=(W-w)/2:1015[b];"
              f"[b]{wordmark()},{caption_chain(capdir, cid, cap, 1730)}[v]")
    run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-loop", "1", "-i", br,
         "-i", os.path.join(vo, f"{cid}.wav"), "-filter_complex", fc,
         "-map", "[v]", "-map", "2:a", "-shortest", *ENC, out])


def endcard(norm, capdir) -> None:
    out = os.path.join(norm, "endcard.mp4")
    W, H = canvas()
    asefile = os.path.join(capdir, "ase.txt")
    with open(asefile, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("ÀṢẹ")
    aseesc = asefile.replace("\\", "/").replace(":", "\\:")
    # vertical anchor: center the block; y0 is the top of the stack.
    y0 = 300 if LAND else 520
    dt = (
        f"drawtext=fontfile='{FONT}':text='MarketPulse':fontcolor={GOLD}:fontsize=110:x=(w-text_w)/2:y={y0},"
        f"drawtext=fontfile='{FONT}':text='Honest DCA & options.':fontcolor={WHITE}:fontsize=50:x=(w-text_w)/2:y={y0 + 170},"
        f"drawtext=fontfile='{FONT}':text='Try it FREE':fontcolor={GOLD}:fontsize=64:x=(w-text_w)/2:y={y0 + 280},"
        f"drawtext=fontfile='{FONT}':textfile='{aseesc}':fontcolor={GOLD}:fontsize=110:x=(w-text_w)/2:y={y0 + 420},"
        f"drawtext=fontfile='{FONT}':text='marketpulse-22bi.onrender.com':fontcolor={TEAL}:fontsize=36:x=(w-text_w)/2:y={y0 + 620}")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={NAVY}:s={W}x{H}:r=30:d=4",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-filter_complex", f"[0:v]{dt}[v]", "-map", "[v]", "-map", "1:a", "-t", "4", *ENC, out])


def build(video: str) -> None:
    segs = VIDEOS[video]
    vo = vodir(video)
    sfx = "_wide" if LAND else ""
    norm = os.path.join(HERE, f"norm_{video}{sfx}")
    capdir = os.path.join(HERE, f"cap_{video}{sfx}")
    os.makedirs(norm, exist_ok=True)
    os.makedirs(capdir, exist_ok=True)
    for cid, speaker, mood, br, _text, cap in segs:
        img = pose(speaker, mood)
        brp = broll(br)
        if brp and os.path.isfile(brp):
            seg_pip(norm, capdir, vo, cid, img, brp, cap)
        else:
            seg_face(norm, capdir, vo, cid, img, cap)
        print("seg", cid, mood)
    endcard(norm, capdir)
    listfile = os.path.join(norm, "_list.txt")
    with open(listfile, "w", encoding="utf-8", newline="\n") as fh:
        for cid, *_ in segs:
            fh.write(f"file '{os.path.join(norm, cid + '.mp4')}'\n".replace("\\", "/"))
        fh.write(f"file '{os.path.join(norm, 'endcard.mp4')}'\n".replace("\\", "/"))
    silent = os.path.join(HERE, f"MarketPulse_{video}_nomusic{sfx}.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", silent])
    tag = "_16x9" if LAND else ""
    final = os.path.join(HERE, f"MarketPulse_{video}_QT{tag}.mp4")
    music = MUSIC_MAP.get(video, MUSIC)
    # Bed kept low (0.08) under the VO + loudnorm so it never reads as static
    # (the MAPLE58 lesson). afade in/out to top & tail cleanly.
    fc = ("[1:a]volume=0.08,afade=t=in:st=0:d=1.2[m];"
          "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mx];"
          "[mx]loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    run(["ffmpeg", "-y", "-i", silent, "-i", music, "-filter_complex", fc,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", final])
    print("DONE ->", final)


def main() -> None:
    global LAND
    args = sys.argv[1:]
    if "wide" in args:
        LAND = True
        args = [a for a in args if a != "wide"]
    if not args or args[0] == "all":
        bake()
        build("rollout")
        build("howto")
    elif args[0] == "bake":
        bake(args[1] if len(args) > 1 else None)
    elif args[0] == "build":
        build(args[1])
    else:
        print("usage: build_qt_explainers.py [bake|build <video>|all] [wide]")


if __name__ == "__main__":
    main()
