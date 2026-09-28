/* MarketPulse — chart engine.
 *
 * Draws the live chart with TradingView Lightweight Charts (vendored v5.2.1,
 * Apache-2.0 — see vendor/LIGHTWEIGHT-CHARTS-LICENSE.txt). chart.js still owns
 * WHAT is on the chart: the tape, replay, overlays and marks. This file owns HOW
 * it is drawn, plus the conversions between screen pixels and (bar, price) that
 * the drawing tools in chart-tools.js need.
 *
 * One rule holds it together: the chart's logical index IS the tape index.
 * Replay feeds the unrevealed bars as whitespace instead of dropping them, so
 * bar i always sits in slot i. Candles land at fixed positions and march
 * forward as the dial moves, instead of the axis restretching on every step.
 *
 * Classic script sharing one global scope with chart.js and app.js. Nothing
 * runs at load time; the chart is built on the first render.
 */

const PC_RIGHT_PAD = 6;        // empty slots right of the newest bar: where the live candle forms
const PC_SNAP_PX = 18;         // snap radius in screen pixels
const PC_HIT_PX = 12;          // grab radius for an existing mark or line end
const PC_MIN_BAR_PX = 7;       // narrowest candle slot the default window will open at
const PC_MIN_BARS = 20;        // ...but never fewer bars than this, however narrow
const PC_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const PC_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// TTM momentum, four colours: the slope matters as much as the sign.
const PC_MOM = { upRising: "rgba(45,212,191,0.95)", upFalling: "rgba(59,130,246,0.65)",
                 dnFalling: "rgba(248,113,113,0.95)", dnRising: "rgba(190,60,80,0.60)" };
const PC_BAND = { bb: "rgba(56,189,248,0.85)", kc: "rgba(148,163,184,0.75)" };

let pc = null;                  // the chart and its series, built on first render
let pcTape = { key: null, n: 0, revealed: 0, times: [], ts: [], ohlc: [], vol: [], tf: "5m" };
let pcWantReset = false;        // next render re-frames the default window
let pcReplayFramedFor = null;   // session-open ts the replay view was last framed on
let pcFixed = null;             // {min, max, volMax} while replay pins the ladder
let pcHoverIdx = null;          // bar under the crosshair, for the OHLC legend
// The library applies a new visible range on its NEXT frame, so reading it back
// straight after setting it returns the old view. Two renders inside one frame
// (a symbol switch as its data lands) would then restore the stale view over a
// fresh reset. So the range we last asked for is remembered until the chart
// reports a change, and the viewport logic reads that instead.
let pcPendingRange = null;

/* Lightweight Charts has no time zone setting and labels everything in UTC. The
 * documented fix is to hand it times already shifted into local time, so the
 * axis reads the same clock the old chart did. The shift can run a bar
 * backwards across a DST fall-back, and the library rejects unsorted data, so
 * each time is forced strictly past the one before it. Nothing converts a
 * chart time back into a real one: every lookup goes through the bar index. */
function _pcTimes(ts, n) {
  const out = new Array(n);
  let prev = -Infinity;
  for (let i = 0; i < n; i++) {
    const t = ts[i] - new Date(ts[i] * 1000).getTimezoneOffset() * 60;
    prev = t > prev ? t : prev + 1;
    out[i] = prev;
  }
  return out;
}

function _pcToken(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function _pcPad(v) { return String(v).padStart(2, "0"); }

function _pcTickLabel(time, type) {
  const d = new Date(time * 1000);            // shifted: read it back with UTC getters
  if (type === 0) return String(d.getUTCFullYear());
  if (type === 1) return PC_MONTHS[d.getUTCMonth()];
  if (type === 2) return `${PC_MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
  return `${_pcPad(d.getUTCHours())}:${_pcPad(d.getUTCMinutes())}`;
}

function _pcCrosshairTime(time) {
  const d = new Date(time * 1000);
  const day = `${PC_DAYS[d.getUTCDay()]} ${PC_MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
  if (!TIME_AXIS_TFS.has(pcTape.tf)) return `${day} ${d.getUTCFullYear()}`;
  return `${day}  ${_pcPad(d.getUTCHours())}:${_pcPad(d.getUTCMinutes())}`;
}

/* Build the chart once. Returns null when the library or container is missing,
 * so a failed vendor load degrades to the "can't draw" message, not a throw. */
function pcEnsure() {
  if (pc) return pc;
  const LW = window.LightweightCharts;
  const el = document.getElementById("liveTradeChart");
  if (!LW || !el) return null;
  const colors = { line: _pcToken("--line", "#2c2140"), dim: _pcToken("--text-dim", "#a99fc0"),
                   buy: _pcToken("--buy", "#2fd180"), sell: _pcToken("--sell", "#ff5d6c") };
  const chart = LW.createChart(el, _pcChartOptions(LW, colors));
  const candles = chart.addSeries(LW.CandlestickSeries, {
    upColor: colors.buy, downColor: colors.sell, wickUpColor: colors.buy, wickDownColor: colors.sell,
    borderVisible: false, priceLineStyle: LW.LineStyle.Dotted,
    // Replay pins the ladder to the whole session so it doesn't lurch per step.
    autoscaleInfoProvider: (base) => (pcFixed
      ? { priceRange: { minValue: pcFixed.min, maxValue: pcFixed.max } } : base()),
  }, 0);
  const volume = chart.addSeries(LW.HistogramSeries, {
    priceScaleId: "vol", priceFormat: { type: "volume" },
    lastValueVisible: false, priceLineVisible: false,
    autoscaleInfoProvider: (base) => (pcFixed && pcFixed.volMax
      ? { priceRange: { minValue: 0, maxValue: pcFixed.volMax } } : base()),
  }, 0);
  chart.priceScale("vol", 0).applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false });
  const draw = new PcDrawings();
  candles.attachPrimitive(draw);
  pc = { LW, chart, el, candles, volume, draw, emas: [], bands: {}, mom: null, dots: null,
         entryLine: null, precision: null, colors: { buy: colors.buy, sell: colors.sell } };
  chart.subscribeCrosshairMove((p) => {
    pcHoverIdx = (p && p.logical != null) ? Math.round(p.logical) : null;
    pcRenderLegend();
  });
  chart.subscribeDblClick(() => { pcWantReset = true; pcApplyDefaultView(); });
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => { pcPendingRange = null; });
  return pc;
}

/* The terminal look: transparent over the card, hairline grid, gold crosshair. */
function _pcChartOptions(LW, c) {
  const cross = { color: "rgba(232,194,90,0.55)", width: 1, style: LW.LineStyle.Dashed,
                  labelBackgroundColor: "#2c2140" };
  return {
    autoSize: true,
    layout: {
      background: { type: LW.ColorType.Solid, color: "transparent" },
      textColor: c.dim,
      fontFamily: _pcToken("--mono", "ui-monospace, monospace"),
      fontSize: 11,
      attributionLogo: true,   // the library's license notice asks for this credit
      panes: { separatorColor: c.line, separatorHoverColor: "rgba(232,194,90,0.35)", enableResize: true },
    },
    grid: { vertLines: { color: "rgba(169,159,192,0.05)" }, horzLines: { color: "rgba(169,159,192,0.07)" } },
    crosshair: { mode: LW.CrosshairMode.Normal, vertLine: cross, horzLine: cross },
    rightPriceScale: { borderColor: c.line, scaleMargins: { top: 0.08, bottom: 0.18 } },
    timeScale: {
      borderColor: c.line, rightOffset: PC_RIGHT_PAD, barSpacing: 8, minBarSpacing: 1,
      timeVisible: true, secondsVisible: false,
      tickMarkFormatter: _pcTickLabel,
    },
    localization: { timeFormatter: _pcCrosshairTime },
    handleScroll: _pcScroll(true),
  };
}

/* ---- data mapping ------------------------------------------------------ */

function _pcLineSeries(opts, pane) {
  return pc.chart.addSeries(pc.LW.LineSeries, {
    lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false,
    // Indicators never set the price range: the candles do, as they always have.
    autoscaleInfoProvider: () => null,
    ...opts,
  }, pane);
}

/* [[ts, value], ...] -> line points on the bars actually revealed. Matched by
 * exact timestamp: the server stamps every overlay from the same bar array. */
function _pcPairsToLine(pairs, lastTs) {
  if (!pairs || !pairs.length) return [];
  const idxOf = new Map();
  for (let i = 0; i < pcTape.revealed; i++) idxOf.set(pcTape.ts[i], i);
  const out = [];
  for (const [t, v] of pairs) {
    if (t > lastTs || v == null) continue;          // never draw past the dial
    const i = idxOf.get(t);
    if (i != null) out.push({ time: pcTape.times[i], value: v });
  }
  return out;
}

function _pcSetEmas(overlay, show, lastTs) {
  const periods = (show && overlay && overlay.emas) ? (overlay.periods || []).map(String) : [];
  while (pc.emas.length > periods.length) pc.chart.removeSeries(pc.emas.pop());
  periods.forEach((key, idx) => {
    const color = EMA_COLORS[idx % EMA_COLORS.length];
    if (!pc.emas[idx]) {
      pc.emas[idx] = _pcLineSeries({ color, lineWidth: 2, lastValueVisible: true }, 0);
    }
    pc.emas[idx].applyOptions({ color, title: "" });
    pc.emas[idx].setData(_pcPairsToLine(overlay.emas[key], lastTs));
  });
}

function _pcSetBands(series, show, lastTs) {
  const LW = pc.LW;
  const specs = [["bb_upper", PC_BAND.bb, LW.LineStyle.Solid], ["bb_lower", PC_BAND.bb, LW.LineStyle.Solid],
                 ["kc_upper", PC_BAND.kc, LW.LineStyle.Dashed], ["kc_lower", PC_BAND.kc, LW.LineStyle.Dashed]];
  for (const [key, color, lineStyle] of specs) {
    if (!show || !series) {
      if (pc.bands[key]) { pc.chart.removeSeries(pc.bands[key]); delete pc.bands[key]; }
      continue;
    }
    if (!pc.bands[key]) pc.bands[key] = _pcLineSeries({ color, lineStyle }, 0);
    pc.bands[key].setData(_pcPairsToLine(series[key], lastTs));
  }
}

/* TTM momentum pane: the histogram says which WAY, the dots on its zero line
 * say energy is building (red = coiled on that bar, green = the bar it fired). */
function _pcSetMomentum(series, show, lastTs) {
  const pairs = show && series && series.mom;
  if (!pairs || pairs.length < 2) {
    if (pc.dots) { pc.chart.removeSeries(pc.dots); pc.dots = null; }
    if (pc.mom) { pc.chart.removeSeries(pc.mom); pc.mom = null; }
    return;
  }
  if (!pc.mom) {
    pc.mom = pc.chart.addSeries(pc.LW.HistogramSeries, {
      priceFormat: { type: "price", precision: 3, minMove: 0.001 },
      lastValueVisible: false, priceLineVisible: false,
    }, 1);
    pc.dots = _pcLineSeries({ lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2.5 }, 1);
    const panes = pc.chart.panes();
    if (panes[1]) panes[1].setStretchFactor(0.24);
  }
  const bars = [];
  let prev = null;
  for (const p of _pcPairsToLine(pairs, lastTs)) {
    const v = p.value;
    const rising = prev == null ? v >= 0 : v > prev;
    const color = v >= 0 ? (rising ? PC_MOM.upRising : PC_MOM.upFalling)
                         : (rising ? PC_MOM.dnRising : PC_MOM.dnFalling);
    bars.push({ time: p.time, value: v, color });
    prev = v;
  }
  pc.mom.setData(bars);
  const on = new Set(series.on || []);
  const dots = [];
  for (let i = 0; i < pcTape.revealed; i++) {
    const isOn = on.has(pcTape.ts[i]);
    const fired = !isOn && i > 0 && on.has(pcTape.ts[i - 1]);
    if (isOn || fired) {
      dots.push({ time: pcTape.times[i], value: 0, color: isOn ? "#f87171" : "#4ade80" });
    }
  }
  pc.dots.setData(dots);
}

/* Enough decimals to see the digits that move, from $1,800 stocks to PEPE. */
function _pcPrecision(price) {
  if (!(price > 0)) return 2;
  if (price >= 1) return 2;
  if (price >= 0.01) return 4;
  return Math.min(10, Math.floor(-Math.log10(price)) + 4);
}

function _pcSetEntry(entry) {
  if (entry == null || !isFinite(entry)) {
    if (pc.entryLine) { pc.candles.removePriceLine(pc.entryLine); pc.entryLine = null; }
    return;
  }
  const opts = { price: Number(entry), color: "#e8c25a", lineWidth: 2,
                 lineStyle: pc.LW.LineStyle.Dashed, axisLabelVisible: true, title: "ENTRY" };
  if (pc.entryLine) pc.entryLine.applyOptions(opts);
  else pc.entryLine = pc.candles.createPriceLine(opts);
}

/* ---- viewport ----------------------------------------------------------- */

/* Where the view sat before new data landed, pinned to a TIMESTAMP. The tape is
 * a rolling window, so on the 1m chart old bars fall off the front every poll;
 * an index would let the view creep forward under a trader studying a setup. */
function _pcSetRange(range) {
  pcPendingRange = { from: range.from, to: range.to };
  pc.chart.timeScale().setVisibleLogicalRange(range);
}

function _pcCaptureView() {
  const lr = pcPendingRange || pc.chart.timeScale().getVisibleLogicalRange();
  if (!lr || !pcTape.n) return null;
  const last = pcTape.revealed - 1;
  const anchorIdx = Math.max(0, Math.min(pcTape.n - 1, Math.floor(lr.from)));
  return { from: lr.from, to: lr.to, last, pinned: lr.to >= last - 0.5,
           anchorIdx, anchorTs: pcTape.ts[anchorIdx] };
}

function pcApplyDefaultView() {
  if (!pc || !pcTape.revealed) return;
  // A phone can't show 78 candles legibly: never open narrower than ~7px a bar.
  const w = pc.chart.timeScale().width();
  const fits = w > 0 ? Math.max(PC_MIN_BARS, Math.floor(w / PC_MIN_BAR_PX)) : Infinity;
  const count = Math.min(pcTape.revealed, DEFAULT_VISIBLE[pcTape.tf] || 78, fits);
  const to = pcTape.revealed - 1 + PC_RIGHT_PAD;
  _pcSetRange({ from: to - PC_RIGHT_PAD - count + 0.5, to });
  pcWantReset = false;
}

function pcFitAll() {
  if (!pc) return;
  pcPendingRange = null;                 // fitContent picks its own range
  pc.chart.timeScale().fitContent();
}

function _pcApplyView(prev, replayWin) {
  if (replayWin) {
    // Frame the session once per drill/replay. After that the trader may zoom
    // freely, and stepping the dial must not move the view: the candles march
    // forward across a still frame. So a replay view is only ever held in
    // place, never "followed" like the live edge.
    if (pcReplayFramedFor !== replayWin.fromTs || pcWantReset) {
      _pcSetRange({ from: replayWin.from - 1, to: replayWin.end + PC_RIGHT_PAD });
      pcReplayFramedFor = replayWin.fromTs;
      pcWantReset = false;
    } else if (prev) {
      _pcRestore(prev, false);
    }
    return;
  }
  pcReplayFramedFor = null;
  if (!prev || pcWantReset) { pcApplyDefaultView(); return; }
  _pcRestore(prev, prev.pinned);
}

function _pcRestore(prev, followEdge) {
  if (followEdge) {
    // Glued to the live edge: keep the same width and gap, follow new bars.
    const width = prev.to - prev.from;
    const to = (pcTape.revealed - 1) + (prev.to - prev.last);
    _pcSetRange({ from: to - width, to });
    return;
  }
  const found = _indexOfTs(pcTape.ts, prev.anchorTs);
  const shift = (found >= 0 ? found : 0) - prev.anchorIdx;
  _pcSetRange({ from: prev.from + shift, to: prev.to + shift });
}

/* ---- render ------------------------------------------------------------- */

/* Replay pins the price ladder (and the volume scale) to the session being
 * replayed, so the axis holds still while candles are revealed. */
function _pcSessionRange(w) {
  const { ohlc, vol, n } = pcTape;
  let min = Infinity, max = -Infinity, volMax = 0;
  for (let i = w.from; i <= Math.min(w.end, n - 1); i++) {
    min = Math.min(min, ohlc[i][2]); max = Math.max(max, ohlc[i][1]);
    volMax = Math.max(volMax, vol[i] || 0);
  }
  return isFinite(min) && isFinite(max) ? { min, max, volMax } : null;
}

/* Candles for every bar (whitespace past the dial) and volume for the revealed ones. */
function _pcSetCandles(showVolume) {
  const { times, ohlc, vol, revealed, n } = pcTape;
  const { buy, sell } = pc.colors;
  const candleData = new Array(n);
  const volData = [];
  for (let i = 0; i < n; i++) {
    if (i >= revealed) { candleData[i] = { time: times[i] }; continue; }
    const [o, h, l, c] = ohlc[i];
    candleData[i] = { time: times[i], open: o, high: h, low: l, close: c };
    if (showVolume && vol[i]) {
      volData.push({ time: times[i], value: vol[i], color: c >= o ? `${buy}66` : `${sell}66` });
    }
  }
  pc.candles.setData(candleData);
  pc.volume.setData(volData);
}

/* Draw one frame of the tape.
 *   m.d        /api/intraday payload
 *   m.revealed bars shown (replay hides the rest as whitespace)
 *   m.replay   {from, end, fromTs} while the dial is parked, else null
 *   m.identity symbol|timeframe; a change re-frames the view
 */
function pcRender(m) {
  if (!pcEnsure()) return false;
  const d = m.d;
  const n = Math.min((d.ohlc || []).length, (d.ts || []).length);
  const prev = (pcTape.key === m.identity) ? _pcCaptureView() : null;
  if (pcTape.key !== m.identity) pcReplayFramedFor = null;
  pcTape = { key: m.identity, n, revealed: Math.min(m.revealed, n), times: _pcTimes(d.ts, n),
             ts: d.ts, ohlc: d.ohlc, vol: d.volume || [], tf: m.tf };
  const { ohlc, revealed } = pcTape;

  const precision = _pcPrecision(ohlc[revealed - 1] && ohlc[revealed - 1][3]);
  if (precision !== pc.precision) {
    pc.precision = precision;
    pc.candles.applyOptions({ priceFormat: { type: "price", precision, minMove: Math.pow(10, -precision) } });
  }

  pcFixed = m.replay ? _pcSessionRange(m.replay) : null;
  _pcSetCandles(m.showVolume);

  const lastTs = pcTape.ts[revealed - 1];
  const ov = m.overlay;
  _pcSetEmas(ov, m.showEma, lastTs);
  const sq = ov && ov.squeeze_series;
  _pcSetBands(sq, m.showSqueeze, lastTs);
  _pcSetMomentum(sq, m.showSqueeze, lastTs);
  _pcSetEntry(m.entry);

  _pcApplyView(prev, m.replay);
  pcRedrawDrawings();
  pcRenderLegend();
  return true;
}

function pcClear() {
  if (!pc) return;
  pc.candles.setData([]);
  pc.volume.setData([]);
  _pcSetEmas(null, false, 0);
  _pcSetBands(null, false, 0);
  _pcSetMomentum(null, false, 0);
  _pcSetEntry(null);
  pcTape = { ...pcTape, key: null, n: 0, revealed: 0, times: [], ts: [], ohlc: [], vol: [] };
  pcRenderLegend();
}

/* O H L C + change for the bar under the crosshair, else the newest bar. Every
 * value is a number run through the chart's own price formatter and the class
 * is one of two literals, so nothing a user can type reaches this markup. */
function pcRenderLegend() {
  const box = document.getElementById("ltcOhlc");
  if (!box) return;
  const r = pcTape.revealed;
  if (!r) { box.innerHTML = ""; return; }
  const i = (pcHoverIdx != null && pcHoverIdx >= 0 && pcHoverIdx < r) ? pcHoverIdx : r - 1;
  const [o, h, l, c] = pcTape.ohlc[i];
  const ref = i > 0 ? pcTape.ohlc[i - 1][3] : o;
  const chg = c - ref;
  const pct = ref ? (chg / ref) * 100 : 0;
  const f = (v) => (pc ? pc.candles.priceFormatter().format(v) : String(v));
  const dir = chg >= 0 ? "up" : "down";
  // One sign for both numbers, taken from the price move as displayed: a tick
  // down must never read as a gain because its percentage rounds to 0.00.
  const shown = f(Math.abs(chg));
  const sign = /[1-9]/.test(shown) ? (chg > 0 ? "+" : "−") : "";
  const v = pcTape.vol[i];
  const volTxt = v ? ` <span class="pc-k">Vol</span> ${_pcCompact(v)}` : "";
  box.innerHTML = `<span class="pc-k">O</span> ${f(o)} <span class="pc-k">H</span> ${f(h)} `
    + `<span class="pc-k">L</span> ${f(l)} <span class="pc-k">C</span> <b class="${dir}">${f(c)}</b> `
    + `<b class="${dir}">${sign}${shown} (${sign}${Math.abs(pct).toFixed(2)}%)</b>${volTxt}`;
}

function _pcCompact(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return String(Math.round(v));
}

/* ---- pixel <-> (bar, price) ------------------------------------------- */

/* The candle pane in container pixels. Its top-left is the container's. */
function pcPaneRect() {
  if (!pc) return null;
  const panes = pc.chart.panes();
  return { w: pc.chart.timeScale().width(), h: panes[0] ? panes[0].getHeight() : 0 };
}

function pcXY(idx, price) {
  if (!pc) return null;
  const x = pc.chart.timeScale().logicalToCoordinate(idx);
  const y = pc.candles.priceToCoordinate(price);
  return (x == null || y == null) ? null : { x, y };
}

/* Revealed bar nearest to screen x (clamped), and the price at screen y. */
function pcPointAt(x, y) {
  if (!pc || !pcTape.revealed) return null;
  const lg = pc.chart.timeScale().coordinateToLogical(x);
  if (lg == null) return null;
  const idx = Math.max(0, Math.min(pcTape.revealed - 1, Math.round(lg)));
  const price = pc.candles.coordinateToPrice(y);
  if (price == null) return null;
  return { idx, ts: pcTape.ts[idx], price: +Number(price).toFixed(pc.precision + 2) };
}

/* A stored point's bar, or -1 when it lies outside the revealed tape. A mark
 * scrolled off the loaded history must not pile up on the edge candle, and one
 * placed on a bar the dial is hiding would leak where price went. */
function pcIdxOfTs(ts) {
  const r = pcTape.revealed;
  if (!r || !ts) return -1;
  const first = pcTape.ts[0], last = pcTape.ts[r - 1];
  const step = r > 1 ? Math.max(1, (last - first) / (r - 1)) : 1;
  if (ts < first - step || ts > last + step) return -1;
  const i = _indexOfTs(pcTape.ts, ts);
  if (i < 0) return -1;
  const j = Math.min(i, r - 1);
  // _indexOfTs rounds up; take whichever neighbour is actually closer.
  return (j > 0 && Math.abs(pcTape.ts[j - 1] - ts) < Math.abs(pcTape.ts[j] - ts)) ? j - 1 : j;
}

/* Nearest open/high/low/close within PC_SNAP_PX of (x, y), or null. */
function pcSnap(x, y) {
  const p = pcPointAt(x, y);
  if (!p) return null;
  let best = null, bestD = Infinity;
  for (const idx of [p.idx - 1, p.idx, p.idx + 1]) {
    if (idx < 0 || idx >= pcTape.revealed) continue;
    const [o, h, l, c] = pcTape.ohlc[idx];
    for (const [price, kind] of [[h, "high"], [l, "low"], [o, "open"], [c, "close"]]) {
      const pt = pcXY(idx, price);
      if (!pt) continue;
      const dist = Math.hypot(pt.x - x, pt.y - y);
      if (dist < bestD) { bestD = dist; best = { idx, ts: pcTape.ts[idx], price, kind, x: pt.x, y: pt.y }; }
    }
  }
  return bestD <= PC_SNAP_PX ? best : null;
}

function pcRedrawDrawings() { if (pc) pc.draw.requestUpdate(); }

/* Pause the chart's own drag-to-pan while a drawing tool owns the pointer.
 * The wheel keeps zooming, and a vertical swipe always scrolls the page, so
 * the chart never traps a phone user halfway down the screen. */
function pcSetInteractive(on) {
  if (pc) pc.chart.applyOptions({ handleScroll: _pcScroll(on) });
}

function _pcScroll(drag) {
  return { mouseWheel: true, pressedMouseMove: drag, horzTouchDrag: drag, vertTouchDrag: false };
}
