"""Generate MarketPulse PWA / home-screen icons.

Dark-luxury brand: near-black field, gold diamond mark, a green market
"pulse" candlestick line. Renders one 1024px master, then downscales to the
sizes a PWA + iOS need. Output PNGs live in static/icons/ and are committed
as plain static assets (the app itself stays pure-stdlib at runtime -- PIL is
only used here, offline, to bake the icons).

Run:  python tools/build_pwa_icons.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "static", "icons")

BG = (10, 13, 18)          # --bg  #0a0d12
BG_GLOW = (26, 22, 14)     # warm gold glow toward center
GOLD = (217, 176, 97)      # --gold #d9b061
GREEN = (47, 209, 128)     # --buy  #2fd180
RED = (255, 93, 108)       # --sell #ff5d6c

MASTER = 1024


def _radial_bg(size: int, rounded: bool) -> Image.Image:
    """Dark field with a soft central gold glow. rounded -> squircle mask."""
    img = Image.new("RGB", (size, size), BG)
    px = img.load()
    cx = cy = size / 2
    maxd = (size / 2) * 1.15
    for y in range(size):
        for x in range(size):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            t = max(0.0, 1.0 - dist) ** 2 * 0.55
            px[x, y] = (
                int(BG[0] + (BG_GLOW[0] - BG[0]) * t),
                int(BG[1] + (BG_GLOW[1] - BG[1]) * t),
                int(BG[2] + (BG_GLOW[2] - BG[2]) * t),
            )
    if rounded:
        mask = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, size - 1, size - 1],
                             radius=int(size * 0.22), fill=255)
        out = Image.new("RGB", (size, size), BG)
        out.paste(img, (0, 0), mask)
        img = out
    return img


def _diamond(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float,
             fill=None, outline=None, width: int = 1) -> None:
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    draw.polygon(pts, fill=fill, outline=outline, width=width)


def _draw_mark(img: Image.Image, scale: float) -> None:
    """Gold diamond mark + a green pulse candlestick line across it."""
    size = img.size[0]
    d = ImageDraw.Draw(img, "RGBA")
    cx = cy = size / 2
    r = size * 0.30 * scale

    lw = max(4, int(size * 0.022))
    _diamond(d, cx, cy, r, outline=GOLD, width=lw)
    _diamond(d, cx, cy, r * 0.52, fill=GOLD)
    _diamond(d, cx, cy, r * 0.20, fill=BG)

    span = r * 1.9
    x0 = cx - span / 2
    step = span / 6
    base = cy + r * 0.15
    heights = [0.30, -0.10, 0.42, 0.05, 0.60, 0.22, 0.85]
    plw = max(3, int(size * 0.014))
    prev = None
    for i, h in enumerate(heights):
        x = x0 + step * i
        y = base - (r * h)
        if prev is not None:
            d.line([prev, (x, y)], fill=(*GREEN, 235), width=plw)
        prev = (x, y)
    for i in (2, 4, 6):
        x = x0 + step * i
        y = base - (r * heights[i])
        col = GREEN if i != 2 else RED
        d.line([(x, y - r * 0.12), (x, y + r * 0.10)], fill=(*col, 200),
               width=max(2, int(size * 0.008)))


def build_icon(size: int, rounded: bool = False, maskable: bool = False) -> Image.Image:
    """maskable -> extra safe padding so an Android mask never clips the mark."""
    master = _radial_bg(MASTER, rounded=rounded)
    _draw_mark(master, scale=0.72 if maskable else 1.0)
    return master.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    jobs = [
        ("icon-192.png", 192, False, False),
        ("icon-512.png", 512, False, False),
        ("icon-maskable-512.png", 512, False, True),
        ("apple-touch-icon.png", 180, True, False),   # iOS wants a filled square
        ("favicon-32.png", 32, False, False),
    ]
    for name, size, rounded, maskable in jobs:
        img = build_icon(size, rounded=rounded, maskable=maskable)
        img.save(os.path.join(OUT, name))
        print(f"  wrote {name} ({size}px)")
    print(f"\n  PWA icons -> {OUT}")


if __name__ == "__main__":
    main()
