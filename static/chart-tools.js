/* MarketPulse — chart interaction tools.
 *
 * Mark an entry, draw a trend line, retouch or delete either, plus the
 * toolbar, indicator menu, replay transport and keyboard shortcuts. Pan, zoom
 * and the crosshair belong to the chart engine now (Lightweight Charts); this
 * file only takes the pointer when a drawing tool, or a grab on something the
 * trader drew, actually needs it.
 *
 * Classic script sharing one global scope with chart.js and app.js; everything
 * here is a declaration and nothing runs at load time.
 */

/* ---- Drawing tools: state ------------------------------------------------ */

// Tool mode: "none" | "mark" | "line".
// Trend line UX: a click drops a pending gold anchor at the target price. Then
// press-and-drag ANYWHERE on the chart rubber-bands a line from the anchor to
// the pointer; release commits it. A plain click just relocates the anchor.
let ltcTool = "none";
let trendAnchor = null;        // {ts, price} — the pending line's first point
let trendPreview = null;       // {ax, ay, bx, by} rubber band, in pane pixels
let gesture = null;            // the pointer gesture this file owns, if any
let editPreview = null;        // {ts, price} while an existing point is dragged
let hoverSnap = null;          // snap diamond under the pointer while a tool is armed
let altHeld = false;           // hold Alt to place freely, without the snap
const DRAG_THRESHOLD_PX = 4;   // how far the pointer must travel to count as a drag

// Painting reads marks and lines on every frame of a pan; parsing localStorage
// that often is waste. Cached per symbol and dropped whenever we write.
let _drawCache = { sym: null, marks: [], lines: [] };
function _drawChanged() { _drawCache = { sym: null, marks: [], lines: [] }; pcRedrawDrawings(); }

function _toolSym() {
  return String((liveLast.data && liveLast.data.symbol) || $("#liveSymbol").value.trim()).toUpperCase();
}

/* What the drawing layer (chart-draw.js) paints, with any drag in progress
 * applied — the stored point only changes when the drag is released. */
function pcDrawSource() {
  // During a lesson the chart shows the lesson's drawings; the user's are hidden, never touched.
  if (lessonView) return { marks: lessonView.marks, lines: lessonView.lines, anchor: null, preview: null, snap: null };
  const sym = liveLast.data && liveLast.data.symbol;
  if (!sym) return null;
  if (_drawCache.sym !== sym) _drawCache = { sym, marks: getUserMarks(sym), lines: getUserLines(sym) };
  let { marks, lines } = _drawCache;
  const hit = gesture && gesture.kind === "edit" && gesture.moved && editPreview ? gesture.hit : null;
  if (hit && hit.kind === "mark") {
    marks = marks.map((m, i) => (i === hit.idx ? { ...m, ...editPreview, editing: true } : m));
  } else if (hit) {
    const end = hit.kind === "lineA" ? "a" : "b";
    lines = lines.map((l, i) => (i === hit.idx ? { ...l, [end]: { ...editPreview }, editing: end } : l));
  }
  return { marks, lines, anchor: trendAnchor, preview: trendPreview, snap: hoverSnap };
}

/* ---- pointer geometry ------------------------------------------------------ */

function _localXY(evt) {
  const r = $("#liveTradeChart").getBoundingClientRect();
  return { x: evt.clientX - r.left, y: evt.clientY - r.top };
}

function _inPane(x, y) {
  const p = pcPaneRect();
  return !!p && x >= 0 && y >= 0 && x <= p.w && y <= p.h;
}

/* The point a click means: the nearest open/high/low/close when one is close
 * enough, else exactly where the pointer is. Alt places freely. */
function _pointFor(x, y) {
  if (!altHeld) {
    const s = pcSnap(x, y);
    if (s) return s;
  }
  const p = pcPointAt(x, y);
  if (!p) return null;
  const xy = pcXY(p.idx, p.price);
  return { ...p, x: xy ? xy.x : x, y };
}

/* An existing mark or trend-line end under the pointer — grabbable from ANY
 * tool, so a point can be retouched without switching modes. */
function _hitTest(x, y) {
  if (lessonView) return null;             // nothing to grab (or Alt-delete) in a lesson
  const sym = liveLast.data && liveLast.data.symbol;
  if (!sym) return null;
  const at = (p) => { const i = pcIdxOfTs(p && p.ts); return i < 0 ? null : pcXY(i, p.price); };
  const near = (p) => { const xy = at(p); return !!xy && Math.hypot(xy.x - x, xy.y - y) <= PC_HIT_PX; };
  const marks = getUserMarks(sym);
  for (let i = marks.length - 1; i >= 0; i--) {
    if (near(marks[i])) return { kind: "mark", idx: i, sym, point: marks[i] };
  }
  const lines = getUserLines(sym);
  for (let i = lines.length - 1; i >= 0; i--) {
    if (near(lines[i].a)) return { kind: "lineA", idx: i, sym, point: lines[i].a };
    if (near(lines[i].b)) return { kind: "lineB", idx: i, sym, point: lines[i].b };
  }
  return null;
}

function _deleteHit(hit) {
  const k = _ltcKeys(hit.sym);
  if (hit.kind === "mark") {
    const marks = getUserMarks(hit.sym);
    marks.splice(hit.idx, 1);
    _writeArr(k.marks, marks);
  } else {
    const lines = getUserLines(hit.sym);
    lines.splice(hit.idx, 1);
    _writeArr(k.lines, lines);
  }
  _drawChanged();
  if (typeof toast === "function") toast("sell", "Deleted");
}

function _commitEdit(hit, to) {
  const k = _ltcKeys(hit.sym);
  if (hit.kind === "mark") {
    const marks = getUserMarks(hit.sym);
    if (!marks[hit.idx]) return;
    marks[hit.idx] = { ...marks[hit.idx], ts: to.ts, price: to.price };
    _writeArr(k.marks, marks);
  } else {
    const end = hit.kind === "lineA" ? "a" : "b";
    const lines = getUserLines(hit.sym);
    if (!lines[hit.idx]) return;
    lines[hit.idx] = { ...lines[hit.idx], [end]: { ts: to.ts, price: to.price } };
    _writeArr(k.lines, lines);
  }
  _drawChanged();
}

/* ---- pointer gestures -------------------------------------------------------- */

function _setHint(text) {
  const hint = $("#ltcHint");
  if (!hint) return;
  hint.hidden = !text;
  hint.textContent = text || "";
}

function _setTool(t) {
  ltcTool = t;
  // Any tool switch drops an in-flight trend gesture.
  trendAnchor = null; trendPreview = null; gesture = null; hoverSnap = null;
  const wrap = $("#liveTradeWrap");
  if (wrap) {
    wrap.classList.toggle("tool-mark", t === "mark");
    wrap.classList.toggle("tool-line", t === "line");
    wrap.classList.toggle("tool-active", t !== "none");
  }
  document.querySelectorAll(".ltc-tool[data-tool]").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.tool === t);
    b.setAttribute("aria-pressed", String(b.dataset.tool === t));
  });
  _setHint(t === "mark" ? "Click the chart to drop an entry mark"
    : t === "line" ? "Click the target price, then press & drag to draw the trend" : "");
  // While a tool is armed a drag draws instead of panning; the wheel still zooms.
  pcSetInteractive(t === "none");
  pcRedrawDrawings();
}

function _claim(evt) {
  evt.stopPropagation();
  evt.preventDefault();
  pcSetInteractive(false);
}

function _onPointerDown(evt) {
  if (lessonView) return;                  // lessons are read-only; the chart still pans
  if (evt.button > 0 || !liveLast.ok) return;
  const { x, y } = _localXY(evt);
  if (!_inPane(x, y)) return;
  const hit = _hitTest(x, y);
  if (hit && evt.altKey) {
    _deleteHit(hit);
    gesture = { kind: "done", startX: x, startY: y, moved: false };
  } else if (hit) {
    gesture = { kind: "edit", hit, startX: x, startY: y, moved: false };
    editPreview = { ts: hit.point.ts, price: hit.point.price };
  } else if (ltcTool === "mark") {
    gesture = { kind: "mark", startX: x, startY: y, moved: false };
  } else if (ltcTool === "line") {
    gesture = { kind: trendAnchor ? "trend" : "anchor", startX: x, startY: y, moved: false };
  } else {
    return;                      // nothing of ours under the pointer: let the chart pan
  }
  _claim(evt);
}

function _onPointerMove(evt) {
  const el = $("#liveTradeChart");
  if (!liveLast.ok || !el) return;
  const { x, y } = _localXY(evt);
  if (gesture) {
    if (!gesture.moved && Math.hypot(x - gesture.startX, y - gesture.startY) > DRAG_THRESHOLD_PX) {
      gesture.moved = true;
    }
    if (!gesture.moved) return;
    const p = _pointFor(x, y);
    hoverSnap = p && p.kind ? p : null;
    if (gesture.kind === "edit" && p) {
      editPreview = { ts: p.ts, price: p.price };
      el.classList.add("is-grabbing");
    } else if (gesture.kind === "trend" && trendAnchor) {
      const i = pcIdxOfTs(trendAnchor.ts);
      const a = i < 0 ? null : pcXY(i, trendAnchor.price);
      if (a) trendPreview = { ax: a.x, ay: a.y, bx: p ? p.x : x, by: p ? p.y : y };
    }
    pcRedrawDrawings();
    return;
  }
  const over = _inPane(x, y) && evt.target && el.contains(evt.target);
  const hit = over ? _hitTest(x, y) : null;
  el.classList.toggle("is-grab", !!hit && !evt.altKey);
  el.classList.toggle("is-delete", !!hit && evt.altKey);
  const snap = over && ltcTool !== "none" && !altHeld ? pcSnap(x, y) : null;
  if (snap !== hoverSnap && (snap || hoverSnap)) { hoverSnap = snap; pcRedrawDrawings(); }
}

function _onPointerUp(evt) {
  if (!gesture) return;
  const g = gesture;
  gesture = null;
  pcSetInteractive(ltcTool === "none");
  $("#liveTradeChart").classList.remove("is-grabbing");
  const { x, y } = _localXY(evt);
  const sym = _toolSym();
  const p = _pointFor(x, y);
  if (g.kind === "edit") {
    if (g.moved && editPreview) {
      _commitEdit(g.hit, editPreview);
      if (typeof toast === "function") toast("buy", "Adjusted");
    }
    editPreview = null;
  } else if (g.kind === "mark" && !g.moved && p) {
    addUserMark(sym, { ts: p.ts, price: p.price, dir: $("#liveSide").value || "mark", t: Date.now() });
    // toast() is (kind, title, body) — keep that order or the message becomes a CSS class.
    if (typeof toast === "function") toast("buy", `◉ Marked @ ${fmtPrice(p.price)}`, p.kind ? `snapped to ${p.kind}` : "");
  } else if ((g.kind === "anchor" || (g.kind === "trend" && !g.moved)) && p) {
    trendAnchor = { ts: p.ts, price: p.price };
    _setHint(`Target @ ${fmtPrice(p.price)}${p.kind ? " (" + p.kind + ")" : ""} — press & drag anywhere to draw the trend`);
  } else if (g.kind === "trend" && g.moved && p && trendAnchor) {
    addUserLine(sym, { a: { ...trendAnchor }, b: { ts: p.ts, price: p.price }, color: "var(--gold)", t: Date.now() });
    if (typeof toast === "function") toast("buy", "╱ Trend line saved", p.kind ? "endpoint snapped to a wick" : "");
    trendAnchor = null;
    _setHint("Click the target price, then press & drag to draw the trend");
  }
  trendPreview = null;
  hoverSnap = null;
  _drawChanged();
}

function _cancelGesture() {
  if (!gesture && !trendAnchor) return false;
  gesture = null; editPreview = null; trendPreview = null; trendAnchor = null; hoverSnap = null;
  pcSetInteractive(ltcTool === "none");
  const el = $("#liveTradeChart");
  if (el) el.classList.remove("is-grabbing");
  if (ltcTool === "line") _setHint("Click the target price, then press & drag to draw the trend");
  pcRedrawDrawings();
  return true;
}

/* Indicator controls — EMA on/off and periods, squeeze on/off, volume on/off.
 *
 * Settings live in chartInd (chart.js) and persist to localStorage, so a reload
 * keeps the chart the trader set up. Changing anything drops the cached overlay
 * and refetches, because the overlay is now measured per timeframe AND per
 * period — a stale one would draw lines from the previous settings.
 */
function _applyIndicatorSettings(refetch) {
  saveChartInd();
  if (refetch) {
    liveOverlay = null;
    liveOverlayKey = null;
    liveOverlayAt = 0;
  }
  const note = $("#indNote");
  if (note) {
    note.textContent = chartInd.showEma
      ? `measured on ${liveTf} bars`
      : "EMA off";
  }
  if (typeof loadLiveTradeChart === "function") loadLiveTradeChart();
  else if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
}

/* Parse "9, 21, 50" the same way the server does, so what you type is what you
   get. Invalid entries leave the previous periods alone rather than wiping the
   lines out from under you mid-edit. */
function _parseEmaPeriods(raw) {
  const out = [];
  for (const part of String(raw || "").split(",")) {
    const n = Number(part.trim());
    if (!Number.isInteger(n) || n < 2 || n > 400) continue;
    if (!out.includes(n)) out.push(n);
    if (out.length >= 4) break;
  }
  return out;
}

function initIndicatorControls() {
  const bar = $("#ltcIndBar");
  if (!bar || bar.dataset.wired === "1") return;
  bar.dataset.wired = "1";

  const ema = $("#indEma"), periods = $("#indEmaPeriods");
  const sqz = $("#indSqueeze"), vol = $("#indVolume"), reset = $("#indReset");
  const pp = $("#indPrePost");

  // Reflect saved settings into the controls on first paint.
  if (ema) ema.checked = !!chartInd.showEma;
  if (sqz) sqz.checked = !!chartInd.showSqueeze;
  if (vol) vol.checked = !!chartInd.showVolume;
  if (pp) pp.checked = !!chartInd.showPrePost;
  if (periods) periods.value = chartInd.ema.join(",");

  if (pp) pp.addEventListener("change", () => {
    chartInd.showPrePost = pp.checked;
    // Needs the server round-trip: the TAPE changes, not just what is drawn.
    _applyIndicatorSettings(true);
  });

  if (ema) ema.addEventListener("change", () => {
    chartInd.showEma = ema.checked;
    _applyIndicatorSettings(ema.checked);
  });
  if (sqz) sqz.addEventListener("change", () => {
    chartInd.showSqueeze = sqz.checked;
    _applyIndicatorSettings(sqz.checked);
  });
  if (vol) vol.addEventListener("change", () => {
    chartInd.showVolume = vol.checked;
    _applyIndicatorSettings(false);   // volume needs no server round-trip
  });

  if (periods) {
    const commit = () => {
      const parsed = _parseEmaPeriods(periods.value);
      if (!parsed.length) { periods.value = chartInd.ema.join(","); return; }
      if (parsed.join(",") === chartInd.ema.join(",")) return;
      chartInd.ema = parsed;
      periods.value = parsed.join(",");   // show exactly what was accepted
      _applyIndicatorSettings(true);
    };
    periods.addEventListener("change", commit);
    periods.addEventListener("blur", commit);
    periods.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
    });
  }

  if (reset) reset.addEventListener("click", () => {
    // Every default, overnight included — leaving showPrePost out used to keep
    // the box ticked while the setting itself went undefined.
    chartInd = { ...IND_DEFAULTS, ema: [...IND_DEFAULTS.ema] };
    if (ema) ema.checked = chartInd.showEma;
    if (sqz) sqz.checked = chartInd.showSqueeze;
    if (vol) vol.checked = chartInd.showVolume;
    if (pp) pp.checked = chartInd.showPrePost;
    if (periods) periods.value = chartInd.ema.join(",");
    _applyIndicatorSettings(true);
  });
}

/* Replay controls — step, scrub, play through a session from its open.
 *
 * Deliberately not persisted: a scrub position is a thing you're doing right
 * now, not a preference, and restoring someone into the middle of yesterday's
 * replay on load would be worse than useless.
 */
function initReplayControls() {
  const bar = $("#ltcReplayBar");
  if (!bar || bar.dataset.wired === "1") return;
  bar.dataset.wired = "1";

  const on = (id, evt, fn) => { const el = $(id); if (el) el.addEventListener(evt, fn); };

  on("#rpToggle", "click", () => (replay.on ? exitReplay() : enterReplay()));
  on("#rpLive", "click", goLive);
  on("#rpPlay", "click", replayPlayPause);
  on("#rpBack", "click", () => replayStep(-1));
  on("#rpFwd", "click", () => replayStep(1));
  on("#rpScrub", "input", (e) => replaySeek(Number(e.target.value)));
  on("#rpSpeed", "change", (e) => {
    replay.speedMs = Number(e.target.value) || 400;
    // Restart the timer so a speed change takes effect immediately rather than
    // after the current tick.
    if (replay.playing) { replayPlayPause(); replayPlayPause(); }
  });
}

/* ---- toolbar, menu, keyboard ---------------------------------------------- */

/* The indicator settings live in a drop-down so the chart gets the height. */
function _setIndMenu(open) {
  const btn = $("#ltcIndBtn"), menu = $("#ltcIndBar");
  if (!btn || !menu) return;
  menu.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
  btn.classList.toggle("is-active", open);
}

function _isTyping(e) {
  const t = e.target;
  const tag = (t && t.tagName) || "";
  return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || !!(t && t.isContentEditable);
}

function _chartOnScreen() {
  const panel = $("#livePanel");
  return !!panel && !panel.hidden;
}

function _onKeyDown(e) {
  if (e.key === "Alt") altHeld = true;
  if (e.key === "Escape") {
    if (_cancelGesture()) return;
    _setIndMenu(false);
    return;
  }
  // Single-letter shortcuts must never fire while someone is typing a ticker —
  // "AMLX" used to arm the mark tool and then the line tool on its way in.
  if (_isTyping(e) || e.ctrlKey || e.metaKey || e.altKey || !_chartOnScreen() || lessonView) return;
  if (e.key === "m" || e.key === "M") _setTool(ltcTool === "mark" ? "none" : "mark");
  if (e.key === "l" || e.key === "L") _setTool(ltcTool === "line" ? "none" : "line");
  // Replay: arrows step a candle, space plays/pauses. Only while replay is on,
  // so these keys stay free for the page otherwise.
  if (replay.on) {
    if (e.key === "ArrowRight") { e.preventDefault(); replayStep(1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); replayStep(-1); }
    if (e.key === " ") { e.preventDefault(); replayPlayPause(); }
  }
}

function initLiveChartInteractions() {
  const el = $("#liveTradeChart");
  if (!el || el.dataset.wired === "1") return;
  el.dataset.wired = "1";
  // Capture phase, so a gesture we own never reaches the chart's own pan.
  el.addEventListener("pointerdown", _onPointerDown, true);
  for (const type of ["mousedown", "touchstart"]) {
    el.addEventListener(type, (e) => { if (gesture) e.stopPropagation(); }, { capture: true, passive: true });
  }
  window.addEventListener("pointermove", _onPointerMove);
  window.addEventListener("pointerup", _onPointerUp);
  window.addEventListener("pointercancel", _cancelGesture);
  el.addEventListener("pointerleave", () => {
    if (hoverSnap && !gesture) { hoverSnap = null; pcRedrawDrawings(); }
  });

  document.querySelectorAll(".ltc-tool[data-tool]").forEach((b) =>
    b.addEventListener("click", () => _setTool(b.dataset.tool)));
  const on = (id, fn) => { const b = $(id); if (b) b.addEventListener("click", fn); };
  on("#ltcUndo", () => {
    if (lessonView) return;
    const what = popUserLast(_toolSym());
    _drawChanged();
    if (typeof toast === "function") toast(what ? "buy" : "", what ? `Undid ${what}` : "Nothing to undo");
  });
  on("#ltcClear", () => {
    if (lessonView) return;
    const sym = _toolSym();
    if (!confirm(`Clear all marks & trend lines for ${sym}?`)) return;
    clearUserAll(sym);
    _drawChanged();
  });
  on("#ltcFit", pcFitAll);
  on("#ltcFullBtn", () => { if (typeof chartExpand === "function") chartExpand(); });
  on("#ltcSymBtn", () => { if (typeof openPalette === "function") openPalette(); });
  on("#ltcIndBtn", () => _setIndMenu($("#ltcIndBar").hidden));
  document.addEventListener("pointerdown", (e) => {
    const menu = $("#ltcIndBar");
    if (menu && !menu.hidden && !e.target.closest("#ltcIndBar, #ltcIndBtn")) _setIndMenu(false);
  });

  initIndicatorControls();
  initReplayControls();
  window.addEventListener("keydown", _onKeyDown);
  window.addEventListener("keyup", (e) => { if (e.key === "Alt") altHeld = false; });
  window.addEventListener("blur", () => { altHeld = false; });
  _setTool("none");
}
