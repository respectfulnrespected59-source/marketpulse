/* MarketPulse — the options paper book.
 *
 * The Options tab could always build a spread and then had nowhere to prove
 * it: you got talked into a put debit spread and the app shrugged. This is
 * where the idea gets tested.
 *
 * Two rules govern everything here, and both cost the trader money on paper
 * so that reality is not a surprise:
 *
 *   1. This file never prices a fill. Entries go through /api/options/open
 *      and marks through /api/options/mark, so entry math and exit math come
 *      from the same tested module. If the client priced its own entries the
 *      two would drift, and a book whose entry and exit disagree can show a
 *      profit that was never available.
 *   2. Nothing is ever marked at the mid. You buy at the ask, sell at the
 *      bid, and a freshly opened spread is therefore already down by the
 *      spread. That is real. Better to see it on day one than at the exit.
 *
 * Sizing is deliberately NOT capped against the $300 pot. That pot and its
 * 20% probe are a recommendation for someone learning on a small stake; the
 * question this book answers is whether the play works. Anyone who can fund
 * the full-size trade should be able to run the identical play, so contracts
 * are the trader's call.
 *
 * State lives in localStorage — this browser's record and nobody else's.
 * All globals are prefixed, because static/*.js share one scope.
 */

const OPT_BOOK_KEY = "mp_optbook";
// The chain is CBOE-delayed ~15m, so polling faster than this only burns
// requests to redraw the same number.
const OPT_BOOK_POLL_MS = 60000;
const OPT_BOOK_START_CASH = 10000;

let optBookTimer = null;
let optBookBusy = false;
let optBookDraft = null;      // the spread loaded but not yet opened

function optBookDefaults() {
  return {
    bankroll: OPT_BOOK_START_CASH,
    realized: 0,
    open: [],        // positions exactly as /api/options/open returned them
    closed: [],      // most recent first
    marks: {},       // id -> last mark from the server
    lastMark: null,
    lastError: "",
  };
}

function getOptBook() {
  try {
    const raw = JSON.parse(localStorage.getItem(OPT_BOOK_KEY) || "null");
    if (raw && typeof raw === "object") return { ...optBookDefaults(), ...raw };
  } catch (e) { /* corrupt state must not cost the whole tab */ }
  return optBookDefaults();
}

function saveOptBook(b) {
  try { localStorage.setItem(OPT_BOOK_KEY, JSON.stringify(b)); } catch (e) { /* private mode */ }
}

function optBookMoney(v) {
  if (v == null) return "—";
  return (v < 0 ? "-" : "") + "$" + Math.abs(v).toFixed(2);
}

function optBookId() {
  return "op" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

/* Every number that reaches innerHTML goes through here.
 *
 * These all arrive as JSON from our own API, so today they are genuinely
 * numbers — but "it is a number because the server said so" is exactly the
 * assumption that turns one compromised upstream into script execution on a
 * page where people keep their trading record. Coercing costs nothing. */
function optNum(v, dp) {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return dp == null ? String(n) : n.toFixed(dp);
}

/* Describe a position the way a trader would say it out loud. */
function optBookLabel(pos) {
  const legs = (pos.legs || []).map(
    (l) => `${l.side === "short" ? "-" : "+"}${l.strike}${l.right === "put" ? "P" : "C"}`
  ).join(" / ");
  return `${pos.symbol} ${legs} · ${pos.expiry}`;
}

/* ------------------------------------------------------------ opening */

/* Pull the spread the signal implies, so the trader can see the play before
   committing to it. Deliberately a two-step flow: load, look, then open. */
async function optBookLoadSuggestion() {
  const sym = ($("#optBookSymbol")?.value || "").trim().toUpperCase();
  const out = $("#optBookDraft");
  if (!sym || !out) return;
  out.innerHTML = `<div class="proof-empty">Reading the chain for ${esc(sym)}…</div>`;
  optBookDraft = null;
  try {
    // The chain and the stock's 30-day read in parallel: the Para-Sail rules need to know whether the
    // stock is at its low (static/options-parasail.js). A failed read is "unknown", never a guess.
    const [r, zr] = await Promise.all([
      fetch(`/api/options?symbol=${encodeURIComponent(sym)}`),
      fetch(`/api/parasail?symbol=${encodeURIComponent(sym)}&kind=stock`).catch(() => null),
    ]);
    const d = await r.json();
    let zone = null;
    try { zone = zr && zr.ok ? (await zr.json()).zone || null : null; } catch (e) { zone = null; }
    if (d.error || !d.spread) {
      out.innerHTML = `<div class="paper-validation bad">${
        esc(d.error || "No directional spread right now — the signal is neutral.")
      }</div>`;
      return;
    }
    const s = d.spread;
    const plan = typeof optSetup === "function" ? optSetup(s.direction, zone) : null;
    optBookDraft = {
      symbol: d.symbol, expiry: d.expiry, perContract: Number(s.per_contract), plan,
      legs: [
        { right: s.direction, strike: s.long.strike, side: "long" },
        { right: s.direction, strike: s.short.strike, side: "short" },
      ],
    };
    const planLine = plan
      ? `<div class="paper-validation ${plan.onPlan ? "good" : "bad"}"><b>${plan.onPlan
          ? `Para-Sail: ON PLAN · ${esc(plan.setup.toUpperCase())}` : `Para-Sail: ${esc(plan.setup.toUpperCase())}`}</b>
          — ${esc(plan.why)}. Take the icing at +${optNum(OPT_PS.sailAt * 100)}%; on expiry day, take it or cut it by noon New York time.</div>`
      : "";
    out.innerHTML =
      `<div class="paper-row">
         <b>${esc(d.symbol)} ${esc(s.type)}</b>
         <span>BUY ${fmtPrice(s.long.strike)} / SELL ${fmtPrice(s.short.strike)}</span>
         <span class="muted">exp ${esc(d.expiry)} · ${optNum(d.dte)}d</span>
       </div>
       <div class="paper-row">
         <span>Debit ${optBookMoney(s.per_contract)}/ct</span>
         <span class="up">max +${optBookMoney(s.max_profit * 100)}</span>
         <span class="down">max ${optBookMoney(-s.max_loss * 100)}</span>
         <span class="muted">breakeven ${fmtPrice(s.breakeven)} · R:R ${optNum(s.risk_reward, 2)}</span>
       </div>
       <div class="muted small">Signal ${esc((d.lean && d.lean.label) || "")}. A read from
         the data, not a directive — and ${optNum(d.dte)} days is not much time to be right.</div>` + planLine;
  } catch (err) {
    out.innerHTML = `<div class="paper-validation bad">Couldn't reach the chain.</div>`;
  }
}

async function optBookOpen() {
  const out = $("#optBookDraft");
  if (!optBookDraft) {
    if (out) out.innerHTML = `<div class="paper-validation bad">Load a spread first.</div>`;
    return;
  }
  const contracts = Math.max(1, parseInt($("#optBookContracts")?.value, 10) || 1);
  // Para-Sail cap: a spread costing over 10 % of equity may still open, but it is logged OFF PLAN.
  let plan = optBookDraft.plan ? { ...optBookDraft.plan } : null;
  if (plan && typeof optCapCheck === "function" && isFinite(optBookDraft.perContract)) {
    const cap = optCapCheck(optBookDraft.perContract * contracts, optBookStats(getOptBook()).equity);
    if (!cap.ok) {
      if (!confirm(`That's ${optNum(cap.pct, 1)}% of your equity — over the Para-Sail 10% cap. `
                   + "Open it anyway? It will be logged OFF PLAN.")) return;
      plan = { ...plan, setup: "off plan", onPlan: false, why: `${plan.why}; over the 10% cap (${optNum(cap.pct, 1)}%)` };
    }
  }
  try {
    const { plan: _p, perContract: _pc, ...spec } = optBookDraft;   // the server gets the legs, not our notes
    const r = await fetch("/api/options/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...spec, contracts }),
    });
    const d = await r.json();
    if (d.error || !d.position) {
      if (out) out.innerHTML = `<div class="paper-validation bad">${esc(d.error || "Could not open.")}</div>`;
      return;
    }
    const b = getOptBook();
    const id = optBookId();
    const pos = { ...d.position, id, trade: id };
    if (plan) Object.assign(pos, { setup: plan.setup, onPlan: plan.onPlan, why: plan.why });   // scored by the forward test
    b.open.push(pos);
    saveOptBook(b);
    optBookDraft = null;
    if (out) out.innerHTML = "";
    if (typeof toast === "function") {
      toast("buy", `Paper open · ${pos.symbol}`,
            `${contracts}x for ${optBookMoney(pos.cost_usd)}`);
    }
    renderOptBook();
    optBookTick();
    // Keep the journal's snapshot current without anyone having to remember.
    optBookExport();
    // Watch it where the price moves: the live chart draws the breakeven and
    // strikes and shows the P&L strip (chart-options.js).
    if (typeof openLiveFor === "function") openLiveFor("stock", pos.symbol);
  } catch (err) {
    if (out) out.innerHTML = `<div class="paper-validation bad">Couldn't reach the server.</div>`;
  }
}

/* ------------------------------------------------------------ the loop */

async function optBookTick() {
  if (optBookBusy) return;
  const b = getOptBook();
  if (!b.open.length) { renderOptBook(); return; }
  optBookBusy = true;
  try {
    const r = await fetch("/api/options/mark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ positions: b.open }),
    });
    const d = await r.json();
    if (d.error) {
      b.lastError = d.error;
      saveOptBook(b);
      renderOptBook();
      return;
    }
    b.lastError = "";
    b.marks = {};
    for (const m of d.marks || []) if (m.id) b.marks[m.id] = m;

    // An expired position is settled and booked automatically — leaving it
    // "open" forever would quietly hide a realised loss.
    const stillOpen = [];
    for (const pos of b.open) {
      const m = b.marks[pos.id];
      if (m && m.status === "expired" && m.net_usd != null) {
        b.realized += m.net_usd;
        b.closed.unshift({
          id: pos.id, symbol: pos.symbol, label: optBookLabel(pos),
          contracts: pos.contracts, entry_debit: pos.entry_debit,
          exit: m.mark, pnl: m.net_usd, why: "expired",
          opened: pos.opened, closed: Date.now(), ...optBookPlanFields(pos),
        });
        if (typeof toast === "function") {
          toast(m.net_usd >= 0 ? "buy" : "sell", `Expired · ${pos.symbol}`,
                optBookMoney(m.net_usd));
        }
      } else {
        stillOpen.push(pos);
      }
    }
    b.open = stillOpen;
    b.lastMark = Date.now();
    optBookParaSailCalls(b);
    saveOptBook(b);
    renderOptBook();
    // The live chart's strip reads the same book; show the new mark there now.
    if (typeof refreshOptStrip === "function") refreshOptStrip();
  } catch (err) {
    // A network blip must not stop the book.
  } finally {
    optBookBusy = false;
  }
}

/* Close at the current mark — the price you could really get out at. */
function optBookClose(id) {
  const b = getOptBook();
  const pos = (b.open || []).find((p) => p.id === id);
  const m = (b.marks || {})[id];
  if (!pos) return;
  if (!m || m.net_usd == null) {
    alert("No live mark for this position yet — it can't be closed at a price nobody quoted.");
    return;
  }
  if (!confirm(`Close ${optBookLabel(pos)} at ${optBookMoney(m.mark)} for ${optBookMoney(m.net_usd)}?`)) return;
  b.realized += m.net_usd;
  b.closed.unshift({
    id, symbol: pos.symbol, label: optBookLabel(pos),
    contracts: pos.contracts, entry_debit: pos.entry_debit,
    exit: m.mark, pnl: m.net_usd, why: "closed manually",
    opened: pos.opened, closed: Date.now(), ...optBookPlanFields(pos),
  });
  b.open = b.open.filter((p) => p.id !== id);
  delete b.marks[id];
  saveOptBook(b);
  renderOptBook();
  // A closed position must leave the snapshot too, or the journal keeps
  // marking something you no longer hold.
  optBookExport();
}

/* ------------------------------------------------------ the Para-Sail rules (static/options-parasail.js) */

/* What the forward test scores on a closed record: the trade it belongs to and whether it was on plan.
 * A position opened before the rules has no setup and stays out of the scorecard. */
function optBookPlanFields(pos) {
  if (!pos.setup) return {};
  return { trade: pos.trade || pos.id, setup: pos.setup, onPlan: pos.onPlan === true, sailed: pos.sailed === true };
}

/* Each tick: call the icing once per trade, and the time parachute once per position. */
function optBookParaSailCalls(b) {
  if (typeof optSailDue !== "function") return;
  for (const pos of b.open || []) {
    if (!pos.setup) continue;
    const m = (b.marks || {})[pos.id];
    if (!pos.sailCalled && optSailDue(pos, m)) {
      pos.sailCalled = true;
      const n = Number(pos.contracts);
      if (typeof toast === "function") {
        toast("buy", `PARA-SAIL · ${pos.symbol}`, n > 1
          ? `Up ${optNum((m.net_usd / pos.cost_usd) * 100, 0)}% — take the icing: close ${optHalf(n)} of ${n}.`
          : `Up ${optNum((m.net_usd / pos.cost_usd) * 100, 0)}% — one contract: the icing is the whole thing.`);
      }
    }
    if (!pos.chuteCalled && optTimeParachute(pos.expiry, Date.now())) {
      pos.chuteCalled = true;
      if (typeof toast === "function") {
        toast("sell", `TIME PARACHUTE · ${pos.symbol}`, "Expiry-day afternoon — take it or cut it.");
      }
    }
  }
}

/* Para-sail: close half at the current mark (one contract = all of it). The rest keeps its id, so the
 * live mark follows it; the closed half keeps the trade id, so the scorecard counts one trade. */
function optBookSail(id) {
  const b = getOptBook();
  const pos = (b.open || []).find((p) => p.id === id);
  const m = (b.marks || {})[id];
  if (!pos) return;
  if (!m || m.net_usd == null) {
    alert("No live mark for this position yet — it can't be closed at a price nobody quoted.");
    return;
  }
  const n = Number(pos.contracts);
  const half = optHalf(n);
  const { closed, rest } = optSplitClose(pos, m, half);
  if (!confirm(`Para-sail ${optBookLabel(pos)}: close ${half} of ${n} at ${optBookMoney(m.mark)} for `
               + `${optBookMoney(closed.pnl)}?`)) return;
  b.realized += closed.pnl;
  b.closed.unshift({ ...closed, label: optBookLabel(pos), why: rest ? "para-sail (half)" : "para-sail (1 contract: all)" });
  b.open = rest ? b.open.map((p) => (p.id === id ? rest : p)) : b.open.filter((p) => p.id !== id);
  delete b.marks[id];          // the old mark priced the old contract count; the next tick re-marks the rest
  saveOptBook(b);
  renderOptBook();
  optBookExport();
  if (rest) optBookTick();
}

/* Park the book on disk so the scheduled Obsidian journal can see it.
 *
 * localStorage is invisible to a cron job, so without this the daily note
 * reports "open_positions: unknown" forever — which is honest, but useless.
 * The server picks the filename; we only send the book. */
async function optBookExport() {
  const b = getOptBook();
  const status = $("#optBookStatus");
  try {
    const r = await fetch("/api/options/book/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ positions: b.open || [] }),
    });
    const d = await r.json();
    if (d.error || !d.ok) {
      if (status) {
        status.textContent = d.error || "Export failed.";
        status.className = "paper-status bad";
      }
      return;
    }
    // Exporting an empty book is meaningful: it records "flat today" instead
    // of leaving the journal unable to tell flat from blind.
    if (status) {
      status.textContent = `exported ${d.count} position${d.count === 1 ? "" : "s"} `
        + `for the journal · ${new Date().toLocaleTimeString()}`;
      status.className = "paper-status live";
    }
    if (typeof toast === "function") {
      toast("buy", "Exported to journal", `${d.count} position${d.count === 1 ? "" : "s"}`);
    }
  } catch (err) {
    if (status) {
      status.textContent = "Couldn't reach the server to export.";
      status.className = "paper-status bad";
    }
  }
}

function optBookReset() {
  if (!confirm("Clear the whole options paper book — positions, trades and P&L?")) return;
  const b = getOptBook();
  const fresh = optBookDefaults();
  fresh.bankroll = b.bankroll;      // keep their stake, drop the results
  saveOptBook(fresh);
  renderOptBook();
}

function optBookSetBankroll() {
  const v = parseFloat($("#optBookBankroll")?.value);
  if (!isFinite(v) || v <= 0) return;
  const b = getOptBook();
  b.bankroll = v;
  saveOptBook(b);
  renderOptBook();
}

/* ---------------------------------------------------------- rendering */

function optBookStats(b) {
  const closed = b.closed || [];
  const wins = closed.filter((t) => t.pnl > 0).length;
  let atRisk = 0;
  for (const p of b.open || []) atRisk += Number(p.max_loss_usd) || 0;
  let openPnl = 0;
  let unquoted = 0;
  for (const p of b.open || []) {
    const m = (b.marks || {})[p.id];
    if (m && m.net_usd != null) openPnl += m.net_usd;
    else unquoted += 1;
  }
  return {
    equity: b.bankroll + b.realized,
    realized: b.realized,
    openPnl, atRisk, unquoted,
    trades: closed.length,
    winRate: closed.length ? Math.round((wins / closed.length) * 100) : null,
    openCount: (b.open || []).length,
  };
}

function renderOptBook() {
  const host = $("#optBookOpen");
  if (!host) return;
  const b = getOptBook();
  const s = optBookStats(b);

  const stats = $("#optBookStats");
  if (stats) {
    stats.innerHTML =
      `<div class="pst"><span>Equity</span><b>${optBookMoney(s.equity)}</b></div>` +
      `<div class="pst"><span>Realized</span><b class="${s.realized >= 0 ? "up" : "down"}">${optBookMoney(s.realized)}</b></div>` +
      `<div class="pst"><span>Open P&amp;L</span><b class="${s.openPnl >= 0 ? "up" : "down"}">${optBookMoney(s.openPnl)}</b></div>` +
      `<div class="pst"><span>At risk</span><b>${optBookMoney(s.atRisk)}</b></div>` +
      `<div class="pst"><span>Trades</span><b>${s.trades}</b></div>` +
      `<div class="pst"><span>Win rate</span><b>${s.winRate == null ? "—" : s.winRate + "%"}</b></div>`;
  }

  const status = $("#optBookStatus");
  if (status) {
    status.textContent = b.lastError
      ? b.lastError
      : b.lastMark
        ? `marked ${new Date(b.lastMark).toLocaleTimeString()} · chain is ~15m delayed`
        : (b.open || []).length ? "marking…" : "no open positions";
    status.className = "paper-status" + (b.lastError ? " bad" : (b.open || []).length ? " live" : "");
  }

  host.innerHTML = (b.open || []).length
    ? b.open.map((p) => {
        const m = (b.marks || {})[p.id] || {};
        const live = m.net_usd != null;
        const cls = !live ? "" : m.net_usd >= 0 ? "win" : "loss";
        const pnl = live
          ? `<span class="${m.net_usd >= 0 ? "up" : "down"}">${optBookMoney(m.net_usd)}</span>`
          : `<span class="muted">unquoted</span>`;
        const pct = (live && m.pct_of_max != null) ? ` <span class="muted">${optNum(m.pct_of_max, 1)}% of max</span>` : "";
        const theta = (m.greeks && m.greeks.theta != null)
          ? ` <span class="muted">θ ${optNum(m.greeks.theta, 2)}/day</span>` : "";
        const dte = m.dte != null ? ` <span class="muted">${optNum(m.dte)}d left</span>` : "";
        // Para-Sail: the plan tag, the icing button once it's due, and the time parachute on expiry day.
        const planTag = p.setup
          ? ` <span class="${p.onPlan ? "up" : "down"}" title="${esc(p.why || "")}">${p.onPlan ? "on plan" : "off plan"} · ${esc(p.setup)}</span>` : "";
        const sail = (p.setup && typeof optSailDue === "function" && optSailDue(p, m))
          ? `<button type="button" class="ltc-tool" data-optsail="${esc(p.id)}">PARA-SAIL · close ${optNum(optHalf(p.contracts))} of ${optNum(p.contracts)}</button>` : "";
        const chute = (typeof optTimeParachute === "function" && optTimeParachute(p.expiry, Date.now()))
          ? ` <span class="down"><b>TIME PARACHUTE</b> — expiry-day afternoon: take it or cut it</span>` : "";
        return `<div class="paper-row ${cls}">
            <b>${esc(optBookLabel(p))}</b>
            <span>${optNum(p.contracts)}x · in ${optBookMoney(p.cost_usd)}</span>
            <span>mark ${m.mark != null ? fmtPrice(m.mark) : "—"}</span>
            ${pnl}${pct}${theta}${dte}${planTag}${chute}
            <span class="muted">risk ${optBookMoney(p.max_loss_usd)} · BE ${fmtPrice(p.breakeven)}</span>
            ${sail}
            <button type="button" class="ltc-tool ghost" data-optchart="${esc(p.symbol)}">Chart</button>
            <button type="button" class="ltc-tool ghost" data-optclose="${esc(p.id)}">Close</button>
          </div>`;
      }).join("")
    : `<div class="proof-empty">No open options positions. Load a spread above to test one.</div>`;

  for (const btn of host.querySelectorAll("[data-optclose]")) {
    btn.addEventListener("click", () => optBookClose(btn.dataset.optclose));
  }
  for (const btn of host.querySelectorAll("[data-optsail]")) {
    btn.addEventListener("click", () => optBookSail(btn.dataset.optsail));
  }
  renderOptScore(b);
  for (const btn of host.querySelectorAll("[data-optchart]")) {
    btn.addEventListener("click", () => {
      if (typeof openLiveFor === "function") openLiveFor("stock", btn.dataset.optchart);
    });
  }

  const closedBox = $("#optBookClosed");
  if (closedBox) {
    const rows = (b.closed || []).slice(0, 25);
    closedBox.innerHTML = rows.length
      ? rows.map((t) =>
          `<div class="paper-row ${t.pnl >= 0 ? "win" : "loss"}">
             <b>${esc(t.label || t.symbol)}</b>
             <span>${optNum(t.contracts)}x</span>
             <span class="${t.pnl >= 0 ? "up" : "down"}">${optBookMoney(t.pnl)}</span>
             <span class="muted">${esc(t.why || "")}</span>
           </div>`).join("")
      : `<div class="proof-empty">No closed options trades yet. Log the losers too — a book that
           only keeps winners is worth less than no book.</div>`;
  }
}

/* The pre-registered forward test (docs/PARASAIL_OPTIONS_PREREG.md): n of 25, losers counted, and a verdict
 * decided in advance — expectancy after every cost above $0 — only once 25 trades are in. */
function renderOptScore(b) {
  const box = $("#optBookScore");
  if (!box || typeof optScorecard !== "function") return;
  const riding = (b.open || []).filter((p) => p.setup).map((p) => p.trade || p.id);
  const s = optScorecard(b.closed || [], riding);
  const money = (v) => (v == null ? "—" : optBookMoney(v));
  const verdict = s.verdict === "pass"
    ? `<b class="up">PASS</b> — expectancy ${money(s.expectancy)} a trade after every cost.`
    : s.verdict === "fail"
      ? `<b class="down">FAIL</b> — expectancy ${money(s.expectancy)} a trade after every cost. Said out loud, same as a pass.`
      : `No verdict until ${optNum(s.target)} trades — losers count, nothing gets deleted.`;
  box.innerHTML = `<div class="paper-row"><b>Para-Sail forward test</b>
      <span>${optNum(s.n)} / ${optNum(s.target)} trades${s.open ? ` · ${optNum(s.open)} still riding (scored when closed)` : ""}</span>
      <span>on plan ${optNum(s.onPlan.n)} (${money(s.onPlan.total)}) · off plan ${optNum(s.offPlan.n)} (${money(s.offPlan.total)})</span>
      <span>win rate ${s.winRate == null ? "—" : optNum(s.winRate) + "%"} · avg win ${money(s.avgWin)} · avg loss ${money(s.avgLoss)}</span>
      <span>expectancy ${s.n ? money(s.expectancy) : "—"} a trade</span></div>
    <div class="muted small">${verdict} Rules registered 2026-09-30, before the first trade.</div>`;
}

function initOptBook() {
  const host = $("#optBookOpen");
  if (!host || host.dataset.wired === "1") return;
  host.dataset.wired = "1";

  const b = getOptBook();
  const bank = $("#optBookBankroll");
  if (bank) {
    bank.value = b.bankroll;
    bank.addEventListener("change", optBookSetBankroll);
  }
  $("#optBookLoadBtn")?.addEventListener("click", optBookLoadSuggestion);
  $("#optBookOpenBtn")?.addEventListener("click", optBookOpen);
  $("#optBookExportBtn")?.addEventListener("click", optBookExport);
  $("#optBookResetBtn")?.addEventListener("click", optBookReset);

  if (optBookTimer) clearInterval(optBookTimer);
  optBookTimer = setInterval(optBookTick, OPT_BOOK_POLL_MS);
  renderOptBook();
  optBookTick();
}
