"""Thumbnail for Explainer #7 (UBER Part 5) — the clean win.

IT FINALLY BEAT THE MARKET, with the real numbers: TOOL +12.7% vs HOLD +2.5%.
1280x720 JPG, brand colors, baked with PIL.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "marketing" / "thumb_07_uber.jpg"
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

    # the hook — the clean win
    d.text((60, 130), "IT FINALLY BEAT", font=font(FB, 80), fill=WHITE)
    d.text((60, 232), "THE MARKET.", font=font(FB, 124), fill=GREEN)

    # the real numbers — tool > hold for once
    pill(d, 250, 462, "TOOL +12.7%", GREEN)
    d.text((505, 462), "vs", font=font(FB, 44), fill=DIM, anchor="mm")
    pill(d, 770, 462, "HOLD +2.5%", GOLD)

    # context
    d.text((60, 560), "A real win on Uber — and the one market regime where",
           font=font(FR, 34), fill=DIM)
    d.text((60, 604), "this tool actually earns its keep.",
           font=font(FR, 34), fill=DIM)

    # corner tag
    d.text((W - 60, 60), "UBER", font=font(FB, 56), fill=WHITE, anchor="ra")
    d.text((W - 60, 124), "PART 5", font=font(FB, 40), fill=GOLD, anchor="ra")

    img.save(OUT, quality=92)
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
