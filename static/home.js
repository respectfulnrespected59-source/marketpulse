/* MarketPulse — home view and first-run walkthrough.
 *
 * The cockpit landing view, saved DCA plans, and the 7-step onboarding.
 *
 * Split out of app.js to keep each file readable. Classic script, so it
 * shares one global scope with app.js and the other panels; everything
 * here is a declaration and nothing runs at load time. app.js is loaded
 * last because its init() call reaches into these.
 */

/* ---------------- First-run walkthrough (7 steps) -------------------------
   The problem this solves, in the user's words: "a large part of why things
   like this don't sell is because people don't even know exactly what it is or
   how to use it when they do get it."

   It is a CHECKLIST, not a modal tour -- nothing is blocked, nothing is
   hijacked, and it self-completes from real state rather than a counter you
   click through. Step 5 is the only one that cannot be satisfied by looking:
   you have to actually log a probe. That is deliberate -- the funnel is the
   lesson, and the lesson is being wrong cheaply. */
const ONBOARD_KEY = "mp_onboard";
const ONBOARD = [
  { view: "stocks",    title: "Read the board",
    blurb: "RSI, MACD and trend on real prices. Four factors have to agree before it says STRONG BUY." },
  { view: "pot",       title: "Set your pot",
    blurb: "The money you can afford to be wrong with. Everything else sizes off this number." },
  { view: "options",   title: "Find a play you can afford",
    blurb: "The cheapest probe that still teaches you something — not the four-thousand-dollar lottery ticket." },
  { view: "watchlist", title: "Watch a name",
    blurb: "Star what you're tracking so the board stays yours, not ours." },
  { view: "pot",       title: "Log your first probe", real: true,
    blurb: "Small enough to be wrong cheaply. This is the only step you can't finish just by looking." },
  { view: "proof",     title: "Prove it — losses and all",
    blurb: "Proof Mode backtests the same signal over years and shows what lost, not just what won." },
  { view: "dca",       title: "Plan the slow lane",
    blurb: "DCA is the unsexy one that most often survives. Worth knowing before you need it." },
];

function getOnboard() { return store.get(ONBOARD_KEY, { seen: [], done: false }); }

function markSeen(view) {
  const o = getOnboard();
  if (o.done || o.seen.includes(view)) return;
  o.seen.push(view);
  store.set(ONBOARD_KEY, o);
}

/* A step is complete when it is genuinely complete: `real` steps check actual
   state, the rest count as done once you've opened that tab. */
function onboardDone(step) {
  if (step.real) return (getPot().probes || []).length > 0;
  return getOnboard().seen.includes(step.view);
}

function renderOnboard() {
  const box = $("#homeOnboard");
  if (!box) return;
  const o = getOnboard();
  const done = ONBOARD.map(onboardDone);
  const n = done.filter(Boolean).length;
  if (o.done || n === ONBOARD.length) { box.innerHTML = ""; return; }
  const next = done.indexOf(false);
  box.innerHTML =
    `<div class="ob">
       <div class="ob-head">
         <span class="ob-title">Getting started</span>
         <span class="ob-count">${n} of ${ONBOARD.length}</span>
         <button class="ob-skip" type="button" id="obSkip">skip</button>
       </div>
       <div class="ob-bar"><i style="width:${(n / ONBOARD.length) * 100}%"></i></div>
       <ol class="ob-list">` +
    ONBOARD.map((s, i) =>
      `<li class="${done[i] ? "is-done" : i === next ? "is-next" : ""}">
         <span class="ob-mark">${done[i] ? "✓" : i + 1}</span>
         <span class="ob-step">
           <b>${esc(s.title)}</b>
           ${i === next ? `<span class="ob-blurb">${esc(s.blurb)}</span>` : ""}
         </span>
         ${done[i] ? "" : `<a class="ob-go" data-goto="${esc(s.view)}">open →</a>`}
       </li>`).join("") +
    `</ol></div>`;
  const skip = $("#obSkip");
  if (skip) skip.addEventListener("click", () => {
    store.set(ONBOARD_KEY, { ...getOnboard(), done: true });
    renderOnboard();
  });
}

/* State the refresh cadence plainly instead of leaving "Auto" to mean anything.
   The numbers are the real ones, not a marketing figure: the view timer is
   60000ms (see startAuto) and the server caches responses for CACHE_TTL=60s,
   so a reading can be up to a minute old. If Auto is off, say that too -- a
   stale board that looks live is worse than one that admits it. */
function cadenceLine() {
  const on = !!($("#autoRefresh") || {}).checked;
  const t = new Date().toLocaleTimeString();
  return on
    ? `Checked ${t} · re-reads every 60s · quotes cached up to 60s, so a reading can be a minute old.`
    : `Checked ${t} · <b>Auto is off</b> — this board will not update until you turn it on or hit refresh.`;
}

/* Honest market read for the cockpit.
   Most days there is no edge worth paying for. Say so, out loud, with the
   counts that prove it — an empty board is a finding, not a failure state.
   Every number here is counted from the same live signals the grids show;
   nothing is asserted that the tool did not just measure. */
async function renderHomeState() {
  const box = $("#homeState");
  if (!box) return;
  box.innerHTML = `<div class="hs hs-scan">Reading the board…</div>`;
  try {
    const [stocks, crypto] = await Promise.all([
      fetch("/api/markets?kind=stocks").then((r) => r.json()).catch(() => ({ rows: [] })),
      fetch("/api/markets?kind=crypto").then((r) => r.json()).catch(() => ({ rows: [] })),
    ]);
    const rows = [...(stocks.rows || []), ...(crypto.rows || [])].filter((r) => !r.error);
    if (!rows.length) {
      box.innerHTML = `<div class="hs hs-scan">Couldn't read the board just now — the data source is quiet.
        Nothing to act on until it comes back.</div>`;
      return;
    }
    const label = (r) => ((r.signal || {}).label || "NEUTRAL").toUpperCase();
    const strongBuy = rows.filter((r) => label(r) === "STRONG BUY").length;
    const strongSell = rows.filter((r) => label(r) === "STRONG SELL").length;
    const soft = rows.filter((r) => ["BUY", "SELL"].includes(label(r))).length;
    const strong = strongBuy + strongSell;

    let cls, head, body;
    if (strong === 0) {
      cls = "hs-quiet";
      head = "Nothing qualifies right now";
      body = `<b>0 of ${rows.length}</b> names show a strong signal`
        + (soft ? ` (${soft} weak — the engine does not enter on those)` : "")
        + `. That's a normal day. Most days there's no edge worth paying for,
           and sitting out is the trade.`;
    } else {
      cls = "hs-live";
      head = `${strong} of ${rows.length} names are showing conviction`;
      const parts = [];
      if (strongBuy) parts.push(`${strongBuy} strong buy`);
      if (strongSell) parts.push(`${strongSell} strong sell`);
      body = `${parts.join(" · ")}${soft ? ` · ${soft} weak (not actionable)` : ""}.
        Read it yourself before you act — a signal is a lean, never an order.`;
    }
    box.innerHTML = `<div class="hs ${cls}">`
      + `<div class="hs-head">${head}</div>`
      + `<div class="hs-body">${body}</div>`
      + `<div class="hs-foot">${cadenceLine()}</div></div>`;
  } catch (e) {
    box.innerHTML = `<div class="hs hs-scan">Board unavailable (${esc(e.message)}).
      Nothing to act on until it reads clean.</div>`;
  }
}

function renderHomePlans() {
  const plans = getDcaPlans();
  const box = $("#homePlansList");
  if (!plans.length) {
    box.innerHTML = `<div class="hc-empty">No saved plans yet. Build a DCA plan and hit 💾 Save plan.</div>`;
    return;
  }
  box.innerHTML = plans.map((pl) => {
    const ann = Math.round(pl.monthly * (PER_YEAR[pl.cadence] || 12));
    return `<div class="plan-row">
      <div class="plan-main"><b>${esc(pl.name)}</b>
        <span class="plan-meta">${esc(pl.symbol)} · $${Math.round(pl.monthly)} ${esc(pl.cadence)} · $${ann.toLocaleString()}/yr</span></div>
      <div class="plan-acts">
        <button class="plan-load" data-id="${esc(pl.id)}" type="button">Load</button>
        <button class="plan-del" data-id="${esc(pl.id)}" type="button" title="delete">🗑</button></div>
    </div>`;
  }).join("");
  box.querySelectorAll(".plan-load").forEach((b) => b.addEventListener("click", () => loadDcaPlan(b.dataset.id)));
  box.querySelectorAll(".plan-del").forEach((b) => b.addEventListener("click", () => delDcaPlan(b.dataset.id)));
}

function saveDcaPlan() {
  const symbol = ($("#dcaSymbol").value.trim() || "NVDA").toUpperCase();
  const kind = $("#dcaKind").value;
  const monthly = dcaMonthlyQf ? dcaMonthlyQf.getAmount() : 200;
  const cadence = $("#dcaCadence").value;
  const years = parseFloat($("#dcaYears").value) || 10;
  const name = prompt("Name this plan:", `${symbol} ${cadence} $${Math.round(monthly)}`);
  if (name == null) return;
  const plans = getDcaPlans();
  plans.push({ id: "dp" + Date.now(), name: (name.trim() || symbol), symbol, kind,
               monthly, cadence, years, created: new Date().toISOString().slice(0, 10) });
  saveDcaPlans(plans);
  renderHomePlans();
}

function loadDcaPlan(id) {
  const pl = getDcaPlans().find((x) => x.id === id);
  if (!pl) return;
  setView("dca");                       // mounts the DCA QuickFill widget
  $("#dcaSymbol").value = pl.symbol;
  $("#dcaKind").value = pl.kind;
  $("#dcaCadence").value = pl.cadence;
  $("#dcaYears").value = pl.years;
  if (dcaMonthlyQf) dcaMonthlyQf.setAmount(pl.monthly);
  dcaLoaded = true;
  loadDca();
}

function delDcaPlan(id) {
  if (!confirm("Delete this plan?")) return;
  saveDcaPlans(getDcaPlans().filter((x) => x.id !== id));
  renderHomePlans();
}

// Back up / restore everything in localStorage (the client-side safety net).
const BACKUP_KEYS = ["mp_pot", "mp_livetrack", "mp_dca_plans", "mp_watch",
                     "mp_alerts", "mp_stock_syms", "mp_crypto_ids"];
function exportData() {
  const data = {};
  BACKUP_KEYS.forEach((k) => { const v = localStorage.getItem(k); if (v != null) data[k] = v; });
  const payload = { app: "MarketPulse", exported: new Date().toISOString(), data };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "marketpulse-backup.json"; a.click();
  URL.revokeObjectURL(url);
}
function importData(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(reader.result);
      const data = parsed.data || parsed;
      if (!confirm("Import REPLACES your current pot, plays & plans. Continue?")) return;
      BACKUP_KEYS.forEach((k) => { if (data[k] != null) localStorage.setItem(k, data[k]); });
      location.reload();
    } catch (e) { alert("Couldn't read that backup file — is it a MarketPulse export?"); }
  };
  reader.readAsText(file);
}

// Robinhood-style quick-fill stake control (mounted lazily on first Live view).
let liveStakeQf = null;
function ensureLiveQf() {
  if (liveStakeQf || typeof QuickFill === "undefined") return;
  const el = $("#liveStakeQf");
  if (!el) return;
  liveStakeQf = QuickFill.mount(el, {
    amount: 300, chips: [50, 100, 250, 500, 1000], step: 25, min: 10,
    getContext: () => ({
      symbol: $("#liveSymbol").value.trim(),
      kind: $("#liveKind").value,
      side: $("#liveSide").value,
    }),
    priceFetcher: async (sym, kind) => {
      const q = await fetchQuote(kind === "crypto" ? sym.toLowerCase() : sym.toUpperCase(), kind);
      return q.price;
    },
  });
  ["#liveSymbol", "#liveKind", "#liveSide"].forEach((sel) =>
    $(sel).addEventListener("change", () => {
      if (liveStakeQf) liveStakeQf.refreshConversion();
      loadLiveTradeChart();
    }));
}

function livePnl(p, current) {
  const c = LIVE_BPS[p.kind === "crypto" ? "crypto" : "stock"];
  const movePct = (current - p.entry) / p.entry * 100;       // raw price move
  const dir = p.side === "put" ? -1 : 1;                     // bearish profits on a drop
  const dirRaw = movePct * dir;
  const costPct = 2 * (c.comm + c.slip) * 100;               // honest round-trip cost
  const netPct = dirRaw - costPct;
  return { movePct, dirRaw, costPct, netPct, netUsd: p.stake * netPct / 100 };
}

function fmtElapsed(fromSec, toSec) {
  let s = Math.max(0, Math.floor(toSec - fromSec));
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  if (d) return `${d}d ${h}h ${m}m`;
  if (h) return `${h}h ${m}m`;
  return `${m}m ${s}s`;
}

async function fetchQuote(sym, kind) {
  const d = await (await fetch(`/api/quote?symbol=${encodeURIComponent(sym)}&kind=${kind}`)).json();
  if (d.error || d.price == null) throw new Error(d.error || "no price");
  return d;
}

async function pinLive() {
  const sym = ($("#liveSymbol").value.trim() || "NVDA").toUpperCase();
  const kind = $("#liveKind").value;
  const side = $("#liveSide").value;
  const stake = liveStakeQf ? liveStakeQf.getAmount() : 300;
  $("#liveBoard").innerHTML = `<div class="proof-empty">Pulling live price for ${esc(sym)}…</div>`;
  try {
    const q = await fetchQuote(kind === "crypto" ? $("#liveSymbol").value.trim().toLowerCase() : sym, kind);
    const now = Math.floor(Date.now() / 1000);
    const sig = q.signal || { label: "NEUTRAL", css: "neutral", reasons: [] };
    const play = {
      sym, kind, side, stake, entry: q.price, entryTs: now,
      pinnedAt: new Date().toISOString(),
      entrySignal: { label: sig.label, css: sig.css, rsi: sig.rsi, reasons: (sig.reasons || []).slice(0, 6) },
      points: [{ t: now, price: q.price }],
      current: q.price, currentTs: now, status: "open", exit: null, closedAt: null,
    };
    saveLive(play);
    renderLive();
    loadLiveTradeChart();   // draw the gold entry line immediately
    startLivePoll();
  } catch (err) {
    $("#liveBoard").innerHTML = `<div class="proof-empty">Couldn’t pin ${esc(sym)}: ${esc(err.message)}</div>`;
  }
}

async function pollLive() {
  const p = getLive();
  if (!p || p.status !== "open") { stopLivePoll(); return; }
  try {
    const symQ = p.kind === "crypto" ? p.sym.toLowerCase() : p.sym;
    const q = await fetchQuote(symQ, p.kind);
    const now = Math.floor(Date.now() / 1000);
    p.current = q.price; p.currentTs = now;
    p.points.push({ t: now, price: q.price });
    if (p.points.length > 500) p.points = p.points.slice(-500);
    saveLive(p);
    if (state.view === "live") renderLive();
  } catch (err) { /* keep last good value; try again next tick */ }
}

function startLivePoll() {
  stopLivePoll();
  liveTimer = setInterval(pollLive, 20000);       // real prices ~every 20s
  liveClock = setInterval(tickLiveElapsed, 1000); // smooth elapsed counter
}
function stopLivePoll() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  if (liveClock) { clearInterval(liveClock); liveClock = null; }
}

function tickLiveElapsed() {
  const p = getLive();
  const el = $("#liveElapsed");
  if (!p || !el) return;
  const end = p.status === "open" ? Math.floor(Date.now() / 1000) : (p.closedAt || p.currentTs);
  el.textContent = fmtElapsed(p.entryTs, end);
}

function closeLive() {
  const p = getLive();
  if (!p || p.status !== "open") return;
  p.status = "closed"; p.exit = p.current; p.closedAt = Math.floor(Date.now() / 1000);
  saveLive(p); stopLivePoll(); renderLive();
}

function resetLive() {
  if (getLive() && !confirm("Clear this live play?")) return;
  localStorage.removeItem("mp_livetrack");
  stopLivePoll();
  renderLive();
}

function renderLive() {
  const board = $("#liveBoard");
  const p = getLive();
  if (!p) {
    board.innerHTML = `<div class="live-empty">No live play yet. Set a symbol, side & stake above, then
      <b>Pin entry</b> to lock a timestamped receipt and watch real prices decide it.</div>`;
    return;
  }
  const price = p.current ?? p.entry;
  const r = livePnl(p, price);
  const winCls = r.netUsd > 0 ? "win" : r.netUsd < 0 ? "lose" : "flat";
  const status = p.status === "open"
    ? (r.netUsd > 0 ? "🟢 WINNING (live)" : r.netUsd < 0 ? "🔴 LOSING (live)" : "⚪ FLAT (live)")
    : (r.netUsd > 0 ? "🟢 CLOSED · WIN" : r.netUsd < 0 ? "🔴 CLOSED · LOSS" : "⚪ CLOSED · FLAT");
  const side = LIVE_SIDE[p.side] || LIVE_SIDE.long;
  const moveArrow = r.movePct >= 0 ? "▲" : "▼";
  const dirCls = r.netUsd >= 0 ? "up" : "down";
  const pinnedLocal = new Date(p.pinnedAt).toLocaleString();
  const sig = p.entrySignal || {};

  board.innerHTML = `<div class="live-card ${winCls}">
    <div class="live-wm">LIVE MARKET TRACK · real prices · simulated fill (honest slippage) · no real order placed · not advice</div>
    <div class="live-top">
      <div class="live-asset">${esc(p.sym)} <span class="live-side ${side.cls}">${side.label}</span></div>
      <div class="live-status ${winCls}">${status}</div>
    </div>
    <div class="live-nums">
      <div class="ln"><span>Entry</span><b>${fmtPrice(p.entry)}</b><i>${esc(pinnedLocal)}</i></div>
      <div class="ln"><span>${p.status === "open" ? "Live price" : "Exit price"}</span>
        <b class="${dirCls}">${fmtPrice(price)}</b><i>${moveArrow} ${Math.abs(r.movePct).toFixed(2)}%</i></div>
      <div class="ln big"><span>Net P&amp;L on $${p.stake}</span>
        <b class="${dirCls}">${r.netUsd >= 0 ? "+" : "-"}$${Math.abs(r.netUsd).toFixed(2)}</b>
        <i>${r.netPct >= 0 ? "+" : ""}${r.netPct.toFixed(2)}% after ${r.costPct.toFixed(2)}% costs</i></div>
      <div class="ln"><span>Elapsed</span><b id="liveElapsed">${fmtElapsed(p.entryTs, p.status === "open" ? Math.floor(Date.now() / 1000) : p.closedAt)}</b>
        <i>${p.status}</i></div>
    </div>
    <div class="live-read">📖 The READ at entry:
      <span class="badge ${esc(sig.css || "neutral")}">${esc(sig.label || "—")}</span>
      ${sig.rsi != null ? "RSI " + sig.rsi + " · " : ""}${esc((sig.reasons || []).join(" · "))}</div>
    <div class="proof-chart-wrap"><svg id="liveChart" class="proof-chart" viewBox="0 0 1000 220" preserveAspectRatio="none"></svg></div>
    <div class="live-actions">
      ${p.status === "open" ? `<button class="add-btn" id="liveClose" type="button">Close &amp; snapshot</button>` : ""}
      <button class="add-btn ghost" id="liveReset" type="button">New play</button>
      <span class="live-note">${p.side === "long" ? "Literal long stake." : "Modeled as a directional $ stake — a real option adds leverage + theta, so treat this as the READ being right, not an exact option payoff."}
        Prices refresh ~20s (crypto can lag ~1m). ${p.status === "open" ? "Recording? This updates live." : ""}</span>
    </div>
  </div>`;

  renderLiveChart(p, winCls);
  $("#liveClose")?.addEventListener("click", closeLive);
  $("#liveReset")?.addEventListener("click", resetLive);
}

function renderLiveChart(p, winCls) {
  const svg = $("#liveChart");
  const pts = p.points || [];
  const W = 1000, H = 220, pad = 10;
  if (pts.length < 2) {
    // one dot at entry until the next poll lands
    const y = H / 2;
    svg.innerHTML = `<line x1="${pad}" y1="${y}" x2="${W - pad}" y2="${y}" stroke="#3a4757" stroke-dasharray="4 4"/>
      <circle cx="${pad}" cy="${y}" r="4" fill="var(--gold)"/>`;
    return;
  }
  const prices = pts.map((q) => q.price);
  const min = Math.min(...prices, p.entry), max = Math.max(...prices, p.entry), span = max - min || 1;
  const X = (i) => pad + (i / (pts.length - 1)) * (W - pad * 2);
  const Y = (v) => pad + (1 - (v - min) / span) * (H - pad * 2);
  const line = pts.map((q, i) => `${X(i).toFixed(1)},${Y(q.price).toFixed(1)}`).join(" ");
  const entryY = Y(p.entry).toFixed(1);
  const col = winCls === "win" ? "var(--buy)" : winCls === "lose" ? "var(--sell)" : "#8a99ab";
  svg.innerHTML =
    `<line x1="${pad}" y1="${entryY}" x2="${W - pad}" y2="${entryY}" stroke="var(--gold)" stroke-width="1" stroke-dasharray="5 4" opacity="0.7"><title>entry ${p.entry}</title></line>` +
    `<polyline points="${line}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>` +
    `<circle cx="${X(pts.length - 1)}" cy="${Y(prices[prices.length - 1])}" r="4" fill="${col}"/>`;
}

