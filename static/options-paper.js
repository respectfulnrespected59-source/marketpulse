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
    const r = await fetch(`/api/options?symbol=${encodeURIComponent(sym)}`);
    const d = await r.json();
    if (d.error || !d.spread) {
      out.innerHTML = `<div class="paper-validation bad">${
        esc(d.error || "No directional spread right now — the signal is neutral.")
      }</div>`;
      return;
    }
    const s = d.spread;
    optBookDraft = {
      symbol: d.symbol, expiry: d.expiry,
      legs: [
        { right: s.direction, strike: s.long.strike, side: "long" },
        { right: s.direction, strike: s.short.strike, side: "short" },
      ],
    };
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
         the data, not a directive — and ${optNum(d.dte)} days is not much time to be right.</div>`;
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
  try {
    const r = await fetch("/api/options/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...optBookDraft, contracts }),
    });
    const d = await r.json();
    if (d.error || !d.position) {
      if (out) out.innerHTML = `<div class="paper-validation bad">${esc(d.error || "Could not open.")}</div>`;
      return;
    }
    const b = getOptBook();
    const pos = { ...d.position, id: optBookId() };
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
          opened: pos.opened, closed: Date.now(),
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
    saveOptBook(b);
    renderOptBook();
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
    opened: pos.opened, closed: Date.now(),
  });
  b.open = b.open.filter((p) => p.id !== id);
  delete b.marks[id];
  saveOptBook(b);
  renderOptBook();
  // A closed position must leave the snapshot too, or the journal keeps
  // marking something you no longer hold.
  optBookExport();
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
        return `<div class="paper-row ${cls}">
            <b>${esc(optBookLabel(p))}</b>
            <span>${optNum(p.contracts)}x · in ${optBookMoney(p.cost_usd)}</span>
            <span>mark ${m.mark != null ? fmtPrice(m.mark) : "—"}</span>
            ${pnl}${pct}${theta}${dte}
            <span class="muted">risk ${optBookMoney(p.max_loss_usd)} · BE ${fmtPrice(p.breakeven)}</span>
            <button type="button" class="ltc-tool ghost" data-optclose="${esc(p.id)}">Close</button>
          </div>`;
      }).join("")
    : `<div class="proof-empty">No open options positions. Load a spread above to test one.</div>`;

  for (const btn of host.querySelectorAll("[data-optclose]")) {
    btn.addEventListener("click", () => optBookClose(btn.dataset.optclose));
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
