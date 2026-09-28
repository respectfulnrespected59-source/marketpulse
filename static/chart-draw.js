/* MarketPulse — the chart's drawing layer.
 *
 * A Lightweight Charts series primitive that paints what the trader placed on
 * the tape: entry marks, trend lines, the pending trend anchor and its rubber
 * band, the snap diamond, and a faint divider at every session change. It only
 * PAINTS. What to paint comes from pcDrawSource() in chart-tools.js, and every
 * position goes through the engine's (bar, price) -> pixel mapping, so a mark
 * stays on its candle through pans, zooms and the rolling 1m tape.
 *
 * Classic script; the class is used by chart-engine.js on the first render.
 */

const PD_GOLD = "#e8c25a";

class PcDrawings {
  constructor() {
    this._p = null;
    this._views = [
      { zOrder: () => "bottom", renderer: () => ({ draw: (t) => this._paint(t, true) }) },
      { zOrder: () => "top", renderer: () => ({ draw: (t) => this._paint(t, false) }) },
    ];
  }

  attached(param) { this._p = param; }
  detached() { this._p = null; }
  updateAllViews() {}
  paneViews() { return this._views; }
  requestUpdate() { if (this._p) this._p.requestUpdate(); }

  _paint(target, background) {
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      ctx.save();
      try {
        if (background) _pdSessionDividers(ctx, mediaSize);
        else _pdUserLayer(ctx, mediaSize);
      } finally {
        ctx.restore();
      }
    });
  }
}

function _pdColorForDir(dir) {
  const c = (pc && pc.colors) || { buy: "#2fd180", sell: "#ff5d6c" };
  if (dir === "put" || dir === "short") return c.sell;
  if (dir === "call" || dir === "long") return c.buy;
  return PD_GOLD;
}

/* Dashed rule where the calendar day changes, so the overnight gap reads as
 * "new session" instead of a random jump. Intraday timeframes only: on daily
 * bars every bar is its own day. */
function _pdSessionDividers(ctx, size) {
  if (!TIME_AXIS_TFS.has(pcTape.tf) || pcTape.revealed < 2) return;
  const ts = pc.chart.timeScale();
  const key = (t) => { const d = new Date(t * 1000); return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; };
  ctx.strokeStyle = "rgba(120,180,255,0.16)";
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 5]);
  let prev = key(pcTape.ts[0]);
  for (let i = 1; i < pcTape.revealed; i++) {
    const k = key(pcTape.ts[i]);
    if (k === prev) continue;
    prev = k;
    const a = ts.logicalToCoordinate(i - 1), b = ts.logicalToCoordinate(i);
    if (a == null || b == null) continue;
    const x = Math.round((a + b) / 2) + 0.5;
    if (x < 0 || x > size.width) continue;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size.height); ctx.stroke();
  }
}

function _pdHLine(ctx, y, width, color, dash, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.setLineDash(dash);
  ctx.beginPath(); ctx.moveTo(0, Math.round(y) + 0.5); ctx.lineTo(width, Math.round(y) + 0.5); ctx.stroke();
  ctx.restore();
}

function _pdRing(ctx, x, y, r, color, filled) {
  ctx.save();
  ctx.shadowColor = color;
  ctx.shadowBlur = 6;
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
  if (filled) { ctx.globalAlpha = 0.35; ctx.fillStyle = color; ctx.fill(); ctx.globalAlpha = 1; }
  ctx.lineWidth = 2.2; ctx.strokeStyle = color; ctx.stroke();
  ctx.restore();
}

/* A stored {ts, price} as a pixel point, or null when it is off the revealed tape. */
function _pdPoint(pt) {
  if (!pt) return null;
  const idx = pcIdxOfTs(pt.ts);
  return idx < 0 ? null : pcXY(idx, pt.price);
}

function _pdUserLayer(ctx, size) {
  const src = (typeof pcDrawSource === "function") ? pcDrawSource() : null;
  if (!src) return;
  ctx.setLineDash([]);
  for (const l of src.lines) _pdTrendLine(ctx, l);
  for (const m of src.marks) _pdMark(ctx, size, m);
  if (src.anchor) {
    const p = _pdPoint(src.anchor);
    if (p) {
      _pdHLine(ctx, p.y, size.width, PD_GOLD, [2, 4], 0.55);
      _pdRing(ctx, p.x, p.y, 6.5, PD_GOLD, true);
    }
  }
  if (src.preview) _pdRubberBand(ctx, src.preview);
  if (src.snap) _pdSnapDiamond(ctx, src.snap);
}

function _pdTrendLine(ctx, l) {
  const a = _pdPoint(l.a), b = _pdPoint(l.b);
  if (!a || !b) return;
  ctx.save();
  ctx.shadowColor = PD_GOLD; ctx.shadowBlur = 5;
  ctx.strokeStyle = PD_GOLD; ctx.lineWidth = 1.8;
  ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  ctx.restore();
  for (const [p, end] of [[a, "a"], [b, "b"]]) {
    const hot = l.editing === end;
    ctx.beginPath(); ctx.arc(p.x, p.y, hot ? 5 : 3.5, 0, Math.PI * 2);
    ctx.fillStyle = PD_GOLD; ctx.globalAlpha = hot ? 0.95 : 0.7; ctx.fill(); ctx.globalAlpha = 1;
  }
}

function _pdMark(ctx, size, m) {
  const p = _pdPoint(m);
  if (!p) return;
  const color = _pdColorForDir(m.dir);
  _pdHLine(ctx, p.y, size.width, color, [2, 5], 0.35);
  _pdRing(ctx, p.x, p.y, m.editing ? 7 : 5.5, color, m.editing);
}

function _pdRubberBand(ctx, { ax, ay, bx, by }) {
  ctx.save();
  ctx.shadowColor = PD_GOLD; ctx.shadowBlur = 5;
  ctx.strokeStyle = PD_GOLD; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
  ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
  ctx.restore();
}

/* The snap target: a diamond coloured by what it grabs (high green, low red). */
function _pdSnapDiamond(ctx, { x, y, kind }) {
  const c = (pc && pc.colors) || { buy: "#2fd180", sell: "#ff5d6c" };
  const color = kind === "high" ? c.buy : kind === "low" ? c.sell : PD_GOLD;
  ctx.save();
  ctx.translate(x, y); ctx.rotate(Math.PI / 4);
  ctx.fillStyle = color; ctx.strokeStyle = "rgba(7,5,13,0.9)"; ctx.lineWidth = 1;
  ctx.fillRect(-4, -4, 8, 8); ctx.strokeRect(-4, -4, 8, 8);
  ctx.restore();
  ctx.fillStyle = color;
  ctx.font = "700 9px ui-monospace, monospace";
  ctx.fillText(kind.toUpperCase(), x + 8, y - 8);
}
