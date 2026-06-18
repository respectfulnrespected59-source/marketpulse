"""MAPLE58 explainer animations — NEON-3D CANDLESTICK edition.

Candle-style charts, glowing + blinking + faux-3D (drop shadow, sheen, pulsing
glow on the live candle), built bar-by-bar. Dark trading-terminal vibe.
matplotlib FuncAnimation -> mp4. 1920x1080, 30fps. No emoji (tofu boxes).

Clips into marketing/anim/:
  candle_run       hero blinking candlestick rip (hook)
  candle_squeeze   candles coil inside tightening bands, then breakout
  candle_move      candles + expected-move cone
  candle_probe     candles with blinking probe entry, then escalate adds
  candle_backtest  candles tagged with W / L markers (proof mode)
  payoff_call      neon-3D call debit-spread payoff
  payoff_strangle  neon-3D strangle payoff
  probe_curve      neon cost-vs-delta curve with the d0.25 floor
  pot_ladder       neon-3D pot climb vs the red ruin line
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Rectangle
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "marketing" / "anim"
OUT.mkdir(parents=True, exist_ok=True)

W, H, DPI, FPS = 1920, 1080, 120, 30
BG = "#0a0d12"
PANEL = "#0e131b"
GRID = "#1b2533"
GREEN = "#3fe08a"
RED = "#ff5a6a"
GOLD = "#f5aa3c"
CYAN = "#46d6ff"
WHITE = "#eceff5"
DIM = "#8a99ab"

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": PANEL, "savefig.facecolor": BG,
    "text.color": WHITE, "axes.labelcolor": DIM, "xtick.color": DIM,
    "ytick.color": DIM, "font.family": "DejaVu Sans", "font.size": 15,
})


def clamp(a):
    return min(1.0, max(0.0, float(a)))


def new_fig():
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    ax = fig.add_axes([0.07, 0.10, 0.88, 0.78])
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.grid(True, color=GRID, lw=0.7, alpha=0.5)
    ax.tick_params(length=0)
    return fig, ax


def title(ax, text, sub, accent=GOLD):
    ax.text(0.0, 1.10, text, transform=ax.transAxes, fontsize=30, fontweight="bold",
            color=WHITE, va="bottom")
    ax.text(0.0, 1.04, sub, transform=ax.transAxes, fontsize=16, color=accent, va="bottom")


def glow_line(ax, x, y, color, lw=2.6, layers=5):
    """Neon glow: stack translucent wide strokes under a bright core."""
    for i in range(layers, 0, -1):
        a = clamp(0.05 + 0.04 * (layers - i))
        ax.plot(x, y, color=color, lw=lw + i * 3.2, alpha=a,
                solid_capstyle="round", zorder=3)
    ax.plot(x, y, color=color, lw=lw, zorder=4, solid_capstyle="round")


def draw_candle(ax, x, o, h, l, c, w=0.34, glow=0.0, live=False):
    """One faux-3D neon candle. glow in [0,1] pulses the halo; live adds a dot."""
    up = c >= o
    col = GREEN if up else RED
    top, bot = max(o, c), min(o, c)
    body_h = max(h * 0.004, top - bot)
    # drop shadow (3D depth) behind the body, offset down-right
    ax.add_patch(Rectangle((x - w / 2 + 0.07, bot - body_h * 0.05), w, body_h,
                 facecolor="#04070b", edgecolor="none", alpha=0.55, zorder=2))
    # wick glow
    glow_line(ax, [x, x], [l, h], col, lw=2.0, layers=3)
    # glow halo around body
    if glow > 0:
        ax.add_patch(Rectangle((x - w / 2 - 0.10, bot - body_h * 0.12), w + 0.20,
                     body_h * 1.24, facecolor=col, edgecolor="none",
                     alpha=clamp(0.10 + 0.22 * glow), zorder=3))
    # body
    ax.add_patch(Rectangle((x - w / 2, bot), w, body_h, facecolor=col,
                 edgecolor=WHITE, lw=0.8, alpha=0.95, zorder=5))
    # 3D sheen: bright top edge
    ax.add_patch(Rectangle((x - w / 2, top - body_h * 0.12), w, body_h * 0.12,
                 facecolor="white", edgecolor="none", alpha=0.18, zorder=6))
    if live:
        ax.scatter([x], [c], s=120 + 240 * glow, color=col, edgecolors="white",
                   lw=1.2, zorder=7, alpha=clamp(0.55 + 0.45 * glow))


def synth_ohlc(n, seed, drift=0.0, vol=1.0, start=100.0):
    rng = np.random.default_rng(seed)
    o = np.zeros(n); h = np.zeros(n); l = np.zeros(n); c = np.zeros(n)
    px = start
    for i in range(n):
        o[i] = px
        c[i] = max(1.0, px + rng.normal(drift, vol))
        h[i] = max(o[i], c[i]) + abs(rng.normal(0, vol * 0.8))
        l[i] = min(o[i], c[i]) - abs(rng.normal(0, vol * 0.8))
        px = c[i]
    return o, h, l, c


def render(name, frames, draw, hold=18):
    fig, ax = new_fig()
    total = frames + hold

    def upd(fr):
        f = min(fr, frames - 1)
        for coll in (ax.patches, ax.lines, ax.collections, ax.texts):
            for a in list(coll):
                a.remove()
        draw(ax, f, fr)
        return []

    anim = FuncAnimation(fig, upd, frames=total, blit=False, interval=1000 / FPS)
    out = OUT / f"{name}.mp4"
    anim.save(str(out), fps=FPS, dpi=DPI, writer="ffmpeg",
              savefig_kwargs={"facecolor": BG},
              extra_args=["-pix_fmt", "yuv420p", "-vcodec", "libx264", "-crf", "20"])
    plt.close(fig)
    print(f"  {name}.mp4")


def _candles_progressive(ax, o, h, l, c, upto, fr, accent, ttl, sub, marks=None):
    title(ax, ttl, sub, accent)
    n = len(o)
    ax.set_xlim(-0.8, n - 0.2)
    pad = (h.max() - l.min()) * 0.14
    ax.set_ylim(l.min() - pad, h.max() + pad)
    ax.set_xticks([])
    pulse = 0.5 + 0.5 * np.sin(fr * 0.5)
    for i in range(upto + 1):
        live = (i == upto)
        draw_candle(ax, i, o[i], h[i], l[i], c[i], glow=(pulse if live else 0.0), live=live)
    if marks:
        for mi, (label, col) in marks.items():
            if mi <= upto:
                blink = 0.45 + 0.55 * (0.5 + 0.5 * np.sin(fr * 0.6 + mi))
                ax.scatter([mi], [c[mi]], s=300, marker="o", facecolors="none",
                           edgecolors=col, lw=2.8, alpha=clamp(blink), zorder=8)
                ax.annotate(label, (mi, c[mi]), textcoords="offset points",
                            xytext=(0, 30), ha="center", color=col, fontsize=14,
                            fontweight="bold", alpha=clamp(blink))


def clip_candle_run():
    o, h, l, c = synth_ohlc(26, 7, drift=0.45, vol=2.1, start=80)

    def draw(ax, f, fr):
        _candles_progressive(ax, o, h, l, c, min(f, len(o) - 1), fr, GOLD,
                             "MAPLE58", "read the tape -- survive first, then climb")
    render("candle_run", len(o) + 4, draw)


def clip_candle_squeeze():
    n = 24
    o, h, l, c = synth_ohlc(n, 3, drift=0.0, vol=0.5, start=100)
    for i in range(8, 17):
        c[i] = 100 + (c[i] - 100) * 0.25
        o[i] = 100 + (o[i] - 100) * 0.25
        h[i] = max(o[i], c[i]) + 0.4
        l[i] = min(o[i], c[i]) - 0.4
    for i in range(17, n):
        o[i] = c[i - 1]; c[i] = o[i] + 2.6
        h[i] = c[i] + 0.5; l[i] = o[i] - 0.3

    def draw(ax, f, fr):
        upto = min(f, n - 1)
        _candles_progressive(ax, o, h, l, c, upto, fr, CYAN,
                             "THE SQUEEZE", "volatility coils tight, then fires")
        xs = np.arange(n)
        width = np.where((xs >= 8) & (xs < 17), 1.4, 4.0)
        k = min(upto + 1, n)
        ax.fill_between(xs[:k], (c - width - 1.5)[:k], (c + width + 1.5)[:k],
                        color=CYAN, alpha=0.07, zorder=1)
        glow_line(ax, xs[:k], (c + width + 1.5)[:k], CYAN, lw=1.4, layers=2)
        glow_line(ax, xs[:k], (c - width - 1.5)[:k], CYAN, lw=1.4, layers=2)
        if upto >= 17:
            ax.text(18.5, c[min(upto, n - 1)] + 3, "BREAKOUT", color=GREEN, fontsize=20,
                    fontweight="bold", alpha=clamp(0.4 + 0.6 * (0.5 + 0.5 * np.sin(fr * 0.7))))
    render("candle_squeeze", n + 6, draw)


def clip_candle_move():
    n = 20
    o, h, l, c = synth_ohlc(n, 11, drift=0.2, vol=1.4, start=100)

    def draw(ax, f, fr):
        upto = min(f, n - 1)
        _candles_progressive(ax, o, h, l, c, upto, fr, GOLD,
                             "EXPECTED MOVE", "how far a normal week actually reaches")
        last = c[min(upto, n - 1)]
        if upto >= 1:
            band, xs = 5.0, [upto, n + 1]
            ax.fill_between(xs, [last - band] * 2, [last + band] * 2, color=GOLD, alpha=0.10, zorder=1)
            glow_line(ax, xs, [last + band] * 2, GOLD, lw=1.4, layers=2)
            glow_line(ax, xs, [last - band] * 2, GOLD, lw=1.4, layers=2)
            ax.text(n - 1.5, last + band + 0.6, "+1 sigma", color=GOLD, fontsize=13, fontweight="bold")
            ax.text(n - 1.5, last - band - 1.4, "-1 sigma", color=GOLD, fontsize=13, fontweight="bold")
    render("candle_move", n + 6, draw)


def clip_candle_probe():
    n = 22
    o, h, l, c = synth_ohlc(n, 21, drift=0.55, vol=1.6, start=70)

    def draw(ax, f, fr):
        upto = min(f, n - 1)
        _candles_progressive(ax, o, h, l, c, upto, fr, GREEN,
                             "PROBE  ->  READ  ->  ESCALATE", "small bet first, add only to a winner",
                             marks={6: ("PROBE $60", GOLD), 12: ("READ", CYAN), 17: ("ESCALATE", GREEN)})
    render("candle_probe", n + 6, draw)


def clip_candle_backtest():
    n = 22
    o, h, l, c = synth_ohlc(n, 33, drift=0.05, vol=1.7, start=100)
    wins, losses = {3, 7, 12, 16, 20}, {5, 9, 14, 18}

    def draw(ax, f, fr):
        upto = min(f, n - 1)
        _candles_progressive(ax, o, h, l, c, upto, fr, GOLD,
                             "PROOF MODE", "every trade -- the wins AND the losses, net of fees")
        for i in range(upto + 1):
            if i in wins:
                ax.annotate("W", (i, h[i]), textcoords="offset points", xytext=(0, 12),
                            ha="center", color=GREEN, fontsize=15, fontweight="bold")
            elif i in losses:
                ax.annotate("L", (i, l[i]), textcoords="offset points", xytext=(0, -22),
                            ha="center", color=RED, fontsize=15, fontweight="bold")
        ax.text(0.99, 1.04, f"{len(wins)}W / {len(losses)}L  net of fees", transform=ax.transAxes,
                ha="right", color=DIM, fontsize=14, alpha=clamp(0.6 + 0.4 * (0.5 + 0.5 * np.sin(fr * 0.5))))
    render("candle_backtest", n + 6, draw)


def _neon_payoff(ax, xs, ys, fr, accent, ttl, sub, be=None):
    title(ax, ttl, sub, accent)
    ax.axhline(0, color=DIM, lw=1.0, alpha=0.6)
    ax.set_xlim(xs.min(), xs.max())
    ax.set_ylim(ys.min() * 1.25 - 1, ys.max() * 1.25 + 1)
    pos = np.where(ys >= 0, ys, 0)
    neg = np.where(ys < 0, ys, 0)
    ax.fill_between(xs + (xs[1] - xs[0]) * 0.4, pos - abs(ys).max() * 0.03, 0,
                    color="#04070b", alpha=0.5, zorder=1)
    ax.fill_between(xs, pos, 0, color=GREEN, alpha=0.16, zorder=2)
    ax.fill_between(xs, neg, 0, color=RED, alpha=0.16, zorder=2)
    glow_line(ax, xs, ys, accent, lw=3.0, layers=5)
    if be is not None:
        blink = 0.4 + 0.6 * (0.5 + 0.5 * np.sin(fr * 0.6))
        for b in (be if isinstance(be, (list, tuple)) else [be]):
            ax.scatter([b], [0], s=220, facecolors="none", edgecolors=GOLD, lw=2.6,
                       alpha=clamp(blink), zorder=6)
            ax.annotate("breakeven", (b, 0), textcoords="offset points", xytext=(0, 18),
                        ha="center", color=GOLD, fontsize=13, fontweight="bold", alpha=clamp(blink))


def clip_payoff_call():
    xs = np.linspace(80, 140, 240)
    pay = np.clip(xs - 100, 0, None) - np.clip(xs - 115, 0, None) - 5

    def draw(ax, f, fr):
        cut = max(2, int(len(xs) * clamp((f + 1) / 60)))
        _neon_payoff(ax, xs[:cut], pay[:cut], fr, GREEN, "CALL DEBIT SPREAD",
                     "defined risk, defined reward -- direction is clear", be=105)
    render("payoff_call", 64, draw)


def clip_payoff_strangle():
    xs = np.linspace(70, 150, 260)
    pay = np.clip(xs - 120, 0, None) + np.clip(100 - xs, 0, None) - 6

    def draw(ax, f, fr):
        cut = max(2, int(len(xs) * clamp((f + 1) / 60)))
        _neon_payoff(ax, xs[:cut], pay[:cut], fr, GOLD, "LONG STRANGLE",
                     "a move is coming -- you don't care which way", be=[94, 126])
    render("payoff_strangle", 64, draw)


def clip_probe_curve():
    x = np.linspace(0, 10, 220)
    cost = 700 * np.exp(-0.45 * x) + 25
    delta = np.clip(0.9 * np.exp(-0.30 * x), 0, 0.95)

    def draw(ax, f, fr):
        title(ax, "WHY CHEAPEST ISN'T BEST", "go too far out and delta dies -- a dead lottery ticket", GOLD)
        cut = max(2, int(len(x) * clamp((f + 1) / 60)))
        ax.set_xlim(0, 10); ax.set_ylim(0, 760)
        ax.set_xlabel("further out of the money  ->  cheaper")
        glow_line(ax, x[:cut], cost[:cut], CYAN, lw=2.8, layers=4)
        glow_line(ax, x[:cut], delta[:cut] * 760, GOLD, lw=2.8, layers=4)
        ax.axhline(0.25 * 760, color=RED, lw=1.6, ls="--", alpha=0.8)
        blink = 0.4 + 0.6 * (0.5 + 0.5 * np.sin(fr * 0.6))
        ax.text(5.2, 0.25 * 760 + 18, "delta 0.25 floor -- below this it's a lottery",
                color=RED, fontsize=14, fontweight="bold", alpha=clamp(blink))
        j = min(cut - 1, len(x) - 1)
        ax.text(9.8, cost[j] + 14, "cost", color=CYAN, fontsize=14, ha="right", fontweight="bold")
        ax.text(9.8, delta[j] * 760 + 14, "delta (reactivity)", color=GOLD, fontsize=14,
                ha="right", fontweight="bold")
    render("probe_curve", 64, draw)


def clip_pot_ladder():
    steps = np.arange(0, 13)
    disc = 300 * (1.06 ** steps)
    ruin = np.concatenate([[300], 300 * (1.55 ** np.arange(1, 6)), np.zeros(7)])
    ruin[6:] = 0

    def draw(ax, f, fr):
        title(ax, "DISCIPLINE vs RUIN",
              "$300 -> $333 one probe at a time   vs   the revenge-sizer at zero", GREEN)
        upto = min(f, len(steps) - 1)
        ax.set_xlim(-0.4, 12.4); ax.set_ylim(0, 760)
        ax.set_xlabel("probes")
        glow_line(ax, steps[:upto + 1], disc[:upto + 1], GREEN, lw=3.0, layers=5)
        glow_line(ax, steps[:upto + 1], ruin[:upto + 1], RED, lw=2.6, layers=4)
        blink = 0.5 + 0.5 * np.sin(fr * 0.5)
        ax.scatter([steps[upto]], [disc[upto]], s=140 + 260 * blink, color=GREEN,
                   edgecolors="white", lw=1.2, zorder=7, alpha=clamp(0.6 + 0.4 * blink))
        if upto >= 6:
            ax.scatter([6], [0], s=200, color=RED, marker="X", zorder=7)
            ax.text(6, 24, "blown up", color=RED, fontsize=14, fontweight="bold", ha="center")
        ax.text(upto + 0.1, disc[upto] + 14, f"${disc[upto]:.0f}", color=GREEN,
                fontsize=15, fontweight="bold")
    render("pot_ladder", len(steps) + 6, draw)


if __name__ == "__main__":
    print("Rendering neon-3D candlestick clips ...")
    clip_candle_run()
    clip_candle_squeeze()
    clip_candle_move()
    clip_candle_probe()
    clip_candle_backtest()
    clip_payoff_call()
    clip_payoff_strangle()
    clip_probe_curve()
    clip_pot_ladder()
    print("DONE ->", OUT)
