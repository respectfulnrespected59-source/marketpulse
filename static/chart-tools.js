/* MarketPulse — chart interaction tools.
 *
 * Click-to-mark, trend-line drawing, crosshair, fullscreen, pan and zoom.
 *
 * Split out of app.js to keep each file readable. Classic script, so it
 * shares one global scope with app.js and the other panels; everything
 * here is a declaration and nothing runs at load time. app.js is loaded
 * last because its init() call reaches into these.
 */

/* ---- Chart interaction: click to mark / draw / hover crosshair / fullscreen ---- */

function _svgEventToChart(evt) {
  const svg = $("#liveTradeChart");
  const rect = svg.getBoundingClientRect();
  // Use the SVG's current viewBox — it was resized when we moved to the
  // Webull layout (1000×360), so a hardcoded height throws Y off by 20%.
  const vb = svg.viewBox && svg.viewBox.baseVal;
  const W = (vb && vb.width) || 1000;
  const H = (vb && vb.height) || 360;
  const x = ((evt.clientX - rect.left) / rect.width) * W;
  const y = ((evt.clientY - rect.top) / rect.height) * H;
  return { x, y, W, H, pxPerSvgX: rect.width / W, pxPerSvgY: rect.height / H };
}

function _pixelToTsPrice(x, y) {
  const g = liveLast.geom;
  if (!g) return null;
  const r = g.priceRect || { x: g.pad, y: g.pad, w: g.W - g.pad * 2, h: g.H - g.pad * 2 };
  const t = Math.max(0, Math.min(1, (x - r.x) / r.w));
  const idx = Math.round(t * (g.n - 1));
  const ts = (g.ts && g.ts[idx]) || Math.floor(Date.now() / 1000);
  const min = g.priceMin != null ? g.priceMin : Math.min(...g.ohlc.map((b) => b[2]));
  const max = g.priceMax != null ? g.priceMax : Math.max(...g.ohlc.map((b) => b[1]));
  const span = (max - min) || 1;
  const price = min + (1 - Math.max(0, Math.min(1, (y - r.y) / r.h))) * span;
  return { ts, price: +price.toFixed(4), idx };
}

function _setTool(t) {
  ltcTool = t;
  // Any tool switch clears an in-flight trend gesture.
  trendAnchor = null; trendDragging = false; trendPreview = null; dragState = null;
  const wrap = $("#liveTradeWrap");
  if (wrap) {
    wrap.classList.toggle("tool-mark", t === "mark");
    wrap.classList.toggle("tool-line", t === "line");
    wrap.classList.toggle("tool-active", t !== "none");
  }
  document.querySelectorAll(".ltc-tool[data-tool]").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.tool === t));
  const hint = $("#ltcHint");
  if (hint) {
    if (t === "mark") { hint.hidden = false; hint.textContent = "Click the chart to drop an entry mark"; }
    else if (t === "line") { hint.hidden = false; hint.textContent = "Click target price → then press & drag to draw the trend"; }
    else { hint.hidden = true; hint.textContent = ""; }
  }
  if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _onChartClick(evt) {
  if (suppressNextClick) { suppressNextClick = false; return; }
  if (!liveLast.ok || ltcTool === "none") return;
  const { x, y } = _svgEventToChart(evt);
  // Snap to the nearest OHLC point unless Alt held.
  const snap = altHeld ? null : _getSnapCandidate(x, y);
  const p = snap ? { ts: snap.ts, price: snap.price, idx: snap.idx } : _pixelToTsPrice(x, y);
  if (!p) return;
  const sym = (liveLast.data && liveLast.data.symbol) || $("#liveSymbol").value.trim().toUpperCase();
  if (ltcTool === "mark") {
    addUserMark(sym, { ts: p.ts, price: p.price, dir: $("#liveSide").value || "mark", t: Date.now() });
    if (typeof toast === "function") toast(`◉ Marked @ ${fmtPrice(p.price)}${snap ? " (" + snap.kind + ")" : ""}`, "buy");
    renderLiveTradeChart(liveLast.data, liveLast.kind);
  } else if (ltcTool === "line") {
    trendAnchor = { ts: p.ts, price: p.price, x: snap ? snap.x : x, y: snap ? snap.y : y };
    const hint = $("#ltcHint");
    if (hint) hint.textContent = `Target @ ${fmtPrice(p.price)}${snap ? " (" + snap.kind + ")" : ""} — press & drag anywhere to draw the trend`;
    renderLiveTradeChart(liveLast.data, liveLast.kind);
  }
}

function _onChartMouseDown(evt) {
  if (!liveLast.ok) return;
  const { x, y, pxPerSvgX, pxPerSvgY } = _svgEventToChart(evt);
  if (liveLast.geom) { liveLast.geom.pxPerSvgX = pxPerSvgX; liveLast.geom.pxPerSvgY = pxPerSvgY; }

  // Hit-test existing markers/endpoints first — works from ANY tool so Rob
  // can retouch a point without switching modes.
  const hit = _hitTestMarker(x, y);
  if (hit) {
    const sym = liveLast.data && liveLast.data.symbol;
    if (evt.altKey) {
      _deleteHit(hit, sym);
      suppressNextClick = true;
      renderLiveTradeChart(liveLast.data, liveLast.kind);
      evt.preventDefault();
      return;
    }
    editState = { kind: hit.kind, idx: hit.idx, sym };
    // Initialize the preview to the marker's current location so the first
    // mousemove has something to nudge from.
    if (hit.kind === "mark") editPreview = { ts: hit.mark.ts, price: hit.mark.price };
    else editPreview = { ts: hit.line[hit.kind === "lineA" ? "a" : "b"].ts,
                         price: hit.line[hit.kind === "lineA" ? "a" : "b"].price };
    evt.preventDefault();
    return;
  }

  // Otherwise, arm a potential trend-line drag.
  if (ltcTool === "line" && trendAnchor) {
    dragState = { startX: x, startY: y, moved: false };
    return;
  }
  // Default (no tool active, not editing a marker, not a hit): drag = pan.
  if (ltcTool === "none" && liveLast.geom) {
    panDrag = { startClientX: evt.clientX, startBar: liveLast.geom.viewStart, moved: false };
    const svg = $("#liveTradeChart");
    if (svg) svg.style.cursor = "grab";
    evt.preventDefault();
  }
}

function _scheduleDragRedraw() {
  if (_rafDrag) return;
  _rafDrag = requestAnimationFrame(() => {
    _rafDrag = 0;
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  });
}

function _onChartMouseUp(evt) {
  // Commit an in-flight edit of an existing marker/endpoint.
  if (editState) {
    _commitEdit();
    if (typeof toast === "function") toast("Adjusted", "buy");
    editState = null; editPreview = null;
    suppressNextClick = true;
    const svg = $("#liveTradeChart"); if (svg) svg.style.cursor = "";
    renderLiveTradeChart(liveLast.data, liveLast.kind);
    return;
  }
  // Finish a pan-drag. Suppress the trailing click so the mouseup doesn't
  // count as a click on empty chart space.
  if (panDrag) {
    const wasDrag = panDrag.moved;
    panDrag = null;
    const svg = $("#liveTradeChart"); if (svg) svg.style.cursor = "";
    if (wasDrag) suppressNextClick = true;
    return;
  }
  if (!dragState) return;
  const wasDrag = dragState.moved;
  const startedInLine = ltcTool === "line" && trendAnchor;
  dragState = null;
  if (!wasDrag) return;   // wasn't a drag — let the click handler run normally
  const { x, y } = _svgEventToChart(evt);
  // Snap the release endpoint for precise line drawing.
  const snap = altHeld ? null : _getSnapCandidate(x, y);
  const p = snap ? { ts: snap.ts, price: snap.price } : _pixelToTsPrice(x, y);
  const sym = (liveLast.data && liveLast.data.symbol) || $("#liveSymbol").value.trim().toUpperCase();
  if (startedInLine && p) {
    addUserLine(sym, {
      a: { ts: trendAnchor.ts, price: trendAnchor.price },
      b: { ts: p.ts, price: p.price },
      color: "var(--gold)", t: Date.now(),
    });
    if (typeof toast === "function") toast("╱ Trend line saved" + (snap ? " (snapped)" : ""), "buy");
  }
  trendDragging = false; trendPreview = null; trendAnchor = null;
  suppressNextClick = true;  // the release will also fire a `click` — swallow it
  const hint = $("#ltcHint");
  if (hint) hint.textContent = "Click target price → then press & drag to draw the trend";
  renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _onChartMove(evt) {
  if (!liveLast.ok) return;
  const { x, y, pxPerSvgX, pxPerSvgY } = _svgEventToChart(evt);
  // Cache scale so snap distance can be enforced in real screen pixels.
  if (liveLast.geom) { liveLast.geom.pxPerSvgX = pxPerSvgX; liveLast.geom.pxPerSvgY = pxPerSvgY; }
  _drawCrosshair(x, y);

  const svg = $("#liveTradeChart");

  // Pan-drag beats every other hover behavior — track pixel delta, translate
  // into full-tape bar units, and re-render on rAF.
  if (panDrag && liveLast.geom) {
    const rect = svg.getBoundingClientRect();
    const dxPx = evt.clientX - panDrag.startClientX;
    if (!panDrag.moved && Math.abs(dxPx) > DRAG_THRESHOLD_PX) {
      panDrag.moved = true;
      if (svg) svg.style.cursor = "grabbing";
    }
    if (panDrag.moved) {
      const g = liveLast.geom;
      const barsPerPx = g.n / Math.max(1, rect.width);
      const deltaBars = -Math.round(dxPx * barsPerPx);
      const nAll = g.nAll || (g.fullOhlc || []).length;
      const newStart = Math.max(0, Math.min(Math.max(0, nAll - g.viewCount), panDrag.startBar + deltaBars));
      chartView = { start: newStart, count: g.viewCount, pinned: (newStart + g.viewCount) >= nAll };
      _scheduleDragRedraw();
    }
    return;
  }

  // Cursor affordance: grab-hand when hovering an editable marker.
  if (svg && !editState && !dragState) {
    const hit = _hitTestMarker(x, y);
    if (hit) svg.style.cursor = evt.altKey ? "not-allowed" : "grab";
    else svg.style.cursor = ltcTool === "none" ? "grab" : "";
  }

  // Live-edit an existing marker/endpoint being dragged.
  if (editState) {
    const snap = altHeld ? null : _getSnapCandidate(x, y);
    const p = snap ? { ts: snap.ts, price: snap.price } : _pixelToTsPrice(x, y);
    editPreview = { ts: p.ts, price: p.price };
    if (svg) svg.style.cursor = "grabbing";
    _scheduleDragRedraw();
    return;
  }

  // Trend-line drag detection: press-and-drag while trend anchor exists.
  if (dragState && ltcTool === "line" && trendAnchor) {
    const dx = x - dragState.startX, dy = y - dragState.startY;
    if (!dragState.moved && (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX)) {
      dragState.moved = true;
      trendDragging = true;
      const a = _tsToXY(liveLast.geom, trendAnchor.ts, trendAnchor.price);
      trendPreview = {
        ax: a ? a.x : trendAnchor.x,
        ay: liveLast.geom.Y(trendAnchor.price),
        bx: x, by: y,
      };
    }
    if (dragState.moved && trendPreview) {
      // Snap the drag endpoint too, for precision line drawing.
      const snap = altHeld ? null : _getSnapCandidate(x, y);
      trendPreview.bx = snap ? snap.x : x;
      trendPreview.by = snap ? snap.y : y;
      _scheduleDragRedraw();
    }
  }
}
function _onChartLeave() { _clearCrosshair(); }

/* ---- Pan + zoom: viewport ops ------------------------------------------
   All coord math funnels through liveLast.geom, so pan/zoom just rewrites
   chartView and triggers a redraw. `pinned` re-latches to true whenever the
   right edge of the window touches the latest bar, so a user who zooms back
   in to "now" gets auto-follow again for free. */

function _panBars(deltaBars) {
  const g = liveLast.geom;
  if (!g) return;
  const nAll = g.nAll || (g.fullOhlc || []).length;
  const count = g.viewCount || g.n;
  if (!nAll || !count) return;
  const newStart = Math.max(0, Math.min(Math.max(0, nAll - count), g.viewStart + deltaBars));
  chartView = { start: newStart, count, pinned: (newStart + count) >= nAll };
  renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _zoomAtBar(anchorBarFull, factor) {
  const g = liveLast.geom;
  if (!g) return;
  const nAll = g.nAll || (g.fullOhlc || []).length;
  if (!nAll) return;
  const oldCount = g.viewCount || g.n;
  const newCount = Math.max(MIN_VISIBLE_BARS, Math.min(nAll, Math.round(oldCount * factor)));
  if (newCount === oldCount) return;
  // Keep the bar under the cursor at the same fractional x position.
  const relCursor = oldCount <= 1 ? 0.5 : (anchorBarFull - g.viewStart) / (oldCount - 1);
  const newStart = Math.max(0, Math.min(Math.max(0, nAll - newCount),
    Math.round(anchorBarFull - relCursor * (newCount - 1))));
  chartView = { start: newStart, count: newCount, pinned: (newStart + newCount) >= nAll };
  renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _onChartWheel(evt) {
  if (!liveLast.ok || !liveLast.geom) return;
  evt.preventDefault();
  const g = liveLast.geom;
  const svg = $("#liveTradeChart");
  const rect = svg.getBoundingClientRect();
  const relX = Math.max(0, Math.min(1, (evt.clientX - rect.left) / rect.width));
  const cursorBarInView = Math.round(relX * Math.max(0, g.n - 1));
  _wheelAnchorBarFull = g.viewStart + cursorBarInView;
  _wheelIsPan = evt.shiftKey || Math.abs(evt.deltaX) > Math.abs(evt.deltaY);
  // Accumulate raw delta; a single rAF-scheduled callback drains it. Multiple
  // wheel events between frames collapse into one gentle step.
  _wheelAccum += _wheelIsPan
    ? (evt.shiftKey ? evt.deltaY : evt.deltaX)
    : evt.deltaY;
  if (_wheelRaf) return;
  _wheelRaf = requestAnimationFrame(_drainWheel);
}

function _drainWheel() {
  _wheelRaf = 0;
  const delta = _wheelAccum;
  _wheelAccum = 0;
  if (!liveLast.geom) return;
  const g = liveLast.geom;
  if (_wheelIsPan) {
    const svg = $("#liveTradeChart");
    const rect = svg.getBoundingClientRect();
    const barsPerPx = Math.max(0.02, g.n / rect.width);
    const step = Math.round(delta * barsPerPx / 3);
    if (step !== 0) _panBars(step);
    return;
  }
  // Gentle exponential zoom: 100 units of delta ≈ 4% zoom step. Multi-event
  // trackpad bursts still add up smoothly instead of stair-stepping.
  const factor = Math.exp(delta * 0.0004);
  const clamped = Math.min(2.5, Math.max(0.4, factor));
  _zoomAtBar(_wheelAnchorBarFull, clamped);
}

function _onChartDblClick(evt) {
  evt.preventDefault();
  if (liveLast.ok && liveLast.data) { resetChartView(); renderLiveTradeChart(liveLast.data, liveLast.kind); }
}

function _toggleFullscreen() {
  const card = $("#liveTradeCard");
  if (!card) return;
  const apply = () => {
    const on = card.classList.toggle("is-fullscreen");
    document.body.classList.toggle("mp-lock-scroll", on);
    const btn = $("#ltcFullBtn");
    if (btn) btn.textContent = on ? "⤢ Exit" : "⛶ Fullscreen";
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  };
  // View Transitions API gives a butter-smooth cross-fade + size morph
  // on Chromium; graceful fallback keeps other browsers working.
  if (document.startViewTransition) document.startViewTransition(apply);
  else apply();
}

function initLiveChartInteractions() {
  const svg = $("#liveTradeChart");
  if (!svg || svg.dataset.wired === "1") return;
  svg.dataset.wired = "1";
  svg.addEventListener("click", _onChartClick);
  svg.addEventListener("mousedown", _onChartMouseDown);
  svg.addEventListener("mousemove", _onChartMove);
  svg.addEventListener("mouseleave", _onChartLeave);
  // Mouseup on window (not just SVG) so a drag that releases outside the chart still commits.
  window.addEventListener("mouseup", _onChartMouseUp);
  svg.addEventListener("dblclick", _onChartDblClick);
  // Wheel-to-zoom / shift-wheel-to-pan. passive:false so preventDefault
  // suppresses the page's own scroll while the cursor is over the chart.
  svg.addEventListener("wheel", _onChartWheel, { passive: false });
  document.querySelectorAll(".ltc-tool[data-tool]").forEach((b) =>
    b.addEventListener("click", () => _setTool(b.dataset.tool)));
  const undo = $("#ltcUndo");
  if (undo) undo.addEventListener("click", () => {
    const sym = ($("#liveSymbol").value || "").trim().toUpperCase();
    const what = popUserLast(sym);
    if (what && liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
    if (typeof toast === "function") toast(what ? `Undid ${what}` : "Nothing to undo");
  });
  const clr = $("#ltcClear");
  if (clr) clr.addEventListener("click", () => {
    const sym = ($("#liveSymbol").value || "").trim().toUpperCase();
    if (!confirm(`Clear all marks & trend lines for ${sym}?`)) return;
    clearUserAll(sym);
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  });
  const full = $("#ltcFullBtn");
  if (full) full.addEventListener("click", _toggleFullscreen);
  const fit = $("#ltcFit");
  if (fit) fit.addEventListener("click", () => {
    resetChartView();
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Alt") { altHeld = true; }
    if (e.key === "Escape") {
      if (editState) { editState = null; editPreview = null; renderLiveTradeChart(liveLast.data, liveLast.kind); return; }
      if (trendAnchor || trendDragging) {
        trendAnchor = null; trendDragging = false; trendPreview = null;
        if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
        return;
      }
      if ($("#liveTradeCard").classList.contains("is-fullscreen")) _toggleFullscreen();
    }
    if (e.key === "m" || e.key === "M") _setTool(ltcTool === "mark" ? "none" : "mark");
    if (e.key === "l" || e.key === "L") _setTool(ltcTool === "line" ? "none" : "line");
  });
  window.addEventListener("keyup", (e) => {
    if (e.key === "Alt") { altHeld = false; }
  });
  window.addEventListener("blur", () => { altHeld = false; });
  _setTool("none");
}

