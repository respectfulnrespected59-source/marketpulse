"""DISCIPLINE explainer builder — "The Robot That Refuses".

Same pipeline as qmm-cartoon-host/assemble_ep03.py: pose still + on-screen super
+ caption bar, cut to the baked VO, with a ducked music bed. Difference here is
the VISUAL: app screenshots and real code panels carry the information, and the
Quantus/Tess emo poses sit beside them to emphasize.

VO is pre-baked by bake_discipline_vo.py -> vo_discipline/<id>.wav

Usage:
  python assemble_discipline.py cards    # render code panels only
  python assemble_discipline.py build    # frames + stitch
  python assemble_discipline.py all
"""
import os
import subprocess
import sys

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HOST = r"C:/Users/respe/qmm-cartoon-host"
HERE = os.path.dirname(os.path.abspath(__file__))
VO = f"{HERE}/vo_discipline"
FR = f"{HERE}/discipline_build"
SHOTS = f"{HERE}/discipline_shots"

SR = 24000
W, H = 1920, 1080
GOLD = (240, 190, 70)
TEAL = (60, 210, 200)
WHITE = (240, 240, 240)
NAVY = (15, 22, 32)
INK = (8, 10, 14)
CODE_BG = (18, 20, 30)
RED = (220, 90, 90)
GREEN = (120, 210, 140)
FBOLD = "C:/Windows/Fonts/arialbd.ttf"
FIMP = "C:/Windows/Fonts/impact.ttf"
FMONO = "C:/Windows/Fonts/consola.ttf"

# pose tag -> (quantus file, tess file)
POSE = {
    "POINT":      ("poses/03_pointing.png",     "library/tess/03_pointing.jpeg"),
    "TALK":       ("poses/02_talking.png",      "library/tess/02_talking.jpeg"),
    "STOP":       ("poses/08_skeptical.png",    "library/tess/08_skeptical.jpeg"),
    "CROSSED":    ("poses/06_arms_crossed.png", "library/tess/06_arms_crossed.jpeg"),
    "EXPLAIN":    ("poses/07_explaining.png",   "library/tess/07_explaining.jpeg"),
    "HYPED":      ("poses/04_hyped.png",        "library/tess/04_hyped.jpeg"),
    "THINK":      ("poses/05_thinking.png",     "library/tess/05_thinking.jpeg"),
    "NEUTRAL":    ("poses/01_neutral.png",      "library/tess/01_neutral.jpeg"),
    "WHITEBOARD": ("library/quantus/15_whiteboard.jpeg", "library/tess/15_whiteboard.jpeg"),
    "CAMARO":     ("library/quantus/13_camaro.jpeg",     "library/tess/13_camaro.jpeg"),
}

C_HDR = [("# agent/guardrails.py", GOLD),
         ('"""Independent safety controls -', WHITE),
         ("   enforced BEFORE any order is sent.", WHITE),
         ("", WHITE),
         ("   Each check is independent:", GREEN),
         ("   prompt/signal output never decides", GREEN),
         ("   whether a trade is allowed,", GREEN),
         ('   these functions do."""', GREEN)]
C_ERRS = [("class SpendLimitError(...)", RED),
          ("class CircuitBreakerError(...)", RED),
          ("class HaltError(...)", RED),
          ("class StaleProposalError(...)", RED),
          ("class SlippageError(...)", RED),
          ("class DisallowedSymbolError(...)", RED)]
C_MODE = [("# agent/config.py", GOLD),
          ('MODE  = "propose"    # not "execute"', WHITE),
          ("PAPER = True         # fake money", WHITE)]
C_SPEND = [("# agent/config.py", GOLD),
           ("MAX_SINGLE_TX_USD   = 100", WHITE),
           ("MAX_DAILY_SPEND_USD = 400", WHITE),
           ("PER_TRADE_USD       = 50", WHITE)]
C_HALT = [("def check_not_halted() -> None:", GOLD),
          ("    if store.is_halted():", WHITE),
          ("        raise HaltError(", RED),
          ('            "Trading halted")', RED)]
C_TTL = [("PROPOSAL_TTL = 1800   # 30 minutes", GOLD),
         ("", WHITE),
         ("def check_fresh(proposal):", WHITE),
         ("    age = time.time() - proposal['ts']", WHITE),
         ("    if age > config.PROPOSAL_TTL:", WHITE),
         ("        raise StaleProposalError(...)", RED)]
C_SYM = [("def check_symbol_allowed(proposal):", GOLD),
         ("    # The chokepoint must not trust", GREEN),
         ("    # the proposal record.", GREEN),
         ("    if symbol not in allowed_symbols():", WHITE),
         ("        raise DisallowedSymbolError(...)", RED)]
C_SLIP = [("MAX_SLIPPAGE_PCT = {", GOLD),
          ('  "stock":  0.005,   # half a percent', WHITE),
          ('  "crypto": 0.015,   # one and a half', WHITE),
          ("}", GOLD),
          ("if adverse > band:", WHITE),
          ("    raise SlippageError(...)", RED)]
C_LOSS = [("MAX_CONSECUTIVE_LOSSES = 3", GOLD),
          ("", WHITE),
          ("def record_trade_result(is_win):", WHITE),
          ("    losses = 0 if is_win else losses+1", WHITE),
          ("    if losses >= MAX_CONSECUTIVE_LOSSES:", WHITE),
          ('        store.engage_halt("3 losses")', RED)]
C_DD = [("MAX_DAILY_LOSS_PCT = 0.05   # 5%", GOLD),
        ("", WHITE),
        ("drawdown = (equity - start) / start", WHITE),
        ("if drawdown <= -MAX_DAILY_LOSS_PCT:", WHITE),
        ("    store.engage_halt(...)", RED),
        ("    raise CircuitBreakerError(...)", RED)]
C_ASYM = [("# only BUYS are spend-capped", GOLD),
          ('if proposal["side"] == "buy":', WHITE),
          ("    check_spend(notional)", WHITE),
          ("", WHITE),
          ("# sells reduce exposure;", GREEN),
          ("# don't spend-cap exits", GREEN)]
C_LABELS = [('ENTRY_LABELS = {"STRONG BUY"}', GOLD),
            ('EXIT_LABELS  = {"SELL",', WHITE),
            ('                "STRONG SELL"}', WHITE),
            ("", WHITE),
            ("# high bar in. low bar out.", GREEN)]
C_BLIND = [("if current_price is None:", WHITE),
           ("    raise SlippageError(", RED),
           ('      "No live price supplied;', RED),
           ('       refusing to send blind")', RED)]
CODE = {"hdr": ("guardrails.py", C_HDR), "errs": ("six ways to refuse", C_ERRS),
        "mode": ("propose, not execute", C_MODE), "spend": ("the ceilings", C_SPEND),
        "halt": ("the kill switch", C_HALT), "ttl": ("signals expire", C_TTL),
        "sym": ("re-check the ticker", C_SYM), "slip": ("the market moved", C_SLIP),
        "loss": ("three strikes", C_LOSS), "dd": ("the drawdown brake", C_DD),
        "asym": ("buys capped, sells never", C_ASYM),
        "labels": ("asymmetric conviction", C_LABELS), "blind": ("fail closed", C_BLIND)}

# (vo_id, who, pose, visual, super)   visual: code:<key> | shot:<file> | pose
BEATS = [
    ("q_open",    "Q", "POINT",   "shot:dash_main.png",   "IT FINDS A SETUP IT LIKES"),
    ("q_open2",   "Q", "STOP",    "code:hdr",             "...AND THEN IT SAYS NO"),
    ("t_wound",   "T", "CROSSED", "pose",                 "IT'S NEVER ONE BAD CALL"),
    ("t_wound2",  "T", "EXPLAIN", "pose",                 "THE CHAIN: LOSE - SIZE UP - LOSE"),
    ("t_wound3",  "T", "POINT",   "pose",                 "WRONG ONCE ISN'T WHAT KILLS YOU"),
    ("q_turn",    "Q", "POINT",   "code:hdr",             "I BUILT THE PART THAT REFUSES"),
    ("q_turn2",   "Q", "TALK",    "code:errs",            "NINE INDEPENDENT CONTROLS"),
    ("q_thesis1", "Q", "EXPLAIN", "pose",                 "EVERYBODY SELLS SIGNALS"),
    ("t_thesis",  "T", "POINT",   "pose",                 "NOBODY SELLS BRAKES"),
    ("q_thesis2", "Q", "POINT",   "code:hdr",             "THE A.I. DOESN'T GET A VOTE"),
    ("t_g1",      "T", "CROSSED", "pose",                 "1 - MOST BOTS TRADE ON DAY ONE"),
    ("q_g1",      "Q", "EXPLAIN", "code:mode",            "PROPOSE, NOT EXECUTE - PAPER DEFAULT"),
    ("t_g2",      "T", "POINT",   "pose",                 "2 - THE SIZE YOU'D NEVER PASS"),
    ("q_g2",      "Q", "POINT",   "code:spend",           "$100 PER-TRADE CEILING"),
    ("t_g3",      "T", "EXPLAIN", "pose",                 "3 - THE DAY YOU'RE DOWN"),
    ("q_g3",      "Q", "TALK",    "code:spend",           "$400/DAY - KILLS THE DEATH SPIRAL"),
    ("q_g4",      "Q", "STOP",    "code:halt",            "4 - ONE FLAG. EVERYTHING STOPS."),
    ("t_g5",      "T", "THINK",   "shot:dash_main.png",   "5 - YOU STEP AWAY..."),
    ("q_g5",      "Q", "POINT",   "code:ttl",             "30 MINUTES, THEN IT'S DEAD"),
    ("t_g6",      "T", "CROSSED", "pose",                 "6 - THIS ONE SOUNDS PARANOID"),
    ("q_g6",      "Q", "EXPLAIN", "code:sym",             "IT DOESN'T TRUST ITS OWN QUEUE"),
    ("t_g7",      "T", "POINT",   "shot:tab_options.png", "7 - YOUR EDGE WAS AT *THAT* PRICE"),
    ("q_g7",      "Q", "TALK",    "code:slip",            "0.5% STOCKS / 1.5% CRYPTO"),
    ("t_g8",      "T", "POINT",   "pose",                 "8 - AFTER THREE, YOU'RE CHASING"),
    ("q_g8",      "Q", "HYPED",   "code:loss",            "THREE LOSSES - IT HALTS ITSELF"),
    ("t_g9",      "T", "NEUTRAL", "pose",                 "9 - AND THE WHOLE DAY?"),
    ("q_g9",      "Q", "POINT",   "code:dd",              "DOWN 5% - EVERYTHING HALTS"),
    ("q_asym",    "Q", "EXPLAIN", "code:asym",            "THE CAPS ONLY APPLY TO BUYS"),
    ("t_asym",    "T", "EXPLAIN", "code:asym",            "SELLING IS NEVER BLOCKED"),
    ("q_asym2",   "Q", "TALK",    "pose",                 "A CAP THAT TRAPPED YOU WOULD HURT YOU"),
    ("t_asym2",   "T", "POINT",   "code:labels",          "STRONG BUY IN - ANY SELL OUT"),
    ("q_asym3",   "Q", "POINT",   "code:labels",          "HIGH BAR IN. LOW BAR OUT."),
    ("q_fail",    "Q", "STOP",    "code:blind",           "NO LIVE PRICE? IT REFUSES."),
    ("t_fail",    "T", "NEUTRAL", "code:blind",           "WHEN IT DOESN'T KNOW, IT DOES NOTHING"),
    ("q_receipt", "Q", "POINT",   "code:spend",           "EVERY NUMBER IS IN THE FILE"),
    ("t_receipt", "T", "WHITEBOARD", "code:spend",        "100 - 400 - 3 - 5% - 30min - 0.5%"),
    ("t_close1",  "T", "EXPLAIN", "pose",                 "NOT ADVICE. NOT A RECOMMENDATION."),
    ("q_close1",  "Q", "STOP",    "pose",                 "MOST OPTIONS TRADES LOSE."),
    ("t_close2",  "T", "POINT",   "pose",                 "SEATBELTS DON'T MAKE YOU A GOOD DRIVER"),
    ("q_close2",  "Q", "EXPLAIN", "pose",                 "DISCIPLINE, WRITTEN DOWN IN CODE"),
    ("q_bumper",  "Q", "CAMARO",  "pose",                 "QUANTUM MELANIN MEDIA"),
    ("t_bumper",  "T", "CAMARO",  "pose",                 "VOICE + RECEIPTS FOR THE DIASPORA"),
    ("q_ase",     "Q", "CAMARO",  "pose",                 "ASE"),
]
NO_BED = {"t_close1", "q_close1", "t_close2", "q_close2"}


def render_code_panels() -> None:
    os.makedirs(SHOTS, exist_ok=True)
    mono = ImageFont.truetype(FMONO, 34)
    tf = ImageFont.truetype(FBOLD, 30)
    for key, (title, rows) in CODE.items():
        cw, chh = 1180, 60 + len(rows) * 46 + 40
        img = Image.new("RGB", (cw, chh), CODE_BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, cw, 56], fill=(30, 34, 50))
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse([20 + i * 30, 20, 36 + i * 30, 36], fill=c)
        d.text((120, 15), title, font=tf, fill=(170, 176, 200))
        y = 74
        for text, col in rows:
            d.text((36, y), text, font=mono, fill=col)
            y += 46
        img.save(f"{SHOTS}/code_{key}.png")
    print(f"rendered {len(CODE)} code panels -> {SHOTS}")


def _wrap(d, text, font, maxw):
    words, out, line = text.split(), [], ""
    for w in words:
        t = (line + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            line = t
        else:
            out.append(line)
            line = w
    if line:
        out.append(line)
    return out


def frame(bid, who, pose, visual, sup, vo, idx):
    accent = TEAL if who == "T" else GOLD
    name = "QUANTUS" if who == "Q" else "TESS"
    bg = Image.new("RGB", (W, H), NAVY)
    gd = ImageDraw.Draw(bg)
    gd.ellipse([W * .5 - 620, H * .5 - 520, W * .5 + 620, H * .5 + 380], fill=(30, 44, 60))
    cv = bg.filter(ImageFilter.GaussianBlur(200))

    pq, pt = POSE[pose]
    ch = Image.open(f"{HOST}/{pq if who == 'Q' else pt}").convert("RGB")

    if visual == "pose":
        s = 1000 / ch.height
        if ch.width * s > 1180:
            s = 1180 / ch.width
        ch = ch.resize((int(ch.width * s), int(ch.height * s)))
        pos = ((W - ch.width) // 2, (H - ch.height) // 2 - 30)
        ins = 40
        m = Image.new("L", ch.size, 0)
        ImageDraw.Draw(m).rectangle([ins, ins, ch.width - ins, ch.height - ins], fill=255)
        cv.paste(ch, pos, m.filter(ImageFilter.GaussianBlur(ins)))
    else:
        # SIDE RULE — the host must point INTO the slide, never off-frame.
        #   Quantus art (03_pointing, 07_explaining) gestures to the VIEWER'S RIGHT,
        #   so he sits LEFT and the slide goes RIGHT.
        #   Tess art is direction-neutral (points at camera / symmetric palms),
        #   so she keeps the slide LEFT, pose RIGHT.
        # Swapping sides rather than mirroring keeps the hoodie art unflipped.
        kind, ref = visual.split(":", 1)
        vis_path = f"{SHOTS}/code_{ref}.png" if kind == "code" else f"{SHOTS}/{ref}"
        vi = Image.open(vis_path).convert("RGB")
        s = min(1120 / vi.width, 600 / vi.height)
        vi = vi.resize((int(vi.width * s), int(vi.height * s)))
        s2 = 600 / ch.height
        ch = ch.resize((int(ch.width * s2), 600))

        if who == "Q":                       # pose LEFT, slide RIGHT
            px = 60
            vx = W - vi.width - 70
        else:                                # slide LEFT, pose RIGHT
            vx = 70
            px = W - ch.width - 50
        vy, py = 260, 300

        d0 = ImageDraw.Draw(cv)
        d0.rounded_rectangle([vx - 10, vy - 10, vx + vi.width + 10, vy + vi.height + 10],
                             radius=14, outline=accent, width=3)
        cv.paste(vi, (vx, vy))
        ins = 30
        m = Image.new("L", ch.size, 0)
        ImageDraw.Draw(m).rectangle([ins, ins, ch.width - ins, ch.height - ins], fill=255)
        cv.paste(ch, (px, py), m.filter(ImageFilter.GaussianBlur(ins)))

    d = ImageDraw.Draw(cv, "RGBA")
    nf = ImageFont.truetype(FIMP, 54)
    nw = d.textlength(name, font=nf)
    d.rounded_rectangle([60, 50, 60 + nw + 70, 130], radius=16, fill=accent)
    d.text((95, 60), name, font=nf, fill=INK)
    sf_ = ImageFont.truetype(FBOLD, 40)
    sw = d.textlength(sup, font=sf_)
    sx = max(60, (W - sw) // 2)
    d.rounded_rectangle([sx - 36, 152, sx + sw + 36, 220], radius=14, fill=(0, 0, 0, 190))
    d.rectangle([sx - 36, 152, sx - 22, 220], fill=accent)
    d.text((sx, 164), sup, font=sf_, fill=WHITE)
    cf = ImageFont.truetype(FBOLD, 50)
    lines = _wrap(d, vo, cf, W - 280)
    bar = 40 + len(lines) * 62
    d.rectangle([0, H - bar, W, H], fill=(0, 0, 0, 200))
    d.rectangle([0, H - bar, 14, H], fill=accent)
    y = H - bar + 20
    for ln in lines:
        d.text((130, y), ln, font=cf, fill=WHITE)
        y += 62
    d.text((W - 380, 60), "QMM · No Cap.", font=ImageFont.truetype(FIMP, 34), fill=GOLD)
    if bid in NO_BED:
        d.text((W - 380, 112), "MUSIC OUT", font=ImageFont.truetype(FBOLD, 26), fill=RED)
    p = f"{FR}/{idx:02d}_{bid}.png"
    cv.save(p)
    return p


def build():
    os.makedirs(FR, exist_ok=True)
    sys.path.insert(0, HERE)
    from bake_discipline_vo import LINES
    text = {i: t for i, _, t in LINES}
    segs, vos, marks, t = [], [], {}, 0.0
    for i, (bid, who, pose, visual, sup) in enumerate(BEATS):
        png = frame(bid, who, pose, visual, sup, text[bid], i)
        w, _ = sf.read(f"{VO}/{bid}.wav")
        dur = len(w) / SR
        marks[bid] = t
        t += dur
        seg = f"{FR}/seg_{i:02d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", png,
                        "-t", f"{dur:.3f}", "-c:v", "libx264", "-tune", "stillimage",
                        "-pix_fmt", "yuv420p", "-r", "24", "-vf", "scale=1920:1080",
                        "-an", seg], check=True)
        segs.append(seg)
        vos.append(w.astype(np.float32))
    sf.write(f"{FR}/master_vo.wav", np.concatenate(vos), SR)
    with open(f"{FR}/segs.txt", "w") as f:
        for s in segs:
            f.write(f"file '{os.path.basename(s)}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", "segs.txt", "-c", "copy", "video_only.mp4"], check=True, cwd=FR)
    open(f"{FR}/marks.txt", "w").write(
        f"{t}\n{marks['t_g1']}\n{marks['q_asym']}\n{marks['t_close1']}\n{marks['q_bumper']}\n")
    print(f"stitched {len(segs)} beats, {t:.1f}s -> {FR}/video_only.mp4")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("cards", "all"):
        render_code_panels()
    if mode in ("build", "all"):
        build()
