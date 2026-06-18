"""MAPLE58 'how to run it' thumbnail — the I-bought-it-now-what hook.

Speaks to the confused buyer: WHAT IS IT? + HOW DO I RUN IT? with a tiny
zip -> folder -> browser step motif. 1280x720 JPG, brand colors, PIL.
Mirrors build_thumb_maple58.py.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "marketing" / "thumb_maple58_howto.jpg"
W, H = 1280, 720
BG = (10, 13, 18)
GOLD, GREEN, WHITE, DIM = (245, 170, 60), (64, 200, 130), (236, 240, 245), (138, 153, 171)
FB = "C:/Windows/Fonts/arialbd.ttf"
FR = "C:/Windows/Fonts/arial.ttf"


def font(p, s):
    return ImageFont.truetype(p, s)


def chip(d, cx, cy, text, color, size=34):
    fnt = font(FB, size)
    tb = d.textbbox((0, 0), text, font=fnt)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    px, py = 22, 14
    d.rounded_rectangle([cx - tw / 2 - px, cy - th / 2 - py, cx + tw / 2 + px, cy + th / 2 + py],
                        radius=14, fill=(color[0], color[1], color[2], 32), outline=color, width=3)
    d.text((cx, cy - 2), text, font=fnt, fill=color, anchor="mm")
    return tw + 2 * px


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    d.rectangle([0, 0, W, 8], fill=GOLD)
    d.text((60, 40), "MARKETPULSE  ·  codename MAPLE58", font=font(FB, 28), fill=GOLD)

    # the hook — the question every buyer actually has
    d.text((58, 92), "I GOT IT...", font=font(FB, 96), fill=WHITE)
    d.text((58, 200), "NOW WHAT?", font=font(FB, 130), fill=GOLD)

    # the promise
    d.text((60, 372), "what it is  +  how to run it on your computer",
           font=font(FB, 40), fill=GREEN)

    # tiny step motif: zip -> folder -> browser
    y = 478
    x = 60
    x += chip(d, x + 90, y, "1 · unzip", DIM) + 28
    d.text((x, y), "→", font=font(FB, 40), fill=DIM, anchor="lm"); x += 50
    x += chip(d, x + 120, y, "2 · run.bat", GREEN) + 28
    d.text((x, y), "→", font=font(FB, 40), fill=DIM, anchor="lm"); x += 50
    chip(d, x + 150, y, "3 · localhost:8000", GREEN)

    # honest footer
    d.text((60, 636), "no account · no fees · runs on your machine · most probes lose · not advice",
           font=font(FR, 27), fill=DIM)

    # name origin nod
    d.text((W - 55, 50), "MArket", font=font(FB, 46), fill=WHITE, anchor="ra")
    d.text((W - 55, 104), "PuLsE", font=font(FB, 46), fill=GOLD, anchor="ra")

    img.save(OUT, quality=92)
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
