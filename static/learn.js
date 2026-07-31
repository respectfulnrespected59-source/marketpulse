/* MarketPulse — Learning Mode, phase 1: the Call.
 *
 * Replay already guarantees the one thing that makes practice honest: at bar i
 * you can only see bars 0..i. What it never did was keep a RECORD. You walked
 * the day, felt clever or stupid, and the evidence evaporated.
 *
 * A Call fixes that. Before stepping forward you commit a direction and a
 * confidence; the next N bars settle it; the result is filed against the SETUP
 * you were looking at, not just the ticker. Enough of those and the app can
 * tell you something no chart can: which reads you are actually good at.
 *
 * Everything here is local. No account, no server, no telemetry — the whole
 * phase runs out of one localStorage key, which is also why it ships intact in
 * the downloadable zip.
 *
 * Tags are computed HERE rather than fetched, because /api/chart-overlay only
 * reports the squeeze as it stands *now* and a Call needs the setup as it stood
 * at an arbitrary bar in the past. The tape is already on the client, so the
 * honest version is to measure it locally.
 */

const LEARN_KEY = "mp_learn";
const LEARN_VERSION = 1;
const LEARN_MAX_CALLS = 2000;      // keeps localStorage bounded; oldest drop first
const DEFAULT_HORIZON = 10;        // bars forward a Call is judged over

/* Round-trip friction, in basis points per side — mirrored from backtest.py
 * (COMMISSION_BPS / SLIPPAGE_BPS) so a "win" here means what a win means in
 * Proof Mode. Drifting from those numbers would quietly make the coach more
 * flattering than the backtester, which is the one direction this must never
 * move. */
const LEARN_COST_BPS = {
  stock: { commission: 0.0, slippage: 5.0 },
  crypto: { commission: 25.0, slippage: 20.0 },
};

/* A directional call only counts as right if the move CLEARS the round trip.
 * Anything inside that band was not a trade worth taking — which is exactly
 * when "stand aside" is the correct answer, and why stand is scoreable. */
function learnFrictionPct(kind) {
  const c = LEARN_COST_BPS[kind === "crypto" ? "crypto" : "stock"];
  return (c.commission + c.slippage) * 2 / 100;   // bps per side -> round-trip %
}

/* ---- storage ---------------------------------------------------------- */

function learnNewId() {
  try {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  } catch (e) { /* fall through */ }
  return "id-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function learnBlank() {
  return { v: LEARN_VERSION, installId: learnNewId(), calls: [] };
}

function getLearn() {
  try {
    const raw = JSON.parse(localStorage.getItem(LEARN_KEY) || "null");
    if (!raw || typeof raw !== "object" || !Array.isArray(raw.calls)) return learnBlank();
    if (!raw.installId) raw.installId = learnNewId();
    raw.v = LEARN_VERSION;
    return raw;
  } catch (e) {
    // A corrupt record must never cost someone their chart — same rule the
    // indicator settings follow.
    return learnBlank();
  }
}

function saveLearn(state) {
  try {
    if (state.calls.length > LEARN_MAX_CALLS) {
      state.calls = state.calls.slice(-LEARN_MAX_CALLS);
    }
    localStorage.setItem(LEARN_KEY, JSON.stringify(state));
  } catch (e) { /* private mode / quota — recording is best-effort, never fatal */ }
}

function learnReset() {
  const keep = getLearn().installId;
  const blank = learnBlank();
  blank.installId = keep;          // the id is not the data; clearing stats keeps it
  saveLearn(blank);
  return blank;
}

/* ---- indicators, measured at a specific bar --------------------------- */
/* All of these take the FULL series and an index, and may only read [0..idx].
 * That constraint is the whole point: a tag computed with a peek at later bars
 * would quietly launder hindsight into the score. */

function _emaAt(closes, period, idx) {
  if (idx < period - 1) return null;
  const k = 2 / (period + 1);
  let ema = 0;
  for (let i = 0; i <= idx; i++) {
    ema = i === 0 ? closes[0] : closes[i] * k + ema * (1 - k);
  }
  return ema;
}

function _rsiAt(closes, period, idx) {
  if (idx < period) return null;
  let gain = 0, loss = 0;
  for (let i = idx - period + 1; i <= idx; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  if (loss === 0) return gain === 0 ? 50 : 100;
  const rs = (gain / period) / (loss / period);
  return 100 - 100 / (1 + rs);
}

/* Session VWAP up to `idx`, restarted at the session's first bar so it means
 * the same thing the live chart's VWAP means. */
function _vwapAt(ohlc, vol, from, idx) {
  let pv = 0, v = 0;
  for (let i = from; i <= idx; i++) {
    const bar = ohlc[i];
    if (!bar) continue;
    const typical = (bar[1] + bar[2] + bar[3]) / 3;
    const q = (vol && vol[i]) || 0;
    pv += typical * q;
    v += q;
  }
  return v > 0 ? pv / v : null;
}

function _stdev(xs) {
  if (xs.length < 2) return 0;
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) * (b - m), 0) / xs.length);
}

/* TTM squeeze at a bar: a Bollinger band sitting INSIDE the Keltner channel
 * means volatility has coiled. Same construction indicators.ttm_squeeze uses
 * server-side (BB 20/2 vs KC 20/1.5xATR); reimplemented here only because the
 * server reports the squeeze as of NOW and a Call needs it as of THEN. */
function _squeezeAt(ohlc, idx, len = 20, bbMult = 2, kcMult = 1.5) {
  if (idx < len) return null;
  const closes = [];
  for (let i = idx - len + 1; i <= idx; i++) closes.push(ohlc[i][3]);
  const mean = closes.reduce((a, b) => a + b, 0) / len;
  const sd = _stdev(closes);
  let trSum = 0;
  for (let i = idx - len + 1; i <= idx; i++) {
    const h = ohlc[i][1], l = ohlc[i][2];
    const pc = ohlc[i - 1] ? ohlc[i - 1][3] : ohlc[i][3];
    trSum += Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc));
  }
  const atr = trSum / len;
  return (mean + bbMult * sd) < (mean + kcMult * atr)
      && (mean - bbMult * sd) > (mean - kcMult * atr);   // true = coiled
}

/* The setup as a small set of tags. Deliberately coarse: "coiled + bull stack"
 * is something a person can recognise and get better at. A continuous vector
 * would be more precise and completely unactionable. */
function learnTagsAt(data, idx, sessionFrom) {
  const ohlc = (data && data.ohlc) || [];
  const vol = (data && data.volume) || [];
  if (!ohlc[idx]) return [];
  const closes = ohlc.map((b) => b[3]);
  const tags = [];

  const periods = (typeof chartInd === "object" && Array.isArray(chartInd.ema) && chartInd.ema.length >= 3)
    ? [...chartInd.ema].slice(0, 3).sort((a, b) => a - b)
    : [14, 21, 57];
  const [fast, mid, slow] = periods.map((p) => _emaAt(closes, p, idx));
  if (fast != null && mid != null && slow != null) {
    if (fast > mid && mid > slow) tags.push("stack_bull");
    else if (fast < mid && mid < slow) tags.push("stack_bear");
    else tags.push("stack_mixed");
  }

  const rsi = _rsiAt(closes, 14, idx);
  if (rsi != null) tags.push(rsi >= 70 ? "rsi_hot" : rsi <= 30 ? "rsi_cold" : "rsi_mid");

  const vwap = _vwapAt(ohlc, vol, Math.max(0, sessionFrom || 0), idx);
  if (vwap != null) tags.push(ohlc[idx][3] >= vwap ? "above_vwap" : "below_vwap");

  const coiled = _squeezeAt(ohlc, idx);
  if (coiled != null) tags.push(coiled ? "squeeze_on" : "squeeze_off");

  return tags;
}

/* ---- scoring ---------------------------------------------------------- */

/* Settle a Call over `horizon` bars.
 *
 * Judged on the CLOSE at the horizon, not the best price in between: rewarding
 * the peak would be teaching a skill nobody has, which is selling the top. */
function learnSettle(data, idx, dir, horizon, kind) {
  const ohlc = (data && data.ohlc) || [];
  const target = idx + horizon;
  if (!ohlc[idx] || !ohlc[target]) return null;         // not enough tape yet
  const entry = ohlc[idx][3];
  const exit = ohlc[target][3];
  if (!entry) return null;
  const movePct = (exit - entry) / entry * 100;
  const friction = learnFrictionPct(kind);

  let outcome;
  if (dir === "stand") {
    // Standing aside is right when there was nothing to take, in EITHER
    // direction, after costs.
    outcome = Math.abs(movePct) <= friction ? "win" : "loss";
  } else {
    const signed = dir === "up" ? movePct : -movePct;
    outcome = signed > friction ? "win" : (signed < -friction ? "loss" : "flat");
  }
  return { entry, exit, movePct, frictionPct: friction, outcome };
}

/* ---- recording -------------------------------------------------------- */

/* Record a Call at the dial's current bar. Returns the settled record, or an
 * {error} the UI can show — never throws into the chart. */
function learnRecordCall(dir, conf) {
  if (!["up", "down", "stand"].includes(dir)) return { error: "bad direction" };
  const d = liveLast && liveLast.data;
  if (!d || !d.ohlc || !d.ohlc.length) return { error: "no chart loaded" };
  if (!replay.on) {
    return { error: "Rewind the dial first — a call only counts when the rest of the day is hidden." };
  }
  const idx = replay.upto;
  const horizon = DEFAULT_HORIZON;
  const kind = (liveLast.kind === "crypto") ? "crypto" : "stock";
  const settled = learnSettle(d, idx, dir, horizon, kind);
  if (!settled) {
    return { error: `Not enough tape past this bar yet — a call needs ${horizon} more candles to settle.` };
  }

  const state = getLearn();
  const rec = {
    id: learnNewId(),
    sym: (d.symbol || "").toUpperCase(),
    kind,
    tf: typeof liveTf === "string" ? liveTf : "",
    barTs: (d.ts && d.ts[idx]) || 0,        // unix epoch SECONDS, matching the tape
    dir,
    conf: Math.max(1, Math.min(3, Number(conf) || 2)),
    horizon,
    tags: learnTagsAt(d, idx, replay.from),
    entry: settled.entry,
    exit: settled.exit,
    movePct: settled.movePct,
    frictionPct: settled.frictionPct,
    outcome: settled.outcome,
    // Replay speed is recorded because reading fast is a different (and worse)
    // skill than reading carefully, and the coach should be able to see that.
    speedMs: (typeof replay === "object" && replay.speedMs) || 0,
    at: Math.floor(Date.now() / 1000),
  };
  state.calls.push(rec);
  saveLearn(state);
  return rec;
}

/* ---- stats: the honest mirror ----------------------------------------- */

/* Sample floors. Below these we say "not enough yet" instead of printing a
 * number, because a 100% hit rate over three calls is noise wearing a crown —
 * and this panel's only job is to be trusted. */
const MIN_TAG_CALLS = 8;
const MIN_CONF_CALLS = 5;
const MIN_FLAG_CALLS = 10;

function _rate(wins, losses) {
  const n = wins + losses;
  return n ? wins / n : null;
}

/* A directional call that settled FLAT means the move never cleared costs —
 * there was no trade at that bar. Those are excluded from the hit rate (they
 * decided nothing) and counted separately, because their rate IS the
 * overtrading signal. */
function _bucket(calls) {
  let wins = 0, losses = 0, flats = 0;
  for (const c of calls) {
    if (c.outcome === "win") wins++;
    else if (c.outcome === "loss") losses++;
    else flats++;
  }
  return { n: calls.length, wins, losses, flats, hitRate: _rate(wins, losses) };
}

function learnTagStats(calls) {
  const byTag = new Map();
  for (const c of calls) {
    for (const t of c.tags || []) {
      if (!byTag.has(t)) byTag.set(t, []);
      byTag.get(t).push(c);
    }
  }
  return [...byTag.entries()]
    .map(([tag, cs]) => ({ tag, ...(_bucket(cs)), enough: cs.length >= MIN_TAG_CALLS }))
    .sort((a, b) => b.n - a.n);
}

/* Confidence vs reality. The most useful number in the app and the least
 * flattering: if the high-confidence bucket underperforms the low one,
 * conviction is pointing the wrong way. */
function learnCalibration(calls) {
  const out = [];
  for (const conf of [1, 2, 3]) {
    const cs = calls.filter((c) => c.conf === conf);
    out.push({ conf, ...(_bucket(cs)), enough: cs.length >= MIN_CONF_CALLS });
  }
  return out;
}

function learnFlags(calls) {
  const flags = [];
  const directional = calls.filter((c) => c.dir !== "stand");

  // 1. Overtrading — calling a direction on bars where nothing was there.
  if (directional.length >= MIN_FLAG_CALLS) {
    const flatRate = directional.filter((c) => c.outcome === "flat").length / directional.length;
    if (flatRate >= 0.35) {
      flags.push({
        id: "overtrading",
        label: "Trading bars that weren't paying",
        detail: `${Math.round(flatRate * 100)}% of your directional calls settled inside costs — `
              + `those were STAND bars. Taking them is how a flat day becomes a losing one.`,
      });
    }
  }

  // 2. Revenge sizing — conviction climbing right after a loss. Measured
  //    against your OWN baseline, so a naturally bold caller isn't flagged for
  //    being bold, only for being bold *because* of a loss.
  const pairs = [];
  for (let i = 1; i < calls.length; i++) {
    pairs.push({ afterLoss: calls[i - 1].outcome === "loss", up: calls[i].conf > calls[i - 1].conf });
  }
  const afterLoss = pairs.filter((p) => p.afterLoss);
  const afterOther = pairs.filter((p) => !p.afterLoss);
  if (afterLoss.length >= MIN_FLAG_CALLS && afterOther.length >= MIN_FLAG_CALLS) {
    const a = afterLoss.filter((p) => p.up).length / afterLoss.length;
    const b = afterOther.filter((p) => p.up).length / afterOther.length;
    if (a - b >= 0.2) {
      flags.push({
        id: "revenge",
        label: "Conviction spikes after a loss",
        detail: `You raise confidence on ${Math.round(a * 100)}% of calls right after a loss, `
              + `versus ${Math.round(b * 100)}% otherwise. The market has no memory of your last call.`,
      });
    }
  }

  // 3. Reading too fast — pattern-matching the shape instead of reading the bar.
  const fast = calls.filter((c) => c.speedMs && c.speedMs <= 200);
  const slow = calls.filter((c) => c.speedMs && c.speedMs >= 400);
  const fastRate = _bucket(fast).hitRate, slowRate = _bucket(slow).hitRate;
  if (fast.length >= MIN_TAG_CALLS && slow.length >= MIN_TAG_CALLS
      && fastRate != null && slowRate != null && slowRate - fastRate >= 0.15) {
    flags.push({
      id: "speed",
      label: "You read worse at speed",
      detail: `${Math.round(fastRate * 100)}% at 2x and faster, versus ${Math.round(slowRate * 100)}% `
            + `at 1x or slower. Slow down and the edge comes back.`,
    });
  }

  return flags;
}

/* The whole picture, from the stored record. Pure — hand it a state object and
 * it computes; no DOM, no storage, so it can be tested directly. */
function learnStats(state) {
  const calls = ((state || getLearn()).calls) || [];
  const directional = calls.filter((c) => c.dir !== "stand");
  const stand = calls.filter((c) => c.dir === "stand");
  const overall = _bucket(directional);
  const standB = _bucket(stand);
  const calibration = learnCalibration(calls);
  const tags = learnTagStats(calls);

  const hi = calibration.find((c) => c.conf === 3);
  const lo = calibration.find((c) => c.conf === 1);
  const inverted = (hi && lo && hi.enough && lo.enough && hi.hitRate != null && lo.hitRate != null)
    ? hi.hitRate < lo.hitRate
    : null;

  const ranked = tags.filter((t) => t.enough && t.hitRate != null)
                     .sort((a, b) => a.hitRate - b.hitRate);
  // Split the ranking rather than taking two off each end: with only two or
  // three qualifying tags those slices overlap, and the panel would name the
  // same setup as both your best and your worst read. With a single tag there
  // is nothing to compare it against, so neither list gets one.
  const half = Math.min(2, Math.floor(ranked.length / 2));

  return {
    total: calls.length,
    directional: overall,
    stand: standB,
    calibration,
    inverted,
    tags,
    weakest: ranked.slice(0, half),
    strongest: half ? ranked.slice(-half).reverse() : [],
    flags: learnFlags(calls),
    // Surfaced in the UI, never buried. The first is a real limit of the
    // current chart: the price ladder is scaled to the whole session, so the
    // day's range is on screen before you walk into it.
    caveats: [
      "The price ladder spans the whole session, so the day's high and low are visible before you get there. Practice, not a clean test.",
      "You are scoring your own calls on days you chose. That is not a random sample.",
    ],
  };
}

/* ---- UI --------------------------------------------------------------- */

/* Plain-language verdict. Deliberately blunt about costs, because "I was right
 * about the direction and still lost money" is the lesson most people never
 * get told. */
function learnResultText(rec) {
  const move = `${rec.movePct >= 0 ? "+" : ""}${rec.movePct.toFixed(2)}%`;
  const over = `${rec.horizon} bars`;
  if (rec.dir === "stand") {
    return rec.outcome === "win"
      ? `Right to stand aside — it moved ${move} over ${over}, inside costs.`
      : `Missed one — it moved ${move} over ${over}, past costs.`;
  }
  if (rec.outcome === "win") return `Called it — ${move} over ${over}, clear of costs.`;
  if (rec.outcome === "flat") {
    return `Direction aside, ${move} over ${over} did not clear the ${rec.frictionPct.toFixed(2)}% round trip. No trade there.`;
  }
  return `Wrong way — ${move} over ${over}.`;
}

/* The call row only makes sense while the dial is parked behind the edge, so it
 * follows that state rather than sitting there inviting a meaningless click. */
function learnSyncUI() {
  const row = document.querySelector("#rpCall");
  if (!row) return;
  const engaged = typeof replay === "object" && replay.on;
  row.hidden = !engaged;
}

function learnWireUI() {
  const row = document.querySelector("#rpCall");
  if (!row || row.dataset.wired === "1") return;
  row.dataset.wired = "1";
  const out = document.querySelector("#rpCallResult");

  row.querySelectorAll("[data-call]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const conf = document.querySelector("#rpConf");
      const rec = learnRecordCall(btn.dataset.call, conf ? conf.value : 2);
      if (!out) return;
      if (rec.error) {
        out.textContent = rec.error;
        out.className = "rp-call-result is-warn";
        return;
      }
      out.textContent = learnResultText(rec);
      out.className = "rp-call-result is-" + rec.outcome;
    });
  });
}

/* ---- drills ----------------------------------------------------------- */

/* A FIXED roster, declared up front and never reordered by results.
 *
 * The temptation is to drill you on "interesting" days — the big reversals, the
 * clean breakouts. That is survivorship bias with a coaching hat on: you would
 * get very good at reading days that were obviously readable. Drills come from
 * a fixed list of liquid names, and candidate bars are chosen on SETUP alone.
 * What happened next is never part of the selection. */
const DRILL_UNIVERSE = ["NVDA", "TSLA", "MU", "WDC", "MRVL", "SNDK"];
const DRILL_RECENT_MAX = 40;      // remembered so drills don't repeat themselves

/* Every bar in this tape whose setup carries `tag` and still has enough room
 * ahead of it to settle a call. Outcome is deliberately NOT consulted. */
function learnFindDrillBars(data, tag, horizon) {
  const ts = (data && data.ts) || [];
  const ohlc = (data && data.ohlc) || [];
  const out = [];
  const last = Math.min(ts.length, ohlc.length) - 1;
  for (let i = 0; i <= last - horizon; i++) {
    // Tag the bar against its own session, so VWAP means what it means on screen.
    const from = (typeof _sessionStartIdxAt === "function") ? _sessionStartIdxAt(ts, i) : 0;
    // Carry the session-open TIMESTAMP, not just its index: by the time a drill
    // is applied the tape may have grown a bar and every index shifts.
    if (learnTagsAt(data, i, from).includes(tag)) {
      out.push({ idx: i, ts: ts[i], from, fromTs: ts[from] });
    }
  }
  return out;
}

function _recentDrills(state) {
  return Array.isArray(state.recentDrills) ? state.recentDrills : [];
}

function _rememberDrill(key) {
  const state = getLearn();
  const recent = _recentDrills(state).filter((k) => k !== key);
  recent.push(key);
  state.recentDrills = recent.slice(-DRILL_RECENT_MAX);
  saveLearn(state);
}

/* Which setup to drill. The weakest READ if there is enough evidence to name
 * one; otherwise the tag you have the least experience with, because early on
 * the useful thing is coverage, not correction. */
function learnDrillTarget(stats) {
  const s = stats || learnStats();
  if (s.weakest.length) return { tag: s.weakest[0].tag, reason: "weakest" };
  const seen = new Set(s.tags.map((t) => t.tag));
  const unseen = Object.keys(TAG_LABELS).find((t) => !seen.has(t));
  if (unseen) return { tag: unseen, reason: "unseen" };
  const thin = [...s.tags].sort((a, b) => a.n - b.n)[0];
  return thin ? { tag: thin.tag, reason: "thin" } : null;
}

async function _fetchTape(sym, kind, tf) {
  const res = await fetch(`/api/intraday?symbol=${encodeURIComponent(sym)}&kind=${kind}&tf=${tf}`);
  if (!res.ok) throw new Error(`server said ${res.status}`);
  return res.json();
}

/* Find a bar matching `tag`, load it, and park the dial on it with the rest of
 * the day hidden. Searches the tape already on screen first — instant, offline,
 * no request — then walks the fixed roster. */
async function learnRunDrill(onStatus) {
  const say = (m) => { if (typeof onStatus === "function") onStatus(m); };
  const target = learnDrillTarget();
  if (!target) { say("Make a few calls first — a drill needs something to aim at."); return null; }
  const label = tagLabel(target.tag);
  const tf = (typeof liveTf === "string" && liveTf) || "5m";
  const horizon = DEFAULT_HORIZON;
  const recent = new Set(_recentDrills(getLearn()));

  const current = liveLast && liveLast.data;
  const currentSym = (current && current.symbol) || "";
  const order = [
    ...(current ? [{ sym: currentSym, kind: liveLast.kind, data: current }] : []),
    ...DRILL_UNIVERSE.filter((s) => s.toUpperCase() !== currentSym.toUpperCase())
                     .map((s) => ({ sym: s, kind: "stock", data: null })),
  ];

  for (const cand of order) {
    let data = cand.data;
    if (!data) {
      say(`Looking for ${label} on ${cand.sym}…`);
      try { data = await _fetchTape(cand.sym, cand.kind, tf); }
      catch (e) { continue; }          // a name that won't load is not a failure
    }
    const bars = learnFindDrillBars(data, target.tag, horizon);
    const fresh = bars.filter((b) => !recent.has(`${cand.sym}|${b.ts}`));
    const pool = fresh.length ? fresh : bars;
    if (!pool.length) continue;

    // Rotate by how many drills you've done rather than picking at random, so
    // repeated drills walk across the session instead of clustering.
    const pick = pool[_recentDrills(getLearn()).length % pool.length];

    if (cand.sym.toUpperCase() !== currentSym.toUpperCase()) {
      const symInput = document.querySelector("#liveSymbol");
      const kindInput = document.querySelector("#liveKind");
      if (symInput) symInput.value = cand.sym;
      if (kindInput) kindInput.value = cand.kind;
      if (typeof loadLiveTradeChart === "function") await loadLiveTradeChart();
    }

    // Park the dial: reveal from that day's open up to the chosen bar, hide the
    // rest. fromTs pins the window to the drilled day, not today's.
    replay.on = true;
    replay.fromTs = pick.fromTs || pick.ts;
    replay.cursorTs = pick.ts;
    // Re-locate the bar in whatever tape is now on screen; _syncCursorRange
    // will do the same on every later render.
    const liveTs = (liveLast.data && liveLast.data.ts) || [];
    const here = (typeof _indexOfTs === "function") ? _indexOfTs(liveTs, pick.ts) : -1;
    replay.upto = here >= 0 ? here : pick.idx;
    if (typeof renderLiveTradeChart === "function" && liveLast.data) {
      renderLiveTradeChart(liveLast.data, liveLast.kind);
    }
    _rememberDrill(`${cand.sym}|${pick.ts}`);
    return { sym: cand.sym, tag: target.tag, label, reason: target.reason, barTs: pick.ts };
  }
  say(`No ${label} setup in the loaded tape right now — try a different timeframe.`);
  return null;
}

/* ---- Coach panel ------------------------------------------------------ */

const TAG_LABELS = {
  stack_bull: "trend stacked up", stack_bear: "trend stacked down",
  stack_mixed: "trend tangled", rsi_hot: "RSI running hot",
  rsi_cold: "RSI washed out", rsi_mid: "RSI mid-range",
  above_vwap: "above VWAP", below_vwap: "below VWAP",
  squeeze_on: "coiled (squeeze on)", squeeze_off: "not coiled",
};
const tagLabel = (t) => TAG_LABELS[t] || t;
/* Prefixed on purpose. index.html loads these files as classic scripts sharing
 * ONE global scope, and app.js already declares `esc` and `pct` — a bare
 * `const esc` here is a redeclaration SyntaxError that kills app.js and takes
 * the whole dashboard down with it. */
const learnPct = (r) => (r == null ? "—" : `${Math.round(r * 100)}%`);
const learnEsc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* The one-line read. Deliberately not a letter grade: a "C+" invites you to
 * argue with the letter instead of looking at the number underneath it. */
function learnHeadline(s) {
  const d = s.directional;
  if (!s.total) {
    return { big: "No calls yet", sub: "Open the Live tab, rewind the dial, and call the next move before it prints." };
  }
  if (d.hitRate == null) {
    return { big: `${s.total} call${s.total === 1 ? "" : "s"}`, sub: "Nothing decisive yet — every directional call so far settled inside costs." };
  }
  const n = d.wins + d.losses;
  const sub = n < 20
    ? `${n} decisive calls. Too few to mean much yet — keep going.`
    : `${n} decisive calls, after costs.`;
  return { big: learnPct(d.hitRate), sub };
}

function renderCoach() {
  const body = document.querySelector("#coachBody");
  if (!body) return;
  const s = learnStats();
  const head = learnHeadline(s);

  const calib = s.calibration.map((c) => {
    const w = c.hitRate == null ? 0 : Math.round(c.hitRate * 100);
    const name = { 1: "low", 2: "medium", 3: "high" }[c.conf];
    const val = c.enough ? learnPct(c.hitRate) : `need ${MIN_CONF_CALLS - c.n} more`;
    return `<div class="cal-row">
      <span class="cal-name">${name}</span>
      <span class="cal-bar"><i style="width:${c.enough ? w : 0}%"></i></span>
      <span class="cal-val">${learnEsc(val)}</span>
    </div>`;
  }).join("");

  const tagList = (list, cls) => list.length
    ? list.map((t) => `<li class="${cls}"><b>${learnEsc(tagLabel(t.tag))}</b>
        <span>${learnPct(t.hitRate)} over ${t.wins + t.losses}</span></li>`).join("")
    : `<li class="tag-none">Not enough calls yet — a setup needs ${MIN_TAG_CALLS} before it counts.</li>`;

  const target = learnDrillTarget(s);
  const drillPitch = !target
    ? "Make a few calls and this will start aiming at whatever you keep getting wrong."
    : target.reason === "weakest"
      ? `Drops you on a <b>${learnEsc(tagLabel(target.tag))}</b> bar with the rest of the day hidden — your weakest read.`
      : `Drops you on a <b>${learnEsc(tagLabel(target.tag))}</b> bar with the rest of the day hidden — one you have barely called yet.`;

  const flags = s.flags.length
    ? s.flags.map((f) => `<li><b>${learnEsc(f.label)}</b><span>${learnEsc(f.detail)}</span></li>`).join("")
    : `<li class="flag-none">Nothing flagged yet.</li>`;

  body.innerHTML = `
    <div class="coach-grid">
      <div class="coach-card coach-headline">
        <div class="coach-big">${learnEsc(head.big)}</div>
        <div class="coach-sub">${learnEsc(head.sub)}</div>
        ${s.stand.n ? `<div class="coach-stand">Stood aside ${s.stand.n}×, right ${learnPct(s.stand.hitRate)} of the time.</div>` : ""}
        ${s.directional.flats ? `<div class="coach-stand">${s.directional.flats} call${s.directional.flats === 1 ? "" : "s"} settled inside costs — those were no-trade bars.</div>` : ""}
      </div>

      <div class="coach-card">
        <h3>Does your conviction mean anything?</h3>
        ${calib}
        ${s.inverted === true
          ? `<p class="coach-warn">Your conviction is inverted — you do worse when you are sure.</p>`
          : s.inverted === false
            ? `<p class="coach-good">Conviction lines up: your high-confidence calls do land better.</p>`
            : `<p class="coach-note">Not enough calls at each level to judge this yet.</p>`}
      </div>

      <div class="coach-card">
        <h3>Weakest reads</h3>
        <ul class="tag-list">${tagList(s.weakest, "is-weak")}</ul>
        <h3>Strongest reads</h3>
        <ul class="tag-list">${tagList(s.strongest, "is-strong")}</ul>
      </div>

      <div class="coach-card">
        <h3>Habits worth watching</h3>
        <ul class="flag-list">${flags}</ul>
      </div>

      <div class="coach-card coach-drill">
        <h3>Practice the one you keep missing</h3>
        <p>${drillPitch}</p>
        <button class="add-btn" id="coachDrill" type="button">Run a drill</button>
        <div class="drill-status" id="coachDrillStatus" role="status" aria-live="polite"></div>
      </div>
    </div>

    <div class="coach-caveats">
      <b>Read this before you trust the numbers</b>
      <ul>${s.caveats.map((c) => `<li>${learnEsc(c)}</li>`).join("")}</ul>
      <p>This grades your process, not any instrument. Nothing here is a suggestion to buy or sell.</p>
    </div>`;
}

function learnWireCoach() {
  const btn = document.querySelector("#coachReset");
  if (btn && btn.dataset.wired !== "1") {
    btn.dataset.wired = "1";
    btn.addEventListener("click", () => {
      if (!window.confirm("Clear every recorded call? This cannot be undone.")) return;
      learnReset();
      renderCoach();
    });
  }
  // Delegated: the drill button is re-created on every renderCoach(), so
  // binding it directly would leave a dead listener behind each time.
  const body = document.querySelector("#coachBody");
  if (!body || body.dataset.drillWired === "1") return;
  body.dataset.drillWired = "1";
  body.addEventListener("click", async (e) => {
    const hit = e.target.closest && e.target.closest("#coachDrill");
    if (!hit) return;
    const status = document.querySelector("#coachDrillStatus");
    const say = (m) => { if (status) status.textContent = m; };
    hit.disabled = true;
    say("Finding a setup…");
    try {
      const drill = await learnRunDrill(say);
      if (!drill) { hit.disabled = false; return; }
      say(`Loaded ${drill.sym} — ${drill.label}. Read it, then call it.`);
      // Hand over to the chart: the drill is only useful where the dial is.
      if (typeof setView === "function") setView("live");
    } catch (err) {
      say("Could not set up a drill just now.");
    } finally {
      hit.disabled = false;
    }
  });
}

function learnBoot() { learnWireUI(); learnWireCoach(); }

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", learnBoot);
} else {
  learnBoot();
}
