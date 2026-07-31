/* MarketPulse — live trading chart.
 *
 * The Webull-style candlestick view: intraday candles that refresh on a timer,
 * daily EMA overlays, TTM squeeze, snap-to-candle marks, drawable trend lines,
 * and pan/zoom. Split out of app.js, which had grown past the point where the
 * chart and the rest of the app could be read separately.
 *
 * Loaded BEFORE app.js (see index.html): app.js calls init() on its last line,
 * and that path reaches into this file, so these declarations must already
 * exist. Everything here is a declaration — nothing runs at load time.
 *
 * Shares the global helpers declared in app.js ($, store, state, esc, ...).
 * Both files are classic scripts, so they share one global scope.
 */

/* ---- Live trading chart: real intraday candlesticks that refresh live ---- */
let liveChartTimer = null;
let liveTf = "5m";
const TF_ORDER = ["1m", "5m", "10m", "15m", "30m", "1h", "1D", "1W"];
const TF_LABELS = {
  stock: { "1m": "1m", "5m": "5m", "10m": "10m", "15m": "15m",
           "30m": "30m", "1h": "1h", "1D": "1D", "1W": "1W" },
  crypto: { "1m": "1m", "5m": "5m", "10m": "10m", "15m": "15m",
            "30m": "30m", "1h": "1h", "1D": "1D", "1W": "1W" },
};
// How much history each button actually covers, so the header can say it.
const TF_GRAIN = {
  stock: { "1m": "1m · 5D", "5m": "5m · 5D", "10m": "10m · 5D", "15m": "15m · 1M",
           "30m": "30m · 1M", "1h": "1h · 3M", "1D": "1D · 1Y", "1W": "1W · 5Y" },
  crypto: { "1m": "1m · ~5h", "5m": "5m · ~1D", "10m": "10m · ~1D", "15m": "15m · ~3D",
            "30m": "30m · ~3D", "1h": "1h · ~12D", "1D": "1D · ~10M", "1W": "1W · ~10M" },
};
// 1m tape needs a much faster poll to feel alive; daily and weekly bars only
// change once a session, so polling them hard just burns upstream quota.
const TF_POLL_MS = { "1m": 8000, "5m": 20000, "10m": 30000, "15m": 45000,
                     "30m": 60000, "1h": 60000, "1D": 300000, "1W": 600000 };

/* Indicator settings — the trader's, not ours.
 *
 * Read straight from localStorage rather than through app.js's `store`, because
 * chart.js is evaluated FIRST (see index.html) and `store` doesn't exist yet at
 * this point. Corrupt settings fall back to defaults instead of throwing: a bad
 * saved value must never cost someone their chart.
 */
const IND_KEY = "mp_chart_indicators";
const IND_DEFAULTS = {
  ema: [14, 21, 57],
  showEma: true,
  showSqueeze: true,
  showVolume: true,
};
let chartInd = { ...IND_DEFAULTS };
try {
  const saved = JSON.parse(localStorage.getItem(IND_KEY) || "null");
  if (saved && typeof saved === "object") chartInd = { ...IND_DEFAULTS, ...saved };
  if (!Array.isArray(chartInd.ema) || !chartInd.ema.length) chartInd.ema = [...IND_DEFAULTS.ema];
} catch (e) { chartInd = { ...IND_DEFAULTS }; }

function saveChartInd() {
  try { localStorage.setItem(IND_KEY, JSON.stringify(chartInd)); } catch (e) { /* private mode */ }
}

// Chart overlay cache: EMA series + TTM squeeze, computed on the SAME bars the
// chart draws. The key carries the timeframe and the periods — it used to be
// just "kind:symbol", so switching timeframe reused an overlay measured on a
// completely different scale, which is why the lines looked arbitrary.
let liveOverlay = null;                  // last payload, or null
let liveOverlayKey = null;               // kind:symbol:tf:periods:squeeze
let liveOverlayAt = 0;                   // ms epoch of last successful fetch
const OVERLAY_TTL_MS = 60 * 1000;
// Assigned by position, so the first period a trader lists always gets gold.
const EMA_COLORS = ["#f5c66b", "#5b8def", "#c471ed", "#4ecb8f"];

// In-memory snapshot of the last loaded intraday payload — click handlers use
// it to convert pixel coords back into (timestamp, price) space.
let liveLast = { data: null, kind: "stock", ok: false };

// Chart viewport: which slice of the loaded OHLC is currently visible.
// `pinned` = true means "keep the right edge glued to the latest bar as new
// bars arrive"; the moment the user pans back, that latches to false and the
// poll no longer yanks them forward. Reset whenever symbol or timeframe
// changes so the default compact window shows the freshest bars.
// `anchorTs` is what actually holds the view still. /api/intraday returns a
// ROLLING window (MAX_INTRADAY_BARS=500), so on a 1m tape the array length
// stops growing and the CONTENT shifts left instead. A saved array index then
// points at newer data every poll — pan back to study a setup, take your hands
// off, and the tape creeps forward under you. Anchoring to the left-edge
// timestamp pins the view to the DATA rather than to an array position.
//
// Contract: anchorTs === null means "start is authoritative — adopt it and
// record its timestamp". Non-null means "re-locate start by timestamp". Pan and
// zoom therefore null it out; the next render fills it back in.
let chartView = { start: null, count: null, pinned: true, anchorTs: null };
let lastRenderSym = null, lastRenderTf = null;
const MIN_VISIBLE_BARS = 12;
// Sensible default "compact" viewport per timeframe — chosen so a new tape
// opens showing recent context at a comfortable candle width, not the whole
// loaded array crammed into 1000px. Wheel/pinch zooms out to the full history.
const DEFAULT_VISIBLE = { "1m": 90, "5m": 78, "10m": 78, "15m": 78,
                          "30m": 70, "1h": 60, "1D": 90, "1W": 60 };
let panDrag = null;  // {startClientX, startBar, moved}
// Wheel coalescing: many trackpads fire 8-15 wheel events per gesture, each
// with deltaY ~100. Applying a full step per event compounds into a dizzying
// zoom. Instead: accumulate the raw delta between frames and apply once per
// rAF with a gentle exponential factor.
let _wheelAccum = 0;
let _wheelAnchorBarFull = null;
let _wheelIsPan = false;
let _wheelRaf = 0;
function resetChartView() { chartView = { start: null, count: null, pinned: true, anchorTs: null }; }

/* ---- Session replay -----------------------------------------------------
 *
 * Walk a session forward from its open, one candle at a time. The whole day is
 * already loaded, so replay is purely a question of how much of it we reveal —
 * no refetching, and stepping backward is free.
 *
 * `from` is the session's first bar and `upto` the last revealed one. The axis
 * is always scaled to the FULL session (see chartSlot's scaleN), so candles
 * land at fixed x positions and march left to right instead of the tape
 * restretching on every step.
 *
 * The dial is NOT a mode you enter — it stays unlocked while the market is
 * open. `on` means "the cursor is parked behind the live edge": bars after
 * `upto` are hidden so a bar is read with no lookahead, while the poll keeps
 * running and `end` keeps growing behind the curtain. `cursorTs` is what holds
 * the cursor still on a rolling tape — see _syncCursorRange.
 */
let replay = { on: false, from: 0, upto: 0, end: 0, cursorTs: null, fromTs: null,
               playing: false, timer: null, speedMs: 400 };

/* First bar of the last calendar day present in the tape.
 *
 * Crypto never closes, so a "session" there is a rolling 24h rather than a
 * bell-to-bell day; falling back to the last day's worth of bars gives the same
 * replay feel without pretending there's an open. */
/* First bar of the calendar day CONTAINING `at`. Generalised from "the last
 * day" so a drill can rewind into an earlier session in the loaded tape — a
 * drill that could only ever replay today would run out of material fast. */
function _sessionStartIdxAt(tsArr, at) {
  if (!tsArr || !tsArr.length) return 0;
  // On daily and weekly bars every bar is its own day, so "the day containing
  // this bar" would resolve to the bar itself and there'd be nothing to replay.
  // The meaningful unit there is the whole loaded range — play the year forward.
  if (!TIME_AXIS_TFS.has(liveTf)) return 0;
  const anchor = Math.max(0, Math.min(at, tsArr.length - 1));
  const key = (d) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const want = key(new Date(tsArr[anchor] * 1000));
  for (let i = anchor; i >= 0; i--) {
    if (key(new Date(tsArr[i] * 1000)) !== want) return i + 1;
  }
  return 0;
}

function _sessionStartIdx(tsArr) {
  return _sessionStartIdxAt(tsArr, (tsArr && tsArr.length ? tsArr.length : 1) - 1);
}

function _replayStop() {
  if (replay.timer) { clearInterval(replay.timer); replay.timer = null; }
  replay.playing = false;
}

/* Keep the cursor coherent with a tape that is still growing.
 *
 * Two rules make an unlocked dial safe on a live chart. A cursor parked behind
 * the edge must NOT be dragged forward by new bars — that would yank you out of
 * the moment you're studying. A cursor at the edge must follow, because that IS
 * live. The parked cursor is held by TIMESTAMP, not index: on the fast tapes
 * old bars roll off the front, and an index would silently drift you forward
 * through the session while you sat still.
 */
function _syncCursorRange(d) {
  const ts = (d && d.ts) || [];
  const n = ts.length;
  if (n < 2) return;
  // A drill parks you in an earlier session, so the dial's window follows the
  // day being drilled rather than today's. Held by timestamp like the cursor,
  // because the index shifts as the tape rolls.
  let from = _sessionStartIdx(ts);
  if (replay.on && replay.fromTs) {
    const f = _indexOfTs(ts, replay.fromTs);
    if (f >= 0) from = f;
    else replay.fromTs = null;   // that day has rolled off the client
  }
  replay.from = from;
  replay.end = n - 1;
  if (!replay.on) {                       // pinned to the edge = live
    replay.upto = replay.end;
    replay.cursorTs = null;
    replay.fromTs = null;
    return;
  }
  if (replay.cursorTs) {
    const found = _indexOfTs(ts, replay.cursorTs);
    if (found >= 0) replay.upto = found;
    // found < 0 → that bar has aged off the client entirely; the clamp below
    // parks the user on the oldest bar we still hold rather than guessing.
  }
  replay.upto = Math.max(replay.from, Math.min(replay.upto, replay.end));
  replay.cursorTs = ts[replay.upto] || null;
}

/* Jump to the open and walk forward — the "study the session" entry point. */
function enterReplay() {
  const d = liveLast.data;
  if (!d || !d.ts || d.ts.length < 2) return;
  _replayStop();
  replay.on = true;
  replay.from = _sessionStartIdx(d.ts);
  replay.end = d.ts.length - 1;
  // One candle at the open is the whole point — start with exactly that.
  replay.upto = replay.from;
  replay.cursorTs = d.ts[replay.upto] || null;
  _syncReplayUI();
  renderLiveTradeChart(d, liveLast.kind);
}

/* Snap back to the live edge. The poll was never stopped, so "live" is one
 * render away — no refetch needed to be current. */
function goLive() {
  _replayStop();
  replay.on = false;
  replay.cursorTs = null;
  replay.fromTs = null;   // leaving a drill drops its session window too
  resetChartView();
  _syncReplayUI();
  if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
}

/* Kept for the toggle button's existing binding in chart-tools.js. */
function exitReplay() { goLive(); }

function replaySeek(idx) {
  const d = liveLast.data;
  if (!d || !d.ts || d.ts.length < 2) return;
  const want = Math.round(idx);
  // Dragging to the right-hand end means "catch me up", not "reveal the last
  // bar" — otherwise the dial would strand you one bar behind a moving edge.
  if (want >= replay.end) return goLive();
  replay.on = true;
  replay.upto = Math.max(replay.from, Math.min(replay.end, want));
  replay.cursorTs = d.ts[replay.upto] || null;
  _syncReplayUI();
  renderLiveTradeChart(d, liveLast.kind);
}

function replayStep(n) { replaySeek(replay.upto + n); }

function replayPlayPause() {
  if (replay.playing) { _replayStop(); _syncReplayUI(); return; }
  // Hitting play while live rewinds to the open rather than doing nothing —
  // "play" on a chart that is already at the edge can only mean "run it again".
  if (!replay.on || replay.upto >= replay.end) { enterReplay(); }
  replay.playing = true;
  replay.timer = setInterval(() => replayStep(1), replay.speedMs);
  _syncReplayUI();
}

function _syncReplayUI() {
  const ctr = $("#rpControls"), tog = $("#rpToggle"), liveBtn = $("#rpLive");
  if (tog) tog.classList.toggle("is-active", replay.on);
  // The dial is unlocked at all times now; it never hides.
  if (ctr) ctr.hidden = false;
  if (liveBtn) {
    liveBtn.classList.toggle("is-behind", replay.on);
    liveBtn.disabled = !replay.on;
    liveBtn.textContent = replay.on ? "● GO LIVE" : "● LIVE";
  }
  const play = $("#rpPlay");
  if (play) play.textContent = replay.playing ? "⏸" : "▶";
  const scrub = $("#rpScrub");
  if (scrub) {
    scrub.min = String(replay.from);
    scrub.max = String(replay.end);
    scrub.value = String(replay.upto);
  }
  // Learning Mode's call row follows the dial: a read only means something
  // while the rest of the day is hidden.
  if (typeof learnSyncUI === "function") learnSyncUI();
  const clock = $("#rpClock");
  const ts = liveLast.data && liveLast.data.ts && liveLast.data.ts[replay.upto];
  if (clock) {
    const shown = replay.upto - replay.from + 1;
    const total = replay.end - replay.from + 1;
    if (!replay.on) {
      clock.textContent = "live";
    } else {
      clock.textContent = ts
        ? `${_fmtAxisTime(new Date(ts * 1000), liveTf)} · ${shown}/${total}`
        : `${shown}/${total}`;
    }
  }
}

/* Index of `ts` in a sorted timestamp array, or the closest bar at/after it.
   Returns -1 only when the anchor has aged out of the rolling window entirely,
   which genuinely means that data is no longer on the client. */
function _indexOfTs(tsArr, ts) {
  if (!tsArr || !tsArr.length || !ts) return -1;
  if (ts < tsArr[0]) return -1;
  if (ts >= tsArr[tsArr.length - 1]) return tsArr.length - 1;
  let lo = 0, hi = tsArr.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (tsArr[mid] <= ts) lo = mid; else hi = mid;
  }
  return tsArr[lo] === ts ? lo : hi;
}
// Chart interaction mode: "none" | "mark" | "line".
// Trend line UX: single click drops a pending gold anchor at the target price
// (visible ring + dashed price rule). Then press-and-drag ANYWHERE on the
// chart — no timing window, no double-click — rubber-bands a gold line from
// the anchor to the cursor; release commits it. Plain click without dragging
// just relocates the anchor.
let ltcTool = "none";
let trendAnchor = null;        // {ts, price, x, y} — target price, ephemeral
let trendDragging = false;
let trendPreview = null;       // {ax, ay, bx, by} for live rubber-band
let dragState = null;          // {startX, startY, moved} — press-and-drag tracker
let suppressNextClick = false; // stop the drag's release from committing an anchor
let _rafDrag = 0;
const DRAG_THRESHOLD_PX = 4;   // how far the cursor must travel to be a "drag"

// Precision + edit state
let altHeld = false;           // hold Alt to bypass snap
let editState = null;          // {kind: "mark"|"lineA"|"lineB", idx, sym} being edited
let editPreview = null;        // {ts, price} live-follows the cursor during edit
const SNAP_PHYS_PX = 18;       // snap radius in *screen* pixels (feels the same at any zoom)
const HIT_PHYS_PX = 12;        // click hit radius in *screen* pixels

// Per-symbol persistence for user-drawn marks & trend lines. Timestamps are
// unix-seconds so switching timeframes still lines them up on the tape.
function _ltcKeys(sym) {
  const k = String(sym || "").toUpperCase();
  return { marks: `mp_marks_${k}`, lines: `mp_lines_${k}` };
}
function _readArr(key) { try { return JSON.parse(localStorage.getItem(key)) || []; } catch { return []; } }
function _writeArr(key, arr) { try { localStorage.setItem(key, JSON.stringify(arr)); } catch {} }
function getUserMarks(sym) { return _readArr(_ltcKeys(sym).marks); }
function getUserLines(sym) { return _readArr(_ltcKeys(sym).lines); }
function addUserMark(sym, m) { const k = _ltcKeys(sym).marks; const a = _readArr(k); a.push(m); _writeArr(k, a); }
function addUserLine(sym, l) { const k = _ltcKeys(sym).lines; const a = _readArr(k); a.push(l); _writeArr(k, a); }
function popUserLast(sym) {
  const k = _ltcKeys(sym); const m = _readArr(k.marks), l = _readArr(k.lines);
  // Undo whichever bucket was written most recently, using the trailing `t`.
  const lastM = m.length ? m[m.length - 1].t || 0 : -1;
  const lastL = l.length ? l[l.length - 1].t || 0 : -1;
  if (lastL >= lastM && l.length) { l.pop(); _writeArr(k.lines, l); return "line"; }
  if (m.length) { m.pop(); _writeArr(k.marks, m); return "mark"; }
  return null;
}
function clearUserAll(sym) { const k = _ltcKeys(sym); _writeArr(k.marks, []); _writeArr(k.lines, []); }

function renderTfButtons(kind) {
  const box = $("#ltcTf");
  if (!box) return;
  const labels = TF_LABELS[kind === "crypto" ? "crypto" : "stock"];
  box.innerHTML = TF_ORDER.map((tf) =>
    `<button type="button" data-tf="${tf}" class="${tf === liveTf ? "is-active" : ""}">${labels[tf]}</button>`
  ).join("");
  box.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      if (liveTf === b.dataset.tf) return;
      liveTf = b.dataset.tf;
      loadLiveTradeChart();
      startChartPoll();                       // reset cadence for new tf
    }));
}

function stopChartPoll() {
  if (liveChartTimer) { clearInterval(liveChartTimer); liveChartTimer = null; }
}
function startChartPoll() {
  stopChartPoll();
  liveChartTimer = setInterval(loadLiveTradeChart, TF_POLL_MS[liveTf] || 20000);
}

async function loadLiveTradeChart() {
  const raw = $("#liveSymbol").value.trim();
  const kind = $("#liveKind").value;
  if (!raw) return;
  const sym = kind === "crypto" ? raw.toLowerCase() : raw.toUpperCase();
  try {
    const res = await fetch(`/api/intraday?symbol=${encodeURIComponent(sym)}&kind=${kind}&tf=${liveTf}`);
    if (!res.ok) throw new Error(`server said ${res.status}`);
    const d = await res.json();
    // Fire-and-forget overlay refresh so the chart shows immediately; the
    // next full render (either this call's chain or the next poll) picks up
    // the daily EMAs + squeeze once they land.
    loadChartOverlay(kind, sym).then((ov) => {
      if (ov) renderLiveTradeChart(d, kind);
    }).catch(() => {});
    renderLiveTradeChart(d, kind);
  } catch (e) {
    // A blip must not wipe a tape that's already drawn — but staying silent
    // when there is NOTHING drawn is how this shows up as "the chart just
    // doesn't come up". The app shell is a PWA and loads from cache, so the
    // page looks perfectly healthy while /api/* (network-only, by design) is
    // unreachable. Say that out loud instead of showing an empty box.
    if (!liveLast.ok) _showChartUnreachable(sym);
  }
}

/* Honest empty-state when we have no tape to draw and the fetch failed. */
function _showChartUnreachable(sym) {
  const svg = $("#liveTradeChart");
  if (svg) svg.innerHTML = "";
  const last = $("#ltcLast"); if (last) last.textContent = "—";
  const chg = $("#ltcChg"); if (chg) { chg.textContent = ""; chg.className = "ltc-chg"; }
  const foot = $("#ltcFoot");
  if (foot) {
    foot.textContent = navigator.onLine
      ? `Can't reach the MarketPulse server for ${sym}. Is it still running? `
        + `Live prices are never cached, so the page can load from cache while data can't.`
      : `You're offline. Live prices are never served from cache — reconnect and this fills back in.`;
  }
}

async function loadChartOverlay(kind, sym) {
  // Nothing to fetch if the trader has both indicators switched off.
  if (!chartInd.showEma && !chartInd.showSqueeze) return null;

  const periods = chartInd.ema.join(",");
  // The timeframe and the periods are part of the identity of an overlay —
  // leaving them out is what made a 1m chart wear daily EMA lines.
  const key = `${kind}:${sym.toLowerCase()}:${liveTf}:${periods}:${chartInd.showSqueeze ? 1 : 0}`;
  if (liveOverlayKey === key && Date.now() - liveOverlayAt < OVERLAY_TTL_MS) {
    return liveOverlay;
  }
  try {
    const url = `/api/chart-overlay?symbol=${encodeURIComponent(sym)}&kind=${kind}`
      + `&tf=${encodeURIComponent(liveTf)}&ema=${encodeURIComponent(periods)}`
      + `&squeeze=${chartInd.showSqueeze ? 1 : 0}`;
    const d = await (await fetch(url)).json();
    if (d && !d.error) {
      liveOverlay = d;
      liveOverlayKey = key;
      liveOverlayAt = Date.now();
      return d;
    }
  } catch (e) { /* keep prior overlay */ }
  return liveOverlay && liveOverlayKey === key ? liveOverlay : null;
}

/* Interpolate an EMA value at unix-second `ts` from sorted [[ts,v]] pairs.
   Before the earliest / after the latest → clamp to the closest end. */
function _emaAt(pairs, ts) {
  if (!pairs || !pairs.length) return null;
  if (ts <= pairs[0][0]) return pairs[0][1];
  if (ts >= pairs[pairs.length - 1][0]) return pairs[pairs.length - 1][1];
  let lo = 0, hi = pairs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pairs[mid][0] <= ts) lo = mid; else hi = mid;
  }
  const [t0, v0] = pairs[lo], [t1, v1] = pairs[hi];
  const f = t1 === t0 ? 0 : (ts - t0) / (t1 - t0);
  return v0 + (v1 - v0) * f;
}

function _emaOverlaySVG(geom, clampY, overlay) {
  if (!geom || !overlay || !overlay.emas || !chartInd.showEma) return "";
  const { X, ts, n } = geom;
  if (!ts || ts.length !== n || n < 2) return "";
  let out = "";
  // Draw in the order the trader listed their periods, so colours stay put.
  const order = (overlay.periods || []).map(String);
  order.forEach((key, idx) => {
    const pairs = overlay.emas[key];
    if (!pairs || pairs.length < 1) return;
    const pts = [];
    for (let i = 0; i < n; i++) {
      const v = _emaAt(pairs, ts[i]);
      if (v == null) continue;
      pts.push(`${X(i).toFixed(1)},${clampY(v).toFixed(1)}`);
    }
    if (pts.length < 2) return;
    const colour = EMA_COLORS[idx % EMA_COLORS.length];
    out += `<polyline points="${pts.join(" ")}" fill="none" stroke="${colour}"
      stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" opacity="0.9"
      pointer-events="none"><title>EMA ${key} · ${overlay.tf || ""} bars</title></polyline>`;
  });
  return out;
}

function _renderSqueezeChip(overlay) {
  const box = $("#ltcSqz");
  if (!box) return;
  // The squeeze is now a single reading measured on the chart's own bars, and
  // it says which timeframe that was. It used to be a weekly value for stocks
  // and a daily one for crypto, pinned above whatever chart you had open.
  const sq = overlay && overlay.squeeze;
  if (!chartInd.showSqueeze || !sq || !sq.state) {
    box.hidden = true; box.textContent = ""; return;
  }
  const state = sq.state;                              // "on" | "fired" | "off"
  const mom = sq.mom;                                  // "bull" | "bear"
  const arrow = mom === "bull"
    ? (sq.accel === "rising" ? "▲" : "△")
    : (sq.accel === "falling" ? "▼" : "▽");
  const grain = sq.grain || (overlay && overlay.tf) || "";
  const txt = state === "on" ? `ON·${sq.bars}` : state === "fired" ? "FIRED" : "off";
  box.hidden = false;
  box.className = `ltc-sqz ${state} ${mom || ""}`;
  box.innerHTML = `<b>TTM</b> ${grain} ${txt} <span class="ltc-sqz-arr">${arrow}</span>`;
  box.title = `TTM squeeze ${state} on ${grain} bars · momentum ${mom || "—"} ${sq.accel || ""}`;
}

function _renderEmaLegend(overlay) {
  const box = $("#ltcEmas");
  if (!box) return;
  const emas = overlay && overlay.emas;
  const periods = (overlay && overlay.periods) || [];
  const has = chartInd.showEma && emas
    && periods.some((p) => (emas[String(p)] || []).length);
  if (!has) { box.hidden = true; box.textContent = ""; return; }

  // Every value below originates server-side from a fixed vocabulary: periods
  // are integers this client asked for, and the price is a number. Nothing a
  // user can type reaches this markup.
  const chip = (period, idx) => {
    const arr = emas[String(period)];
    const v = arr && arr.length ? arr[arr.length - 1][1] : null;
    if (v == null) return "";
    const colour = EMA_COLORS[idx % EMA_COLORS.length];
    const n = Number(period) || 0;
    return `<span class="ltc-ema-chip"><i style="background:${colour}"></i>`
      + `EMA${n}<b>${fmtPrice(v)}</b></span>`;
  };
  box.hidden = false;
  box.innerHTML = periods.map(chip).join("");
}

/* The "travel" — when a new candle lands while the view is pinned to the right
 * edge, the window slides forward one bar. Redrawn cold that reads as a jump:
 * the whole tape teleports left and the new candle is just suddenly there.
 *
 * So we start the rolling group one slot to the RIGHT (where the tape was a
 * moment ago) and let it settle back to zero. Same pixels, but the eye reads
 * candles marching left as fresh ones form in the right-hand gap.
 *
 * Transform-only, so it stays on the compositor and never triggers layout.
 */
let _rollKey = null;      // sym|tf this counter belongs to
let _rollLastTs = 0;      // newest bar's timestamp at the previous render
const ROLL_MS = 420;

function _playRoll(slotW, fullTs, sym) {
  const key = `${sym || ""}|${liveTf}`;
  const newestTs = (fullTs && fullTs.length) ? fullTs[fullTs.length - 1] : 0;
  const prevTs = _rollLastTs;
  const sameTape = _rollKey === key;
  _rollKey = key;
  _rollLastTs = newestTs;
  // Replay drives its own stepping; the live roll would fight it.
  if (replay.on || !sameTape || !chartView.pinned) return;
  // How many bars did the tape advance? Measured in TIME, because once the
  // rolling window is full the array length stops changing and a length-based
  // check would silently never fire again on the 1m tape.
  if (!prevTs || !newestTs || newestTs <= prevTs) return;
  const prevIdx = _indexOfTs(fullTs, prevTs);
  if (prevIdx < 0) return;                         // gapped too far to animate
  const grew = (fullTs.length - 1) - prevIdx;
  if (grew < 1 || grew > 3) return;                // first paint, or a big refill
  const g = $("#ltcBase");
  if (!g || typeof g.animate !== "function") return;
  // Honour the OS-level motion preference — this is decoration, not data.
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  g.animate(
    [{ transform: `translateX(${(slotW * grew).toFixed(2)}px)` }, { transform: "translateX(0px)" }],
    { duration: ROLL_MS, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
  );
}

function renderLiveTradeChart(d, kind) {
  const svg = $("#liveTradeChart");
  const fullOhlc = (d && d.ohlc) || [];
  const fullTs = (d && d.ts) || [];
  const fullVol = (d && d.volume) || [];
  $("#ltcSym").textContent = (d && d.symbol) || "—";
  const grainMap = TF_GRAIN[kind === "crypto" ? "crypto" : "stock"];
  $("#ltcKind").textContent = (kind === "crypto" ? "Crypto · " : "Stock · ") + (grainMap[liveTf] || "");
  renderTfButtons(kind);
  _renderSqueezeChip(liveOverlay);
  _renderEmaLegend(liveOverlay);

  // Reset the viewport whenever the identity of the tape changes so a fresh
  // symbol / timeframe starts with all bars visible (not stuck on a stale window).
  const sym = d && d.symbol;
  if (sym !== lastRenderSym || liveTf !== lastRenderTf) {
    resetChartView();
    // A cursor is a position within ONE tape. Changing symbol or timeframe
    // makes it meaningless, so drop it rather than carry a stale index across.
    replay.on = false;
    replay.cursorTs = null;
    replay.fromTs = null;
    _replayStop();
    lastRenderSym = sym;
    lastRenderTf = liveTf;
  }

  // Re-seat the cursor against this tape before anything reads from/upto/end.
  _syncCursorRange(d);

  // Slice to viewport. `count == null` means "use the compact per-tf default"
  // (much easier to read than the whole loaded array); otherwise clamp to
  // sane bounds. If pinned, glue to the right edge as new bars arrive.
  const nAll = fullOhlc.length;

  let start, end;
  // How many slots the x-axis is scaled for, and which bars set the price
  // range. Both equal the drawn window in normal use; replay widens them.
  let scaleN = null, priceFrom = null, priceTo = null;

  if (replay.on && nAll > 1) {
    // Replay owns the window outright. Reveal [from..upto], but scale the axis
    // to the WHOLE session so revealed candles hold fixed x positions and march
    // left to right, and price-scale to the whole session too so the ladder
    // doesn't lurch on every step — you're watching price move, not the chart
    // rescale under it.
    start = Math.max(0, Math.min(replay.from, nAll - 1));
    end = Math.max(start + 1, Math.min(replay.upto + 1, nAll));
    scaleN = Math.max(1, Math.min(replay.end, nAll - 1) - start + 1);
    priceFrom = start;
    priceTo = Math.min(replay.end + 1, nAll);
  } else {
    const defaultN = Math.min(nAll, DEFAULT_VISIBLE[liveTf] || 78);
    const count = chartView.count == null ? defaultN : Math.max(MIN_VISIBLE_BARS, Math.min(nAll, chartView.count));
    if (chartView.pinned || chartView.start == null) {
      start = Math.max(0, nAll - count);
    } else {
      // Re-locate the left edge by TIMESTAMP. Using the stored index here is what
      // let the tape slide: the index is stable but the data under it is not.
      let idx = chartView.start;
      if (chartView.anchorTs && fullTs.length === nAll) {
        const found = _indexOfTs(fullTs, chartView.anchorTs);
        if (found >= 0) idx = found;
        // found < 0 → the anchor aged out of the window; fall back to the index
        // and clamp, which parks the user at the oldest bar we still hold.
      }
      start = Math.max(0, Math.min(nAll - count, idx));
    }
    end = start + count;
    // Record where we actually landed so the next poll can find this bar again.
    chartView.start = start;
    chartView.anchorTs = (fullTs.length === nAll && fullTs[start]) || null;
  }
  const ohlc = fullOhlc.slice(start, end);
  const tsArr = fullTs.slice(start, end);
  const volArr = fullVol.slice(start, end);

  // Live needs two bars before a chart means anything. Replay legitimately
  // starts with ONE — the opening candle, alone on the left, is the point.
  const minBars = replay.on ? 1 : 2;
  liveLast = { data: d, kind, ok: ohlc.length >= minBars };
  // The dial is a live control now, not a replay-mode artefact: its range has
  // to track the growing tape on EVERY render, or it sits at 0..0 and can't be
  // dragged at all. Runs after liveLast so the clock can read the cursor bar.
  _syncReplayUI();
  if (ohlc.length < minBars) {
    svg.innerHTML = "";
    $("#ltcLast").textContent = "—";
    $("#ltcChg").textContent = "";
    // The 1m note used to say Yahoo only serves the current session. That was
    // true when 1m asked for a one-day range; it now pulls five days, so an
    // empty 1m chart means the symbol has no tape at all, not that it's early.
    $("#ltcFoot").textContent = kind === "crypto"
      ? "No candles for this coin at this timeframe — try BTC, ETH, SOL…"
      : "No candles for this symbol at this timeframe — check the ticker.";
    return;
  }

  // Webull-style layout: candles left, price ladder right, time axis below,
  // volume pane between them.
  const W = 1000, H = 360;
  const padL = 8, padT = 10;
  const AXIS_R = 58;   // right price ladder width
  const AXIS_B = 22;   // bottom time-label strip height
  // Volume off gives its height back to the candles rather than leaving a gap.
  const VOL_H = chartInd.showVolume ? 46 : 0;
  const VOL_GAP = chartInd.showVolume ? 4 : 0;
  const priceRect = {
    x: padL, y: padT,
    w: W - padL - AXIS_R,
    h: H - padT - AXIS_B - VOL_H - VOL_GAP,
  };
  const volRect = { x: padL, y: priceRect.y + priceRect.h + VOL_GAP, w: priceRect.w, h: VOL_H };
  const timeAxisTop = volRect.y + volRect.h;

  const c = candlesInRect(ohlc, priceRect, scaleN,
    priceFrom != null ? fullOhlc.slice(priceFrom, priceTo) : null);
  const clampY = (v) => Math.max(priceRect.y, Math.min(priceRect.y + priceRect.h, c.Y(v)));
  const last = ohlc[ohlc.length - 1][3];
  liveLast.geom = {
    W, H, pad: padL, X: c.X, Y: c.Y, n: ohlc.length, ohlc, ts: tsArr,
    priceRect, volRect, timeAxisTop, axisR: AXIS_R,
    priceMin: c.min, priceMax: c.max,
    // Shared slot mapping — pan, zoom, snap and hit-test all invert through it.
    slot: c.slot,
    // Viewport bookkeeping so wheel/drag can operate against the full tape.
    fullOhlc, fullTs, fullVol, viewStart: start, viewCount: end - start, viewEnd: end, nAll,
  };

  // STATIC layer — anchored to the frame. The price ladder and grid must not
  // slide when the tape rolls, or the whole chart looks like it's sloshing.
  let staticLayer = "";
  staticLayer += _priceGridSVG(priceRect, c.min, c.max);
  staticLayer += _priceAxisSVG(priceRect, c.min, c.max, last, AXIS_R, W);
  staticLayer += `<line x1="${priceRect.x}" y1="${clampY(last).toFixed(1)}" x2="${priceRect.x + priceRect.w}" y2="${clampY(last).toFixed(1)}"
    stroke="var(--text-dim)" stroke-width="1" stroke-dasharray="2 3" opacity="0.5"/>`;

  // ROLLING layer — everything pinned to a bar position. This is the group we
  // translate when a new candle arrives, so the tape visibly travels instead
  // of teleporting one bar to the left.
  let base = "";
  // In replay the axis labels the whole session and the volume pane keeps the
  // session's max, so neither rescales as candles are revealed.
  const axisTs = priceFrom != null ? fullTs.slice(priceFrom, priceTo) : null;
  const volMax = priceFrom != null
    ? Math.max(...fullVol.slice(priceFrom, priceTo).map((v) => v || 0), 1)
    : null;
  base += _sessionDividersSVG(priceRect, ohlc, tsArr, timeAxisTop, c.slot);
  base += c.markup;
  if (chartInd.showVolume) base += _volumeSVG(volRect, ohlc, volArr, c.slot, volMax);
  base += _timeAxisSVG(priceRect, ohlc, tsArr, liveTf, kind, timeAxisTop, c.slot, axisTs);

  let overlay = "";
  const p = getLive();
  if (p && p.sym && d.symbol && p.sym.toUpperCase() === String(d.symbol).toUpperCase()) {
    overlay += `<line x1="${priceRect.x}" y1="${clampY(p.entry).toFixed(1)}" x2="${priceRect.x + priceRect.w}" y2="${clampY(p.entry).toFixed(1)}"
      stroke="var(--gold)" stroke-width="1.8" stroke-dasharray="6 4" filter="url(#neonGold)"><title>your entry ${p.entry}</title></line>`;
  }
  // Daily EMA(14/21/57) polylines — interpolated onto the intraday grid so
  // they span the whole width at any timeframe.
  if (liveOverlay && liveOverlay.emas) {
    // Pass the whole overlay: the renderer needs `periods` for draw order and
    // `tf` for the tooltip, not just the series map.
    overlay += _emaOverlaySVG(liveLast.geom, clampY, liveOverlay);
  }
  overlay += _userOverlaySVG(d.symbol, liveLast.geom, clampY);

  if (trendAnchor) {
    const a = _tsToXY(liveLast.geom, trendAnchor.ts, trendAnchor.price);
    if (a) {
      const ay = clampY(trendAnchor.price);
      overlay += `<line x1="${priceRect.x}" y1="${ay.toFixed(1)}" x2="${priceRect.x + priceRect.w}" y2="${ay.toFixed(1)}"
        stroke="var(--gold)" stroke-width="1" stroke-dasharray="2 4" opacity="0.55"/>`;
      overlay += `<circle cx="${a.x.toFixed(1)}" cy="${ay.toFixed(1)}" r="6.5"
        fill="var(--gold)" fill-opacity="0.35" stroke="var(--gold)" stroke-width="2"
        filter="url(#neonGold)"><title>target ${trendAnchor.price} — press &amp; drag anywhere to draw the trend</title></circle>`;
    }
  }
  if (trendPreview) {
    overlay += `<line x1="${trendPreview.ax.toFixed(1)}" y1="${trendPreview.ay.toFixed(1)}"
      x2="${trendPreview.bx.toFixed(1)}" y2="${trendPreview.by.toFixed(1)}"
      stroke="var(--gold)" stroke-width="2" stroke-dasharray="6 4" opacity="0.95"
      filter="url(#neonGold)"/>`;
  }

  // ltcCrosshair is updated separately in _drawCrosshair — no full redraw on hover.
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  // The rolling group is clipped to the candle area so a mid-roll translate
  // can never bleed under the price ladder.
  const clipW = priceRect.w + c.slot.w * RIGHT_PAD_SLOTS;
  svg.innerHTML = _neonDefsSVG()
    + `<clipPath id="ltcRollClip"><rect x="${priceRect.x}" y="0" width="${Math.min(clipW, W - priceRect.x - AXIS_R + 2).toFixed(1)}" height="${H}"/></clipPath>`
    + `<g id="ltcStatic">${staticLayer}</g>`
    + `<g id="ltcRoll" clip-path="url(#ltcRollClip)"><g id="ltcBase">${base}${overlay}</g></g>`
    + `<g id="ltcCrosshair" pointer-events="none"></g>`;
  _playRoll(c.slot.w, fullTs, sym);

  const first = ohlc[0][3];
  const chg = first ? (last - first) / first * 100 : 0;
  $("#ltcLast").textContent = fmtPrice(last);
  const chgEl = $("#ltcChg");
  chgEl.textContent = (chg >= 0 ? "▲ " : "▼ ") + Math.abs(chg).toFixed(2) + "%";
  chgEl.className = "ltc-chg " + (chg >= 0 ? "up" : "down");

  // A scrubbed-back price is NOT the market price. In a trading app that
  // confusion is the expensive kind, so say it in the header rather than
  // relying on the user noticing the dial isn't at the end.
  const asOf = $("#ltcAsOf");
  const cursorTs = replay.on && fullTs[replay.upto];
  if (asOf) {
    asOf.hidden = !replay.on;
    asOf.textContent = cursorTs
      ? `as of ${_fmtAxisTime(new Date(cursorTs * 1000), liveTf)} · not live`
      : "not live";
  }
  const card = $("#liveTradeCard");
  if (card) card.classList.toggle("is-rewound", !!replay.on);

  const cadence = TF_POLL_MS[liveTf] / 1000;
  $("#ltcFoot").textContent = replay.on
    ? `Rewound to an earlier bar — later candles hidden, price above is NOT current. Live data still updating; hit GO LIVE to catch up · educational, not advice`
    : `Live candles · gold line = your entry · refreshes ~${cadence}s · Mark drops entries, Trend line = click target + drag · educational, not advice`;
}

/* ---- Webull-style chart primitives ---- */

/* Slot geometry — the single source of truth for "where does bar i sit".
 *
 * The old mapping was `i / (n - 1) * rect.w`, which stretches the FIRST and
 * LAST bars onto the rect's edges. Two things a trader feels immediately:
 * bar 0 is sliced in half by the left edge, and the newest bar is pinned under
 * the price ladder with its right half clipped — so the candle that is still
 * forming is the one you can't actually see.
 *
 * Webull instead gives every bar its own slot, centred, and leaves a few EMPTY
 * slots at the right edge. That gap is what the live candle forms in and
 * travels across before the tape rolls left. Without it a new bar has nowhere
 * to appear except on top of the axis.
 */
const RIGHT_PAD_SLOTS = 6;

/* `scaleN` decouples "how many bars are DRAWN" from "how many the axis is
 * scaled for". They are the same in normal use, but replay needs them apart:
 * the day's full bar count sets the slot width once, and revealed candles then
 * appear at fixed positions marching left to right. Scaling to the revealed
 * count instead would restretch the whole tape on every step, which reads as
 * the chart breathing rather than the session playing forward.
 */
function chartSlot(rect, n, scaleN) {
  const slots = Math.max(1, (scaleN == null ? n : scaleN) + RIGHT_PAD_SLOTS);
  const w = rect.w / slots;
  return {
    w,
    slots,
    // Centre of bar i. Valid past n-1 too — that range is the headroom.
    X: (i) => rect.x + (i + 0.5) * w,
    // Inverse: pixel x back to a fractional bar index.
    barAt: (x) => (x - rect.x) / w - 0.5,
  };
}

function candlesInRect(ohlc, rect, scaleN, priceBars) {
  // `priceBars` lets the price range span more than what's drawn — replay uses
  // the whole session so the ladder holds still while candles appear.
  const pb = (priceBars && priceBars.length) ? priceBars : ohlc;
  const highs = pb.map((b) => b[1]), lows = pb.map((b) => b[2]);
  const min = Math.min(...lows), max = Math.max(...highs), span = max - min || 1;
  const n = ohlc.length;
  const sg = chartSlot(rect, n, scaleN);
  const X = sg.X;
  const Y = (v) => rect.y + (1 - (v - min) / span) * rect.h;
  const slot = sg.w;
  const bw = Math.max(1, Math.min(slot * 0.7, 9));
  const wick = Math.max(0.6, Math.min(bw * 0.28, 2));
  let out = "";
  for (let i = 0; i < n; i++) {
    const [o, h, l, c] = ohlc[i];
    const up = c >= o;
    const col = up ? "var(--buy)" : "var(--sell)";
    const x = X(i);
    const yH = Y(h), yL = Y(l);
    const yO = Y(o), yC = Y(c);
    const top = Math.min(yO, yC), bot = Math.max(yO, yC);
    const bodyH = Math.max(1, bot - top);
    out += `<line x1="${x.toFixed(1)}" y1="${yH.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yL.toFixed(1)}" stroke="${col}" stroke-width="${wick.toFixed(2)}"/>`;
    out += `<rect x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${col}" rx="0.5"/>`;
  }
  return { markup: out, X, Y, min, max, slot: sg };
}

function _fmtAxisPrice(v) {
  if (!isFinite(v)) return "";
  if (Math.abs(v) >= 10000) return v.toFixed(0);
  if (Math.abs(v) >= 100) return v.toFixed(1);
  if (Math.abs(v) >= 1) return v.toFixed(2);
  return v.toFixed(4);
}

/* Vertical divider + tiny date label at every session boundary — every time
   the calendar day changes bar-to-bar. Draws BEHIND the candles so the price
   action stays visually dominant, but the eye immediately clocks "new day
   here" instead of reading the overnight gap as a random blank. */
function _sessionDividersSVG(rect, ohlc, tsArr, timeAxisTop, slotGeom) {
  const n = ohlc.length;
  if (!tsArr || tsArr.length !== n || n < 2) return "";
  const sg = slotGeom || chartSlot(rect, n);
  const X = sg.X;
  let out = "";
  let prevKey = null;
  // Density guard: at deep zoom-out one divider per bar is noise. Cap to
  // one label every ~55px so labels never overlap.
  const minLabelPx = 55;
  const barPx = sg.w;
  const labelStride = Math.max(1, Math.ceil(minLabelPx / Math.max(1, barPx)));
  let idxSinceLabel = labelStride;
  const bottom = (timeAxisTop != null ? timeAxisTop : rect.y + rect.h).toFixed(1);
  for (let i = 0; i < n; i++) {
    const t = tsArr[i];
    if (!t) continue;
    const d = new Date(t * 1000);
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    if (prevKey !== null && key !== prevKey) {
      const x = X(i).toFixed(1);
      out += `<line x1="${x}" y1="${rect.y.toFixed(1)}" x2="${x}" y2="${bottom}"
        stroke="rgba(120,180,255,0.18)" stroke-width="1" stroke-dasharray="3 5"/>`;
      if (idxSinceLabel >= labelStride) {
        const label = d.toLocaleDateString([], { month: "short", day: "numeric" });
        out += `<text x="${(X(i) + 4).toFixed(1)}" y="${(rect.y + 12).toFixed(1)}"
          fill="rgba(160,190,230,0.65)" font-family="var(--mono)" font-size="10"
          font-weight="600" letter-spacing="0.01em">${label}</text>`;
        idxSinceLabel = 0;
      }
    }
    idxSinceLabel++;
    prevKey = key;
  }
  return out;
}

function _priceGridSVG(rect, min, max) {
  const steps = 5;
  let out = "";
  for (let i = 0; i <= steps; i++) {
    const y = rect.y + rect.h * (i / steps);
    out += `<line x1="${rect.x}" y1="${y.toFixed(1)}" x2="${rect.x + rect.w}" y2="${y.toFixed(1)}"
      stroke="rgba(120,150,190,0.06)" stroke-width="1"/>`;
  }
  return out;
}

function _priceAxisSVG(rect, min, max, last, axisRW, W) {
  const steps = 5;
  const axisX = rect.x + rect.w;
  const span = max - min || 1;
  let out = "";
  for (let i = 0; i <= steps; i++) {
    const v = min + span * (1 - i / steps);   // top-to-bottom (highest first)
    const y = rect.y + rect.h * (i / steps);
    out += `<text x="${axisX + 6}" y="${(y + 3).toFixed(1)}" fill="var(--text-dim)"
      font-family="var(--mono)" font-size="10.5" font-weight="600" letter-spacing="0.01em">${_fmtAxisPrice(v)}</text>`;
  }
  // Floating last-price tag — Webull's signature.
  const ly = rect.y + (1 - (last - min) / span) * rect.h;
  const y = Math.max(rect.y + 8, Math.min(rect.y + rect.h - 8, ly));
  out += `<rect x="${(axisX + 2).toFixed(1)}" y="${(y - 8).toFixed(1)}" width="${axisRW - 6}" height="16" rx="3"
    fill="var(--gold)" opacity="0.94" filter="url(#neonGold)"/>`;
  out += `<text x="${(axisX + axisRW / 2 - 1).toFixed(1)}" y="${(y + 3).toFixed(1)}" fill="#0a0d12"
    font-family="var(--mono)" font-size="10.5" font-weight="800" text-anchor="middle">${_fmtAxisPrice(last)}</text>`;
  return out;
}

// Intraday bars get a CLOCK; only daily and weekly get a date. This used to
// key off `tf === "1m"` (plus a "day" value that no longer exists), so a 5m
// chart covering one 6.5-hour session printed "Jul 30" at all six ticks —
// six identical labels that tell you nothing about where you are in the day.
// The date still gets said once per session change, by _sessionDividersSVG.
const TIME_AXIS_TFS = new Set(["1m", "5m", "10m", "15m", "30m", "1h"]);

function _fmtAxisTime(dt, tf) {
  if (TIME_AXIS_TFS.has(tf)) {
    return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return dt.toLocaleDateString([], { month: "short", day: "numeric" });
}

function _timeAxisSVG(rect, ohlc, tsArr, tf, kind, top, slotGeom, axisTs) {
  const n = ohlc.length;
  if (!tsArr || tsArr.length !== n) return "";
  const sg = slotGeom || chartSlot(rect, n);
  // `axisTs` labels the FULL scaled span rather than just what's drawn. Replay
  // needs it: with 7 of 79 candles revealed, spreading six ticks across the
  // drawn bars crushes every label into the leftmost inch. The axis should show
  // the whole session and let candles fill in underneath it.
  const labelTs = (axisTs && axisTs.length) ? axisTs : tsArr;
  const labelN = labelTs.length;
  let out = `<line x1="${rect.x}" y1="${top.toFixed(1)}" x2="${rect.x + rect.w}" y2="${top.toFixed(1)}"
    stroke="rgba(120,150,190,0.14)" stroke-width="1"/>`;
  // With a single bar (replay's first candle) six evenly-spaced ticks would all
  // resolve to index 0 and stack on top of each other.
  const steps = labelN < 2 ? 0 : 5;
  for (let i = 0; i <= steps; i++) {
    const idx = steps === 0 ? 0 : Math.round((labelN - 1) * i / steps);
    const ts = labelTs[idx];
    if (!ts) continue;
    const x = sg.X(idx);
    const label = _fmtAxisTime(new Date(ts * 1000), tf);
    out += `<line x1="${x.toFixed(1)}" y1="${top.toFixed(1)}" x2="${x.toFixed(1)}" y2="${(top + 4).toFixed(1)}"
      stroke="var(--text-dim)" stroke-width="1"/>`;
    out += `<text x="${x.toFixed(1)}" y="${(top + 14).toFixed(1)}" fill="var(--text-dim)"
      font-family="var(--mono)" font-size="10.5" font-weight="600" text-anchor="middle">${label}</text>`;
  }
  return out;
}

function _volumeSVG(rect, ohlc, volume, slotGeom, maxOverride) {
  if (!volume || volume.length !== ohlc.length || volume.every((v) => !v)) return "";
  // maxOverride keeps the pane scaled to the whole session during replay, so
  // early bars don't shrink each time a bigger one is revealed.
  const max = maxOverride || Math.max(...volume) || 1;
  const n = volume.length;
  // Same slots as the candles, or the histogram walks out from under them.
  // volRect shares priceRect's x and width, so the candles' geometry fits.
  const sg = slotGeom || chartSlot(rect, n);
  const bw = Math.max(1, Math.min(sg.w * 0.7, 9));
  let out = `<line x1="${rect.x}" y1="${rect.y.toFixed(1)}" x2="${rect.x + rect.w}" y2="${rect.y.toFixed(1)}"
    stroke="rgba(120,150,190,0.10)" stroke-width="1" stroke-dasharray="2 4"/>`;
  for (let i = 0; i < n; i++) {
    const h = (volume[i] / max) * rect.h;
    const x = sg.X(i);
    const y = rect.y + rect.h - h;
    const [o, , , c] = ohlc[i];
    const col = c >= o ? "rgba(47,209,128,0.42)" : "rgba(255,93,108,0.42)";
    out += `<rect x="${(x - bw / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${col}"/>`;
  }
  out += `<text x="${(rect.x + 4).toFixed(1)}" y="${(rect.y + 11).toFixed(1)}"
    fill="var(--text-faint)" font-family="var(--mono)" font-size="9" letter-spacing="0.14em">VOL</text>`;
  return out;
}

function _drawCrosshair(x, y) {
  const g = liveLast.geom; if (!g) return _clearCrosshair();
  const r = g.priceRect;
  if (x < r.x || x > r.x + r.w || y < r.y || y > r.y + r.h) return _clearCrosshair();
  const el = $("#ltcCrosshair"); if (!el) return;

  // Snap the crosshair to the nearest OHLC point unless Alt bypasses it.
  const snap = altHeld ? null : _getSnapCandidate(x, y);
  const cx = snap ? snap.x : x;
  const cy = snap ? snap.y : y;
  const p = _pixelToTsPrice(cx, cy);
  if (snap) { p.price = snap.price; p.ts = snap.ts; }
  const priceLabelX = r.x + r.w;
  const when = p && p.ts ? _fmtAxisTime(new Date(p.ts * 1000), liveTf) : "";
  const priceStr = p ? _fmtAxisPrice(p.price) : "";
  const snapCol = snap ? snap.color : "var(--gold)";
  const snapDot = snap
    ? `<rect x="${(cx - 4).toFixed(1)}" y="${(cy - 4).toFixed(1)}" width="8" height="8"
        transform="rotate(45 ${cx.toFixed(1)} ${cy.toFixed(1)})"
        fill="${snap.color}" stroke="rgba(10,13,18,0.9)" stroke-width="1"/>
       <text x="${(cx + 8).toFixed(1)}" y="${(cy - 8).toFixed(1)}" fill="${snap.color}"
        font-family="var(--mono)" font-size="9" font-weight="700" letter-spacing="0.08em">${snap.kind.toUpperCase()}</text>`
    : "";

  // 1px physical-pixel lines regardless of chart size — sharper reads.
  const strokeW = 1 / (g.pxPerSvgY || 1);
  const lineCol = snap ? snapCol : "rgba(217,176,97,0.65)";
  el.innerHTML = `
    <line x1="${r.x}" y1="${cy.toFixed(2)}" x2="${(r.x + r.w).toFixed(2)}" y2="${cy.toFixed(2)}"
      stroke="${lineCol}" stroke-width="${strokeW.toFixed(2)}" stroke-dasharray="4 4" shape-rendering="crispEdges"/>
    <line x1="${cx.toFixed(2)}" y1="${r.y}" x2="${cx.toFixed(2)}" y2="${(r.y + r.h).toFixed(2)}"
      stroke="${lineCol}" stroke-width="${strokeW.toFixed(2)}" stroke-dasharray="4 4" shape-rendering="crispEdges"/>
    <circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="1.4" fill="${snap ? snapCol : "var(--gold)"}" opacity="0.95"/>
    <rect x="${(priceLabelX + 2).toFixed(1)}" y="${(cy - 8).toFixed(1)}"
      width="${g.axisR - 6}" height="16" rx="3"
      fill="rgba(10,13,18,0.96)" stroke="${snapCol}" stroke-width="1"/>
    <text x="${(priceLabelX + g.axisR / 2 - 1).toFixed(1)}" y="${(cy + 3).toFixed(1)}"
      fill="${snapCol}" font-family="var(--mono)" font-size="10.5" font-weight="800" text-anchor="middle">${priceStr}</text>
    <rect x="${(cx - 28).toFixed(1)}" y="${(g.timeAxisTop + 2).toFixed(1)}"
      width="56" height="16" rx="3" fill="rgba(10,13,18,0.96)" stroke="${snapCol}" stroke-width="1"/>
    <text x="${cx.toFixed(1)}" y="${(g.timeAxisTop + 13).toFixed(1)}"
      fill="${snapCol}" font-family="var(--mono)" font-size="10" font-weight="700" text-anchor="middle">${when}</text>
    ${snapDot}
  `;
}

function _clearCrosshair() {
  const el = $("#ltcCrosshair"); if (el) el.innerHTML = "";
}

/* ---- Precision snap to candle OHLC ---- */

// Return the nearest {high, low, open, close} point on candles near the
// cursor, or null if nothing is within SNAP_PHYS_PX *screen pixels*. Checks
// the nearest candle and its two neighbors so snap kicks in even when the
// cursor is between wicks. Colors follow the semantic role of the point so
// the user can eyeball which they're grabbing.
function _getSnapCandidate(x, y) {
  const g = liveLast.geom;
  if (!g || !g.ohlc || !g.ohlc.length) return null;
  const scale = g.pxPerSvgX && g.pxPerSvgY;
  // Convert the physical-pixel threshold back to SVG units on each axis.
  const thX = SNAP_PHYS_PX / (g.pxPerSvgX || 1);
  const thY = SNAP_PHYS_PX / (g.pxPerSvgY || 1);
  const r = g.priceRect;
  // Invert through the SAME slot mapping the candles were drawn with.
  const raw = g.slot ? g.slot.barAt(x) : ((x - r.x) / r.w) * (g.n - 1);
  const nearest = Math.max(0, Math.min(g.n - 1, Math.round(raw)));
  const indices = [nearest - 1, nearest, nearest + 1].filter((i) => i >= 0 && i < g.n);
  let best = null, bestD = Infinity;
  for (const idx of indices) {
    const cx = g.X(idx);
    const [o, h, l, c] = g.ohlc[idx];
    const opts = [
      { price: h, kind: "high",  color: "var(--buy)"  },
      { price: l, kind: "low",   color: "var(--sell)" },
      { price: o, kind: "open",  color: "var(--gold)" },
      { price: c, kind: "close", color: "var(--gold)" },
    ];
    for (const opt of opts) {
      const py = g.Y(opt.price);
      // Normalize distance to physical pixels so 1px in X and 1px in Y count equally.
      const dxPx = (cx - x) * (g.pxPerSvgX || 1);
      const dyPx = (py - y) * (g.pxPerSvgY || 1);
      const d = Math.hypot(dxPx, dyPx);
      if (d < bestD) { bestD = d; best = { ...opt, x: cx, y: py, idx, ts: (g.ts && g.ts[idx]) || 0 }; }
    }
  }
  if (bestD > SNAP_PHYS_PX) return null;
  return best;
}

/* ---- Hit-testing existing marks + trend-line endpoints ---- */

function _hitTestMarker(x, y) {
  const g = liveLast.geom;
  const sym = liveLast.data && liveLast.data.symbol;
  if (!g || !sym) return null;
  const px = g.pxPerSvgX || 1, py = g.pxPerSvgY || 1;
  const inRange = (dx, dy) => Math.hypot(dx * px, dy * py) <= HIT_PHYS_PX;
  const marks = getUserMarks(sym);
  for (let i = marks.length - 1; i >= 0; i--) {
    const m = marks[i];
    const pt = _tsToXY(g, m.ts, m.price);
    if (!pt) continue;
    if (inRange(pt.x - x, g.Y(m.price) - y)) return { kind: "mark", idx: i, mark: m };
  }
  const lines = getUserLines(sym);
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    const a = _tsToXY(g, l.a && l.a.ts, l.a && l.a.price);
    const b = _tsToXY(g, l.b && l.b.ts, l.b && l.b.price);
    if (a && inRange(a.x - x, g.Y(l.a.price) - y)) return { kind: "lineA", idx: i, line: l };
    if (b && inRange(b.x - x, g.Y(l.b.price) - y)) return { kind: "lineB", idx: i, line: l };
  }
  return null;
}

function _deleteHit(hit, sym) {
  const k = _ltcKeys(sym);
  if (hit.kind === "mark") {
    const marks = getUserMarks(sym);
    marks.splice(hit.idx, 1);
    _writeArr(k.marks, marks);
  } else {
    const lines = getUserLines(sym);
    lines.splice(hit.idx, 1);
    _writeArr(k.lines, lines);
  }
  if (typeof toast === "function") toast("sell", "Deleted");
}

function _commitEdit() {
  if (!editState || !editPreview) return;
  const sym = editState.sym;
  const k = _ltcKeys(sym);
  if (editState.kind === "mark") {
    const marks = getUserMarks(sym);
    if (marks[editState.idx]) {
      marks[editState.idx] = { ...marks[editState.idx], ts: editPreview.ts, price: editPreview.price };
      _writeArr(k.marks, marks);
    }
  } else {
    const end = editState.kind === "lineA" ? "a" : "b";
    const lines = getUserLines(sym);
    if (lines[editState.idx]) {
      lines[editState.idx] = { ...lines[editState.idx], [end]: { ts: editPreview.ts, price: editPreview.price } };
      _writeArr(k.lines, lines);
    }
  }
}

/* ---- Neon defs, grid, and user overlays for the live chart ---- */

function _neonDefsSVG() {
  return `<defs>
    <filter id="neonGold" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="neonBuy" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="neonSell" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>`;
}

// Convert a stored (ts, price) point to (x, y) using current geometry. Falls
// back to first/last candle when the ts is outside the visible tape.
function _tsToXY(geom, ts, price) {
  if (!geom) return null;
  const { X, Y, ts: tsArr, n } = geom;
  let idx = 0;
  if (tsArr && tsArr.length === n && ts) {
    // Clip to the visible window so a mark whose timestamp is scrolled off
    // the chart doesn't render as a stray blob at the nearest edge candle.
    const first = tsArr[0], last = tsArr[n - 1];
    const step = n > 1 ? Math.max(1, (last - first) / (n - 1)) : 1;
    if (ts < first - step || ts > last + step) return null;
    let bestD = Infinity;
    for (let i = 0; i < tsArr.length; i++) {
      const d = Math.abs(tsArr[i] - ts);
      if (d < bestD) { bestD = d; idx = i; }
    }
  }
  return { x: X(idx), y: Y(price), idx };
}

function _userOverlaySVG(symbol, geom, clampY) {
  const marks = getUserMarks(symbol);
  const lines = getUserLines(symbol);
  const r = geom.priceRect || { x: geom.pad, y: 0, w: geom.W - geom.pad * 2, h: geom.H };
  const isEditing = editState && editState.sym === symbol && editPreview;
  let out = "";
  for (let i = 0; i < lines.length; i++) {
    let l = lines[i];
    if (isEditing && editState.idx === i) {
      if (editState.kind === "lineA") l = { ...l, a: { ...l.a, ts: editPreview.ts, price: editPreview.price } };
      if (editState.kind === "lineB") l = { ...l, b: { ...l.b, ts: editPreview.ts, price: editPreview.price } };
    }
    const a = _tsToXY(geom, l.a && l.a.ts, l.a && l.a.price);
    const b = _tsToXY(geom, l.b && l.b.ts, l.b && l.b.price);
    if (!a || !b) continue;
    const col = l.color || "var(--gold)";
    out += `<line x1="${a.x.toFixed(1)}" y1="${clampY(l.a.price).toFixed(1)}"
      x2="${b.x.toFixed(1)}" y2="${clampY(l.b.price).toFixed(1)}"
      stroke="${col}" stroke-width="1.6" opacity="0.9" filter="url(#neonGold)"/>`;
    // Endpoint handles — visible + hit-testable.
    const ax = a.x, ay = clampY(l.a.price), bx = b.x, by = clampY(l.b.price);
    const editingA = isEditing && editState.kind === "lineA" && editState.idx === i;
    const editingB = isEditing && editState.kind === "lineB" && editState.idx === i;
    out += `<circle cx="${ax.toFixed(1)}" cy="${ay.toFixed(1)}" r="${editingA ? 5 : 3.5}" fill="${col}" fill-opacity="${editingA ? 0.9 : 0.65}" stroke="var(--bg)" stroke-width="1"/>`;
    out += `<circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="${editingB ? 5 : 3.5}" fill="${col}" fill-opacity="${editingB ? 0.9 : 0.65}" stroke="var(--bg)" stroke-width="1"/>`;
  }
  for (let i = 0; i < marks.length; i++) {
    let m = marks[i];
    if (isEditing && editState.kind === "mark" && editState.idx === i) {
      m = { ...m, ts: editPreview.ts, price: editPreview.price };
    }
    const p = _tsToXY(geom, m.ts, m.price);
    if (!p) continue;
    const y = clampY(m.price);
    const col = m.dir === "put" || m.dir === "short" ? "var(--sell)"
              : m.dir === "call" || m.dir === "long" ? "var(--buy)"
              : "var(--gold)";
    const filt = col.includes("sell") ? "neonSell" : col.includes("buy") ? "neonBuy" : "neonGold";
    const editingMe = isEditing && editState.kind === "mark" && editState.idx === i;
    out += `<line x1="${r.x}" y1="${y.toFixed(1)}" x2="${(r.x + r.w).toFixed(1)}" y2="${y.toFixed(1)}"
      stroke="${col}" stroke-width="1" stroke-dasharray="2 5" opacity="0.35"/>`;
    out += `<circle cx="${p.x.toFixed(1)}" cy="${y.toFixed(1)}" r="${editingMe ? 7 : 5.5}" fill="${editingMe ? col : "none"}" fill-opacity="${editingMe ? 0.4 : 1}"
      stroke="${col}" stroke-width="${editingMe ? 2.8 : 2.2}" filter="url(#${filt})">
      <title>${esc(m.note || (m.dir || "mark") + " @ " + m.price)} — drag to move, Alt-click to delete</title></circle>`;
  }
  return out;
}

