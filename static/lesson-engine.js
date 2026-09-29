/* MarketPulse Classes — the lesson engine. Pure functions, no DOM.
 *
 * A compiled lesson (tools/classes/lesson_compiler.py) is a frozen tape plus
 * steps of chart ops. What the chart shows after step i is FOLDED from step 0
 * every time, never accumulated, so skip / back / replay-a-step are exact and
 * can't drift. lessonStateAt mirrors the compiler's state_at; a test runs both
 * on the same lesson and fails if they ever disagree.
 *
 * Ordering contract (same as the compiler): within a step, seeks and plays set
 * the cursor; drawings show at the step's final cursor, and a drawing on a bar
 * the cursor hasn't reached yet stays hidden until the play reveals it.
 *
 * Classic script sharing one global scope with the page; declarations only.
 */

const LESSON_MIN_TICK_MS = 40;       // the fastest the cursor ever steps: ~25 frames a second
const LESSON_PLAY_SHARE = 0.85;      // a play finishes while the voice is still finishing its line

/* Index of an exact timestamp in an ascending ts array, or -1. */
function lessonIndexOfTs(ts, t) {
  let lo = 0, hi = (ts || []).length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (ts[mid] === t) return mid;
    if (ts[mid] < t) lo = mid + 1; else hi = mid - 1;
  }
  return -1;
}

/* The chart after steps 0..i (i < 0 = before the first step: the last bar, nothing drawn). */
function lessonStateAt(lesson, i) {
  const ts = lesson.tape.ts;
  const st = { cursor_ts: ts[ts.length - 1], frame: null, marks: [], lines: [], levels: [] };
  for (const step of lesson.steps.slice(0, Math.max(i + 1, 0))) {
    for (const op of step.do) {
      if (op.op === "seek") st.cursor_ts = op.ts;
      else if (op.op === "play") st.cursor_ts = op.to_ts;
      else if (op.op === "frame") st.frame = { from_ts: op.from_ts, to_ts: op.to_ts };
      else if (op.op === "mark") st.marks.push({ ts: op.ts, price: op.price, dir: op.dir });
      else if (op.op === "line") st.lines.push({ a: op.a, b: op.b });
      else if (op.op === "level") st.levels.push({ price: op.price, title: op.title });
      else if (op.op === "clear") { st.marks = []; st.lines = []; st.levels = []; }
    }
  }
  return st;
}

/* Where step i's cursor starts and ends, and whether it walks (play) or jumps (seek). */
function lessonPlayPlan(lesson, i) {
  const ts = lesson.tape.ts;
  let from = lessonIndexOfTs(ts, lessonStateAt(lesson, i - 1).cursor_ts);
  let to = from, animate = false;
  for (const op of lesson.steps[i].do) {
    if (op.op === "seek") { from = to = lessonIndexOfTs(ts, op.ts); animate = false; }
    if (op.op === "play") { to = lessonIndexOfTs(ts, op.to_ts); animate = to > from; }
  }
  return { fromIdx: from, toIdx: to, animate };
}

/* How to walk the cursor from `fromIdx` to `toIdx` inside a line `durMs` long:
 * as few ticks as it takes to look smooth, never faster than the minimum tick,
 * and arriving before the voice finishes. */
function lessonTicks(fromIdx, toIdx, durMs) {
  const bars = Math.max(0, toIdx - fromIdx);
  if (!bars) return { ticks: 0, barsPerTick: 0, tickMs: LESSON_MIN_TICK_MS };
  const budget = Math.max((Number(durMs) || 0) * LESSON_PLAY_SHARE, LESSON_MIN_TICK_MS);
  const most = Math.max(1, Math.floor(budget / LESSON_MIN_TICK_MS));
  const barsPerTick = Math.ceil(bars / Math.min(bars, most));
  const ticks = Math.ceil(bars / barsPerTick);
  return { ticks, barsPerTick, tickMs: Math.max(LESSON_MIN_TICK_MS, Math.floor(budget / ticks)) };
}

/* A lesson's horizontal levels, in the price-line shape the chart engine draws. */
function lessonOptLines(st) {
  return st.levels.map((l) => ({ price: l.price, kind: "level", title: l.title }));
}
