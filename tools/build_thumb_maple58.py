"""MAPLE58 explainer thumbnail — GET · KEEP · GROW · SHARE.

Bold, honest, not flexy: the codename, the 4 limbs, the "$300 -> ?" hook, and a
faint green 'come-up' staircase behind it. 1280x720 JPG, brand colors, PIL.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "marketing" / "thumb_maple58.jpg"
W, H = 1280, 720
BG = (10, 13, 18)
GOLD, GREEN, RED, AMBER, WHITE, DIM = (245, 170, 60), (64, 200, 130), (240, 90, 90), (245, 170, 60), (236, 240, 245), (138, 153, 171)
FB = "C:/Windows/Fonts/arialbd.ttf"
FR = "C:/Windows/Fonts/arial.ttf"


def font(p, s):
    return ImageFont.truetype(p, s)


def pill(d, cx, cy, text, color, size=40):
    fnt = font(FB, size)
    tb = d.textbbox((0, 0), text, font=fnt)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    px, py = 26, 16
    d.rounded_rectangle([cx - tw / 2 - px, cy - th / 2 - py, cx + tw / 2 + px, cy + th / 2 + py],
                        radius=16, outline=color, width=4, fill=(color[0], color[1], color[2], 38))
    d.text((cx, cy - 2), text, font=fnt, fill=color, anchor="mm")


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # faint "come-up" staircase (green) + the ruin line (red), background motif
    steps = [(720, 560), (790, 560), (790, 510), (880, 510), (880, 540), (960, 540),
             (960, 470), (1050, 470), (1050, 430), (1140, 430), (1140, 380), (1230, 380)]
    d.line(steps, fill=(64, 200, 130, 90), width=6, joint="curve")
    d.line([(720, 560), (820, 600), (900, 650), (1000, 700)], fill=(240, 90, 90, 70), width=5)

    d.rectangle([0, 0, W, 8], fill=GOLD)
    d.text((60, 44), "MARKETPULSE  ·  an honest options tool", font=font(FB, 30), fill=GOLD)

    d.text((58, 92), "MAPLE58", font=font(FB, 168), fill=GOLD)

    # the 4 limbs
    y = 320
    pill(d, 150, y, "GET", GREEN)
    pill(d, 360, y, "KEEP", AMBER)
    pill(d, 590, y, "GROW", GREEN)
    pill(d, 845, y, "SHARE", GOLD)

    # the honest hook
    d.text((60, 430), "$300", font=font(FB, 150), fill=WHITE)
    x = 60 + d.textlength("$300", font=font(FB, 150))
    d.text((x + 30, 430), "→ ?", font=font(FB, 150), fill=GREEN)

    # honest bottom line
    d.text((60, 632), "honest options method  ·  most probes lose  ·  educational, not advice",
           font=font(FR, 30), fill=DIM)

    # name origin nod (corner) — MArket PuLsE -> MAPLE
    d.text((W - 55, 52), "MArket", font=font(FB, 50), fill=WHITE, anchor="ra")
    d.text((W - 55, 110), "PuLsE", font=font(FB, 50), fill=GOLD, anchor="ra")

    img.save(OUT, quality=92)
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
