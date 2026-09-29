/* MarketPulse — live trading chart.
 *
 * Owns WHAT the live chart shows: the intraday tape and its timeframe, the
 * refresh cadence, the EMA / TTM squeeze overlays, the replay dial, and the
 * trader's saved marks and trend lines. HOW it is drawn lives in
 * chart-engine.js (TradingView Lightweight Charts) and chart-draw.js; mouse and
 * keyboard tools live in chart-tools.js.
 *
 * Loaded BEFORE app.js (see index.html): app.js calls init() on its last line,
 * and that path reaches into this file, so these declarations must already
 * exist. Everything here is a declaration — nothing runs at load time.
 *
 * Shares the global helpers declared in app.js ($, store, state, esc, ...).
 * All of these are classic scripts, so they share one global scope.
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
  // Pre-market and after-hours candles. OFF by default: turning it on changes
  // what the chart shows, and extended bars are thin enough that they must
  // never feed an indicator (the server strips them before computing).
  showPrePost: false,
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
const EMA_COLORS = PC_EMA_COLORS;          // chart-theme.js, shared with the landing chart

// In-memory snapshot of the last loaded intraday payload. Learning Mode reads
// the tape from here, and the drawing tools read which symbol is on screen.
let liveLast = { data: null, kind: "stock", ok: false };
// A running lesson (lesson-player.js) owns the chart: its frozen tape, drawings and
// levels replace the live ones until it stops. null = the live chart as usual.
let lessonView = null;
// Every chart load takes a ticket; only the newest may paint. A slow reply for the
// symbol you just left must never land on top of the one you switched to.
let liveLoadSeq = 0;

let lastRenderSym = null, lastRenderTf = null;
// Sensible default "compact" viewport per timeframe — chosen so a new tape
// opens showing recent context at a comfortable candle width, not the whole
// loaded array crammed into one screen. Wheel/pinch zooms out to the full history.
const DEFAULT_VISIBLE = { "1m": 90, "5m": 78, "10m": 78, "15m": 78,
                          "30m": 70, "1h": 60, "1D": 90, "1W": 60 };
/* Ask the next render to re-frame the default window (new symbol, GO LIVE,
 * double-click). The engine owns the viewport itself: pan, zoom, and holding a
 * view still on a rolling tape are all in chart-engine.js now. */
function resetChartView() { pcWantReset = true; }

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

/* Last bar of the calendar day that bar `from` opens. Replay frames and scales
 * to that one session, not to the end of the tape: a drill into Tuesday must
 * not squeeze Tuesday into a sliver of the week, or scale its price ladder to
 * the days after it. On daily and weekly bars the unit is the whole range. */
function _sessionEndIdx(tsArr, from) {
  const last = (tsArr ? tsArr.length : 0) - 1;
  if (last < 0 || !TIME_AXIS_TFS.has(liveTf)) return last;
  const key = (t) => { const d = new Date(t * 1000); return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; };
  const want = key(tsArr[from]);
  let i = from;
  while (i < last && key(tsArr[i + 1]) === want) i++;
  return i;
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
  if (lessonView) return;                  // the lesson drives the dial
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
  if (lessonView) return;                  // GO LIVE belongs to the live chart; Exit ends a lesson
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
  if (lessonView) return;
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
  if (lessonView) return;
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
      // Mid-lesson, the tap means "show me this timeframe live": end the lesson first,
      // or its hand-back would restore the old timeframe over the one just picked.
      if (lessonView && typeof lessonStop === "function") lessonStop({ reload: false });
      if (liveTf === b.dataset.tf && liveLast.ok) return;
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
  // The poll never paints over a lesson; the lesson hands the chart back when it stops.
  liveChartTimer = setInterval(() => { if (!lessonView) loadLiveTradeChart(); }, TF_POLL_MS[liveTf] || 20000);
}

async function loadLiveTradeChart() {
  // A search or a drill means the user wants the live chart back. This load IS the
  // hand-back, so the lesson must not start a second one, and the poll resumes.
  if (lessonView && typeof lessonStop === "function") { lessonStop({ reload: false }); startChartPoll(); }
  const raw = $("#liveSymbol").value.trim();
  const kind = $("#liveKind").value;
  if (!raw) return false;
  const sym = kind === "crypto" ? raw.toLowerCase() : raw.toUpperCase();
  const ticket = ++liveLoadSeq;
  try {
    const res = await fetch(`/api/intraday?symbol=${encodeURIComponent(sym)}&kind=${kind}&tf=${liveTf}`
      + `&prepost=${chartInd.showPrePost ? 1 : 0}`);
    if (!res.ok) throw new Error(`server said ${res.status}`);
    const d = await res.json();
    if (lessonView || ticket !== liveLoadSeq) return false;   // a lesson started, or a newer load, while this was in flight
    // Fire-and-forget overlay refresh so the chart shows immediately; the
    // next full render (either this call's chain or the next poll) picks up
    // the daily EMAs + squeeze once they land.
    loadChartOverlay(kind, sym).then((ov) => {
      if (ov && !lessonView && ticket === liveLoadSeq) renderLiveTradeChart(d, kind);
    }).catch(() => {});
    renderLiveTradeChart(d, kind);
    return liveLast.ok;                     // true = this tape is what the chart now shows
  } catch (e) {
    // A blip must not wipe a tape that's already drawn — but staying silent
    // when there is NOTHING drawn is how this shows up as "the chart just
    // doesn't come up". The app shell is a PWA and loads from cache, so the
    // page looks perfectly healthy while /api/* (network-only, by design) is
    // unreachable. Say that out loud instead of showing an empty box.
    if (!liveLast.ok) _showChartUnreachable(sym);
    return false;
  }
}

/* Honest empty-state when we have no tape to draw and the fetch failed. */
function _showChartUnreachable(sym) {
  // Clear through the engine: wiping the container would destroy its canvas.
  if (typeof pcClear === "function") pcClear();
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
  const pp = chartInd.showPrePost ? 1 : 0;
  const key = `${kind}:${sym.toLowerCase()}:${liveTf}:${periods}:${chartInd.showSqueeze ? 1 : 0}:${pp}`;
  if (liveOverlayKey === key && Date.now() - liveOverlayAt < OVERLAY_TTL_MS) {
    return liveOverlay;
  }
  try {
    const url = `/api/chart-overlay?symbol=${encodeURIComponent(sym)}&kind=${kind}`
      + `&tf=${encodeURIComponent(liveTf)}&ema=${encodeURIComponent(periods)}`
      + `&squeeze=${chartInd.showSqueeze ? 1 : 0}&prepost=${pp}`;
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
  // Never the word "off" here. The indicator's own checkbox is also labelled
  // on/off, so a chip reading "TTM off" next to a ticked box looks like a
  // contradiction — one means "not drawing", the other means "not compressed".
  // Say what the STATE is instead: coiled, fired, or expanded.
  const txt = state === "on" ? `COILED·${Number(sq.bars) || 0}`
    : state === "fired" ? "FIRED" : "no coil";
  // Distance still to travel before the bands close inside the channel. The
  // state alone can only describe a squeeze that already exists — this is what
  // lets you see one coming instead of being told after the fact. Shown only
  // when it is genuinely close, or it is noise on every quiet chart.
  let near = "";
  if (state === "off" && sq.gap != null && sq.width) {
    const pct = (Number(sq.gap) / Number(sq.width)) * 100;
    if (isFinite(pct) && pct <= 40) {
      near = ` <span class="ltc-sqz-near">· ${Number(sq.gap).toFixed(2)} to coil</span>`;
    }
  }
  box.hidden = false;
  box.className = `ltc-sqz ${state} ${mom || ""}`;
  box.innerHTML = `<b>TTM</b> ${grain} ${txt} <span class="ltc-sqz-arr">${arrow}</span>${near}`;
  box.title = `TTM squeeze ${state} on ${grain} bars · momentum ${mom || "—"} ${sq.accel || ""}`
    + (sq.gap != null
       ? `\nbands are ${Number(sq.gap).toFixed(3)} from closing inside the Keltner channel`
         + ` (upper ${Number(sq.gap_upper).toFixed(3)}, lower ${Number(sq.gap_lower).toFixed(3)})`
         + `\nnegative = compressed`
       : "");
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

/* Draw the tape. Works out what is revealed and which overlays apply, then
 * hands one frame to the engine. Everything that is chart STATE (replay dial,
 * header price, footer) is settled here; everything that is PIXELS is not. */
function renderLiveTradeChart(d, kind) {
  const fullOhlc = (d && d.ohlc) || [];
  const fullTs = (d && d.ts) || [];
  const sym = d && d.symbol;
  _renderChartLabels(sym, kind);
  if (sym !== lastRenderSym || liveTf !== lastRenderTf) _onNewTape(sym, kind);

  // Re-seat the cursor against this tape before anything reads from/upto/end.
  _syncCursorRange(d);
  const nAll = Math.min(fullOhlc.length, fullTs.length);
  const revealed = replay.on ? Math.min(nAll, replay.upto + 1) : nAll;
  // Live needs two bars before a chart means anything. Replay legitimately
  // starts with ONE — the opening candle, alone on the left, is the point.
  liveLast = { data: d, kind, ok: revealed >= (replay.on ? 1 : 2) };
  // The dial is a live control, not a replay-mode artefact: its range has to
  // track the growing tape on EVERY render, or it sits at 0..0 and can't be
  // dragged at all. Runs after liveLast so the clock can read the cursor bar.
  _syncReplayUI();
  if (!liveLast.ok) {
    _renderEmptyChart(kind);
    _renderOptStrip("");
    if (typeof optChartEnsureMarking === "function") optChartEnsureMarking(false);
    return;
  }

  // Options paper positions on this symbol ride along: lines on the chart, stats
  // under the price. Priced against the LIVE last close even while rewound —
  // the position is open now, not at the cursor. A fault in the options layer
  // must never cost the trader the candles, so it degrades to "no overlay".
  let opt = { lines: [], html: "" };
  if (lessonView) {
    opt = { lines: lessonView.optLines || [], html: "" };   // the lesson's levels, no live positions
  } else if (typeof optChartFor === "function") {
    try { opt = optChartFor(sym, kind, fullOhlc[nAll - 1][3]); } catch (e) { /* candles first */ }
  }
  const drawn = typeof pcRender === "function" && pcRender({
    d, revealed, tf: liveTf,
    identity: `${kind}|${sym}|${liveTf}`,
    // The dial may run past the day it started in; the frame stretches to follow.
    replay: replay.on ? { from: replay.from, fromTs: fullTs[replay.from],
                          end: Math.max(_sessionEndIdx(fullTs, replay.from), replay.upto) } : null,
    overlay: lessonView ? null : liveOverlay,   // live EMAs belong to the live symbol, not a lesson tape
    showEma: !!chartInd.showEma,
    showSqueeze: !!chartInd.showSqueeze,
    showVolume: !!chartInd.showVolume,
    entry: lessonView ? null : _chartEntryFor(sym),
    optLines: opt.lines,
  });
  if (!drawn) {
    $("#ltcFoot").textContent = "The chart engine didn't load. Refresh the page; if it keeps "
      + "happening, the app files are out of date.";
    return;
  }
  _renderOptStrip(opt.html);
  _renderHeaderPrice(fullOhlc, fullTs, revealed, kind);
  _renderReplayStatus(fullTs);
}

/* Header labels and chips, plus settling any live calls the tape has reached. */
function _renderChartLabels(sym, kind) {
  $("#ltcSym").textContent = sym || "—";
  const grainMap = TF_GRAIN[kind === "crypto" ? "crypto" : "stock"];
  $("#ltcKind").textContent = (kind === "crypto" ? "Crypto · " : "Stock · ") + (grainMap[liveTf] || "");
  renderTfButtons(kind);
  // A lesson's tape has no live indicators: the live symbol's squeeze/EMA chips would
  // describe a different chart (e.g. "TTM 5m" over a daily lesson).
  _renderSqueezeChip(lessonView ? null : liveOverlay);
  _renderEmaLegend(lessonView ? null : liveOverlay);
  // Resolve any live forward calls the tape has now caught up with. Runs on
  // every refresh so a call made this morning settles itself without anyone
  // having to remember it — a record that depends on being remembered ends up
  // a record of the memorable trades only.
  if (!lessonView && typeof learnSettlePending === "function") {
    try { learnSettlePending(); } catch (e) { /* never let scoring break the chart */ }
  }
}

/* A new symbol or timeframe starts on the default window, not a stale one. */
function _onNewTape(sym, kind) {
  resetChartView();
  lastRenderSym = sym;
  lastRenderTf = liveTf;
  if (lessonView) return;                  // the lesson sets its own cursor on its own tape
  // A cursor is a position within ONE tape. Changing symbol or timeframe
  // makes it meaningless, so drop it rather than carry a stale index across.
  replay.on = false;
  replay.cursorTs = null;
  replay.fromTs = null;
  _replayStop();
  lastRenderSym = sym;
  lastRenderTf = liveTf;
  if (typeof onChartIdentity === "function") onChartIdentity(sym, kind, liveTf);
}

function _renderEmptyChart(kind) {
  if (typeof pcClear === "function") pcClear();
  $("#ltcLast").textContent = "—";
  $("#ltcChg").textContent = "";
  $("#ltcFoot").textContent = kind === "crypto"
    ? "No candles for this coin at this timeframe — try BTC, ETH, SOL…"
    : "No candles for this symbol at this timeframe — check the ticker.";
}

/* Options paper stats under the price. The markup comes from chart-options.js,
 * which escapes every string and coerces every number before it gets here. */
function _renderOptStrip(html) {
  const box = $("#ltcOpt");
  if (!box) return;
  // The strip is an aria-live region: rewriting identical markup every poll
  // would have a screen reader re-announce it every few seconds.
  if (box.dataset.html === (html || "")) return;
  box.dataset.html = html || "";
  box.innerHTML = html || "";
  box.hidden = !html;
}

/* A fresh mark landed (options-paper.js optBookTick): redraw the strip now
 * rather than waiting up to a 1D/1W poll interval for the next chart render. */
function refreshOptStrip() {
  if (!liveLast.ok || !liveLast.data || typeof optChartFor !== "function") return;
  const d = liveLast.data;
  const n = Math.min((d.ohlc || []).length, (d.ts || []).length);
  if (!n) return;
  try { _renderOptStrip(optChartFor(d.symbol, liveLast.kind, d.ohlc[n - 1][3]).html); } catch (e) { /* keep last strip */ }
}

/* The pinned Live Tracker entry, when it is for the symbol on screen. */
function _chartEntryFor(sym) {
  const p = getLive();
  return (p && p.sym && sym && p.sym.toUpperCase() === String(sym).toUpperCase()) ? p.entry : null;
}

/* The change a trader expects: against the previous session's close on
 * intraday charts, against the previous bar on daily and weekly ones. */
function _renderHeaderPrice(ohlc, ts, revealed, kind) {
  const lastIdx = revealed - 1;
  const last = ohlc[lastIdx][3];
  let ref;
  if (TIME_AXIS_TFS.has(liveTf)) {
    const s = _sessionStartIdxAt(ts, lastIdx);
    ref = s > 0 ? ohlc[s - 1][3] : ohlc[s][0];
  } else {
    ref = lastIdx > 0 ? ohlc[lastIdx - 1][3] : ohlc[0][0];
  }
  const chg = ref ? (last - ref) / ref * 100 : 0;
  $("#ltcLast").textContent = fmtPrice(last);
  const chgEl = $("#ltcChg");
  chgEl.textContent = (chg >= 0 ? "▲ " : "▼ ") + Math.abs(chg).toFixed(2) + "%";
  chgEl.className = "ltc-chg " + (chg >= 0 ? "up" : "down");
  chgEl.title = TIME_AXIS_TFS.has(liveTf)
    ? (kind === "crypto" ? "Change since midnight (your time)" : "Change vs. the previous session's close")
    : "Change vs. the previous bar";
}

/* A scrubbed-back price is NOT the market price. In a trading app that
 * confusion is the expensive kind, so say it in the header and the footer
 * rather than relying on the user noticing the dial isn't at the end. */
function _renderReplayStatus(ts) {
  const asOf = $("#ltcAsOf");
  const cursorTs = replay.on && ts[replay.upto];
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
    : `Live candles · refreshes ~${cadence}s · drag to pan, scroll to zoom, double-click to reset · M marks an entry, L draws a trend line · educational, not advice`;
}

// Intraday bars get a CLOCK; only daily and weekly get a date. This used to
// key off `tf === "1m"` (plus a "day" value that no longer exists), so a 5m
// chart covering one 6.5-hour session printed "Jul 30" at all six ticks —
// six identical labels that tell you nothing about where you are in the day.
// The date still gets said once per session change, by the session dividers in chart-draw.js.
const TIME_AXIS_TFS = PC_INTRADAY_TFS;    // chart-theme.js

function _fmtAxisTime(dt, tf) {
  if (TIME_AXIS_TFS.has(tf)) {
    return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return dt.toLocaleDateString([], { month: "short", day: "numeric" });
}
