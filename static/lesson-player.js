/* MarketPulse Classes — the lesson player.
 *
 * Plays a compiled lesson ON the live chart card: the chart shows the lesson's
 * frozen tape, the cursor walks while Tess or Quantus explains, the lesson's
 * marks, lines and gold levels appear, and a spotlight rings the real app
 * control being taught. While a lesson runs, `lessonView` (declared in
 * chart.js) makes the live poll, the user's drawings and scoring stand aside;
 * lessonStop() hands everything back.
 *
 * Loading takes a ticket (lessonLoadSeq). Exit, leaving the tab, or starting
 * another lesson cancels it: a load that finishes on a cancelled ticket throws
 * its results away instead of taking over a chart nobody is looking at.
 *
 * Audio: one <audio> element, first played from the ▶ tap (iOS only lets a
 * page start sound from a gesture; the same element can then keep playing).
 * Narration is fetched once per step as a blob with the license headers, so it
 * never touches a URL anyone else could open or the service-worker cache.
 */

const LESSON_GAP_MS = 450;                    // a breath between steps
const LESSON_NAMES = { T: "Tess", Q: "Quantus" };
// The only controls a lesson may spotlight (compiler: lesson_compiler.TOOLS).
const LESSON_TOOL_SELECTORS = new Map(Object.entries({
  search: "#ltcSymBtn", timeframes: "#ltcTf", indicators: "#ltcIndBtn", prepost: "#ltcIndBtn",
  mark: '.ltc-tool[data-tool="mark"]', trend: '.ltc-tool[data-tool="line"]', undo: "#ltcUndo",
  clear: "#ltcClear", fit: "#ltcFit", fullscreen: "#ltcFullBtn", replay: "#rpToggle", play: "#rpPlay",
  step: "#rpFwd", speed: "#rpSpeed", dial: "#rpScrub", live: "#rpLive", calls: "#rpCall",
  dca_tab: '.tab[data-view="dca"]',
}));
const LESSON_REPLAY_TOOLS = new Set(["replay", "play", "step", "speed", "dial", "live", "calls"]);

let lessonAudio = null;
let lessonTick = null;
let lessonNext = null;
let lessonLoadSeq = 0;           // the ticket of the load that is allowed to finish
let lessonLoadAbort = null;
let lessonVisWired = false;

const _lessonScroll = () =>
  (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

/* ---- fetching (with the Classes pass, falling back to the main license) -- */
function _lessonHeaderSets() {
  if (typeof mpLicenseHeaders !== "function") return [{}];
  const pass = mpLicenseHeaders("classes"), main = mpLicenseHeaders();
  // A lapsed Classes pass must not hide a valid Pro+ key: try the pass, then the main key.
  return pass["X-MP-License-Key"] && pass["X-MP-License-Key"] !== main["X-MP-License-Key"] ? [pass, main] : [pass];
}

async function _lessonGet(path, signal) {
  let status = 0;
  for (const headers of _lessonHeaderSets()) {
    const r = await fetch(path, { headers, signal });
    if (r.ok) return r;
    status = r.status;
    if (status !== 402) break;
  }
  if (status === 402) throw Object.assign(new Error("locked"), { locked: true });
  throw Object.assign(new Error(`server said ${status}`), { status });
}

function _lessonShapeOk(lesson) {
  const ts = lesson && lesson.tape && lesson.tape.ts;
  return Array.isArray(ts) && ts.length > 1 && Array.isArray(lesson.steps) && lesson.steps.length > 0
    && lesson.steps.every((s) => Array.isArray(s.do) && s.do.every((op) =>
      !("ts" in op || "to_ts" in op || "from_ts" in op)
      || lessonIndexOfTs(ts, op.ts != null ? op.ts : op.to_ts != null ? op.to_ts : op.from_ts) >= 0));
}

/* ---- rendering -------------------------------------------------------- */
function _lessonTimersOff() {
  if (lessonTick) { clearInterval(lessonTick); lessonTick = null; }
  if (lessonNext) { clearTimeout(lessonNext); lessonNext = null; }
}

/* Show the lesson tape with the cursor on bar `idx`. */
function _lessonRenderAt(idx) {
  const v = lessonView;
  if (!v) return;
  const d = v.lesson.tape;
  replay.on = true;
  replay.fromTs = v.frameFromTs;
  replay.cursorTs = d.ts[idx];
  replay.upto = idx;
  renderLiveTradeChart(d, d.kind);
}

function _lessonSpotOff() {
  document.querySelectorAll(".lesson-spot").forEach((el) => el.classList.remove("lesson-spot"));
  const tag = $("#lessonSpotTag");
  if (tag) tag.hidden = true;
}

/* After a spotlight scrolled down to a control, bring the chart back: its top must
 * clear the sticky top bar, or the start of the story hides under it on a phone. */
function _lessonChartIntoView() {
  const chart = $("#liveTradeChart");
  if (!chart) return;
  const bar = document.querySelector(".topbar");
  const clear = bar ? bar.getBoundingClientRect().bottom : 0;
  const top = chart.getBoundingClientRect().top;
  if (top < clear || top > innerHeight * 0.5) window.scrollBy({ top: top - clear - 8, behavior: _lessonScroll() });
}

/* Ring the real control a step is teaching, and say what it is. */
function _lessonSpot(step) {
  _lessonSpotOff();
  const spot = step.do.find((op) => op.op === "spot");
  const card = $("#liveTradeCard");
  // The replay bar is hidden during lessons; show it only while a step teaches one of its controls.
  if (card) card.classList.toggle("lesson-spot-replay", !!(spot && LESSON_REPLAY_TOOLS.has(spot.tool)));
  if (!spot) { _lessonChartIntoView(); return; }
  const sel = LESSON_TOOL_SELECTORS.get(spot.tool);
  const el = sel && document.querySelector(sel);
  if (!el || !el.getClientRects().length) return;         // hidden on this layout: don't ring thin air
  el.classList.add("lesson-spot");
  el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: _lessonScroll() });
  const tag = $("#lessonSpotTag");
  if (tag && spot.label) { tag.textContent = spot.label; tag.hidden = false; }
}

function _lessonControls(enabled) {
  ["#lessonPrev", "#lessonPlay", "#lessonNextBtn", "#lessonAgain"].forEach((id) => {
    const b = $(id);
    if (b) b.disabled = !enabled;
  });
}

function _lessonRenderBar(step) {
  const v = lessonView;
  const bar = $("#lessonBar");
  if (!v || !bar) return;
  bar.hidden = false;
  bar.removeAttribute("aria-busy");
  _lessonControls(true);
  $("#lessonTitle").textContent = v.lesson.title;
  $("#lessonProgress").textContent = `${v.i + 1} / ${v.lesson.steps.length}`;
  const who = $("#lessonWho");
  who.textContent = LESSON_NAMES[step.who] || "";
  who.dataset.who = step.who;
  $("#lessonSay").textContent = step.say;
  $("#lessonPlay").textContent = v.playing ? "❚❚" : "▶";
  $("#lessonPlay").setAttribute("aria-label", v.playing ? "Pause" : "Play");
  $("#lessonPrev").disabled = v.i <= 0;
  $("#lessonDone").hidden = !v.done;
}

/* ---- playing ---------------------------------------------------------- */
function _lessonWalk(plan, step) {
  const t = lessonTicks(plan.fromIdx, plan.toIdx, step.durMs);
  let at = plan.fromIdx;
  lessonTick = setInterval(() => {
    at = Math.min(plan.toIdx, at + t.barsPerTick);
    _lessonRenderAt(at);
    if (at >= plan.toIdx) { clearInterval(lessonTick); lessonTick = null; }
  }, t.tickMs);
}

/* Go to step i. With `play`, narrate it and walk the cursor; otherwise just show where it lands. */
function lessonGo(i, play) {
  const prev = lessonView;
  if (!prev) return;
  _lessonTimersOff();
  const at = Math.max(0, Math.min(prev.lesson.steps.length - 1, i));
  const step = prev.lesson.steps[at];
  const st = lessonStateAt(prev.lesson, at);
  const plan = lessonPlayPlan(prev.lesson, at);
  // A fresh view object per step: a stale audio callback can tell it isn't current.
  const cur = { ...prev, i: at, playing: !!play, done: false, marks: st.marks, lines: st.lines,
                optLines: lessonOptLines(st), frameFromTs: st.frame ? st.frame.from_ts : prev.lesson.tape.ts[0] };
  lessonView = cur;
  _lessonRenderAt(play && plan.animate ? plan.fromIdx : plan.toIdx);
  _lessonRenderBar(step);
  _lessonSpot(step);
  if (!play) { lessonAudio.pause(); return; }
  if (plan.animate) _lessonWalk(plan, step);
  const url = cur.urls[at];
  lessonAudio.src = url;
  lessonAudio.play().catch((err) => {
    // Skipping ahead cancels the step you left (AbortError). Only a failure on the step
    // still on screen may touch the bar, or a stale step repaints over the new one.
    if ((err && err.name === "AbortError") || lessonView !== cur || lessonAudio.src !== url) return;
    _lessonHalt();
  });
}

/* The voice stopped on its own (decode error, blocked play): stop pretending it's playing. */
function _lessonHalt() {
  const v = lessonView;
  if (!v) return;
  _lessonTimersOff();
  lessonView = { ...v, playing: false };
  _lessonRenderAt(lessonPlayPlan(v.lesson, v.i).toIdx);
  _lessonRenderBar(v.lesson.steps[v.i]);
}

function _lessonStepEnded() {
  const v = lessonView;
  if (!v || !v.playing) return;
  if (v.i >= v.lesson.steps.length - 1) {
    lessonView = { ...v, playing: false, done: true };
    _lessonRenderBar(v.lesson.steps[v.i]);
    const go = $("#lessonPracticeBtn");
    if (go) go.focus();
    return;
  }
  lessonNext = setTimeout(() => lessonGo(v.i + 1, true), LESSON_GAP_MS);
}

function lessonTogglePlay() {
  const v = lessonView;
  if (!v) return;
  if (v.playing) lessonGo(v.i, false);                  // pause = the step's finished picture, silent
  else lessonGo(v.done ? 0 : v.i, true);                // play restarts the step: exact, not approximate
}

/* ---- start / stop ------------------------------------------------------- */
function _lessonShowLoading() {
  const bar = $("#lessonBar");
  if (!bar) return;
  bar.hidden = false;
  bar.setAttribute("aria-busy", "true");
  $("#lessonTitle").textContent = "";
  $("#lessonProgress").textContent = "";
  $("#lessonWho").textContent = "";
  $("#lessonSay").textContent = "Loading the lesson…";
  $("#lessonDone").hidden = true;
  _lessonControls(false);
}

async function _lessonFetchAll(id, signal, made) {
  const lesson = await (await _lessonGet(`/api/classes/lesson?id=${encodeURIComponent(id)}`, signal)).json();
  if (!_lessonShapeOk(lesson)) throw new Error("malformed lesson");
  const blobs = await Promise.all(lesson.steps.map(async (_, i) =>
    (await _lessonGet(`/api/classes/audio?id=${encodeURIComponent(id)}&step=${i}`, signal)).blob()));
  blobs.forEach((b) => made.push(URL.createObjectURL(b)));   // URLs only once every step arrived
  return lesson;
}

async function lessonStart(id) {
  lessonStop();
  const ticket = ++lessonLoadSeq;
  const ctl = typeof AbortController === "function" ? new AbortController() : null;
  lessonLoadAbort = ctl;
  _lessonShowLoading();
  const made = [];
  let lesson;
  try {
    lesson = await _lessonFetchAll(id, ctl && ctl.signal, made);
  } catch (e) {
    made.forEach((u) => URL.revokeObjectURL(u));
    if (ticket !== lessonLoadSeq) return;                 // cancelled: whoever cancelled owns the bar now
    const bar = $("#lessonBar");
    if (bar) bar.hidden = true;
    if (e.locked && typeof classesShowLocked === "function") return classesShowLocked(id);
    if (typeof toast === "function") {
      toast("", "Couldn't load that lesson", e.status === 429
        ? "You've opened a lot of lessons in the last hour. Try again in a few minutes."
        : "Check your connection and try again.");
    }
    return;
  }
  if (ticket !== lessonLoadSeq || state.view !== "live") {   // exited, left, or another lesson won
    made.forEach((u) => URL.revokeObjectURL(u));
    return;
  }
  lessonLoadAbort = null;
  _lessonBegin(id, lesson, made);
}

function _lessonBegin(id, lesson, urls) {
  if (!lessonAudio) {
    lessonAudio = new Audio();                          // created now; first PLAYED from the ▶ tap (iOS)
    lessonAudio.addEventListener("ended", _lessonStepEnded);
    lessonAudio.addEventListener("error", () => { if (lessonView && lessonView.playing) _lessonHalt(); });
  }
  if (typeof _setTool === "function") _setTool("none");
  if (typeof _replayStop === "function") _replayStop();   // a live replay mustn't tick under a lesson
  stopChartPoll();
  lessonView = { id, lesson, urls, i: 0, playing: false, done: false, marks: [], lines: [], optLines: [],
                 frameFromTs: lesson.tape.ts[0], prevTf: liveTf };
  liveTf = lesson.tape.tf;
  if (typeof pcLessonSpacing === "function") pcLessonSpacing(true);   // the whole year fits a phone
  resetChartView();                                    // frame the lesson fresh, never a stale view
  const card = $("#liveTradeCard");
  if (card) { card.classList.add("in-lesson"); card.scrollIntoView({ block: "start", behavior: _lessonScroll() }); }
  lessonGo(0, false);                                   // ready on step 1; the ▶ tap starts the voice
  const play = $("#lessonPlay");
  if (play) play.focus({ preventScroll: true });
}

/* End the lesson (or cancel one still loading) and hand the chart back.
 * `reload: false` when the caller loads the next chart itself, so two loads never race. */
function lessonStop(opts) {
  lessonLoadSeq++;                                      // any load in flight is now stale
  if (lessonLoadAbort) { lessonLoadAbort.abort(); lessonLoadAbort = null; }
  const bar = $("#lessonBar");
  if (bar) { bar.hidden = true; bar.removeAttribute("aria-busy"); }
  const v = lessonView;
  if (!v) return;
  _lessonTimersOff();
  _lessonSpotOff();
  if (lessonAudio) { lessonAudio.pause(); lessonAudio.removeAttribute("src"); lessonAudio.load(); }
  v.urls.forEach((u) => URL.revokeObjectURL(u));
  lessonView = null;
  if (typeof _replayStop === "function") _replayStop();
  if (typeof pcLessonSpacing === "function") pcLessonSpacing(false);
  liveTf = v.prevTf;
  replay.on = false;
  replay.cursorTs = null;
  replay.fromTs = null;
  // Nobody reads the lesson tape as if it were the live symbol, and the next live
  // render starts fresh (identity, view, cursor) even on the same symbol and tf.
  liveLast = { data: null, kind: liveLast.kind, ok: false };
  lastRenderSym = null;
  const card = $("#liveTradeCard");
  if (card) card.classList.remove("in-lesson", "lesson-spot-replay");
  if (typeof _drawChanged === "function") _drawChanged();   // the user's own drawings come back
  if ((!opts || opts.reload !== false) && $("#livePanel") && !$("#livePanel").hidden) {
    resetChartView();
    loadLiveTradeChart();
    startChartPoll();
  }
}

/* Lesson over: the same market, live, rewound — the student's turn. */
async function lessonPractice() {
  const v = lessonView;
  const p = (v && v.lesson.practice) || {};
  lessonStop({ reload: false });
  if (p.symbol) { $("#liveSymbol").value = p.symbol; $("#liveKind").value = p.kind || "stock"; }
  if (p.tf) liveTf = p.tf;
  const painted = await loadLiveTradeChart();
  startChartPoll();
  if (!painted || state.view !== "live") return;       // offline or moved on: no replay of stale data
  enterReplay();
  const sym = $("#liveSymbol");
  if (sym) sym.focus({ preventScroll: true });
  if (typeof toast === "function") {
    toast("buy", "Your turn", "Step forward with ▶| and make a call before the next candle prints.");
  }
}

function initLessonPlayer() {
  const on = (id, fn) => {
    const b = $(id);
    if (b && !b.dataset.wired) { b.dataset.wired = "1"; b.addEventListener("click", fn); }
  };
  on("#lessonPlay", lessonTogglePlay);
  on("#lessonPrev", () => lessonView && lessonGo(lessonView.i - 1, lessonView.playing));
  on("#lessonNextBtn", () => lessonView && lessonGo(lessonView.i + 1, lessonView.playing));
  on("#lessonAgain", () => lessonView && lessonGo(lessonView.i, true));
  on("#lessonExit", () => lessonStop());
  on("#lessonPracticeBtn", lessonPractice);
  if (!lessonVisWired) {
    lessonVisWired = true;
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && lessonView && lessonView.playing) lessonGo(lessonView.i, false);
    });
  }
}
