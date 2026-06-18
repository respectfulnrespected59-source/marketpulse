"""Thumbnail for Explainer #5 (BTC Part 3) — the honest "beat the market" trap.

WE 'BEAT' BITCOIN -> DOWN IS DOWN, with the two real numbers:
OUR TOOL -7% vs HOLD -43%. 1280x720 JPG, brand colors, baked with PIL.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "marketing" / "thumb_05_btc.jpg"
W, H = 1280, 720
BG = (10, 13, 18)
GOLD, GREEN, RED, WHITE, DIM = (217, 176, 97), (47, 209, 128), (255, 93, 108), (236, 240, 245), (138, 153, 171)
FB = "C:/Windows/Fonts/arialbd.ttf"
FR = "C:/Windows/Fonts/arial.ttf"


def font(p, s):
    return ImageFont.truetype(p, s)


def pill(d, cx, cy, text, color, size=48):
    f = font(FB, size)
    tb = d.textbbox((0, 0), text, font=f)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    pad_x, pad_y = 34, 20
    x0, y0 = cx - tw / 2 - pad_x, cy - th / 2 - pad_y
    x1, y1 = cx + tw / 2 + pad_x, cy + th / 2 + pad_y
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, outline=color, width=4,
                        fill=(color[0], color[1], color[2], 30))
    d.text((cx, cy), text, font=f, fill=color, anchor="mm")


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    d.rectangle([0, 0, W, 8], fill=GOLD)
    d.text((60, 54), "MARKETPULSE · PROOF MODE", font=font(FB, 30), fill=GOLD)

    # the hook
    d.text((60, 130), "WE 'BEAT' BITCOIN.", font=font(FB, 78), fill=WHITE)
    d.text((60, 232), "DOWN IS DOWN.", font=font(FB, 116), fill=RED)

    # the two real numbers — both losses, that's the point
    pill(d, 250, 462, "OUR TOOL -7%", GOLD)
    d.text((505, 462), "vs", font=font(FB, 44), fill=DIM, anchor="mm")
    pill(d, 770, 462, "HOLD -43%", RED)

    # context
    d.text((60, 560), "Our tool \"beat\" Bitcoin by 35 points — by making ONE",
           font=font(FR, 34), fill=DIM)
    d.text((60, 604), "trade and hiding in cash. Why that's not a win.",
           font=font(FR, 34), fill=DIM)

    # corner tag
    d.text((W - 60, 60), "BTC", font=font(FB, 60), fill=WHITE, anchor="ra")
    d.text((W - 60, 128), "PART 3", font=font(FB, 40), fill=GOLD, anchor="ra")

    img.save(OUT, quality=92)
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
