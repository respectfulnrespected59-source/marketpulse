/* MarketPulse — paper trading in the browser.
 *
 * You declare rules; the server evaluates them against real prices with the
 * SAME engine the paid agent uses; this file opens and closes paper positions
 * from those decisions and keeps the record.
 *
 * Two things it is careful about, because they are what make a paper record
 * worth anything:
 *
 *   1. No real order is ever placed. Not a simulated broker call, not a key,
 *      nothing. Prices are real; the fills are ours.
 *   2. Fills are charged honest costs — the same commission and slippage model
 *      the backtest uses. A paper record that fills at the mid price flatters
 *      itself, and flattering numbers are how people talk themselves into
 *      risking money on a system that never worked.
 *
 * State lives in localStorage, so it is this browser's record and nobody
 * else's. Clearing site data clears it.
 */

const PAPER_KEY = "mp_paper";
const PAPER_POLL_MS = 30000;
// Same per-venue costs the backtest charges. Stocks: no commission, 5bps
// slippage. Crypto: 25bps commission, 20bps slippage.
const PAPER_COSTS = {
  stock: { comm: 0, slip: 0.0005 },
  crypto: { comm: 0.0025, slip: 0.0020 },
};
const PAPER_START_CASH = 10000;

let paperTimer = null;
let paperBusy = false;

function paperDefaults() {
  return {
    strategy: null,
    running: false,
    startCash: PAPER_START_CASH,
    realized: 0,
    open: {},        // SYMBOL -> { symbol, kind, entry, qty, notional, ts }
    closed: [],      // most recent first
    startedAt: null,
    lastRun: null,
    lastError: "",
  };
}

function getPaper() {
  try {
    const raw = JSON.parse(localStorage.getItem(PAPER_KEY) || "null");
    if (raw && typeof raw === "object") return { ...paperDefaults(), ...raw };
  } catch (e) { /* corrupt state must not cost the whole tab */ }
  return paperDefaults();
}

function savePaper(p) {
  try { localStorage.setItem(PAPER_KEY, JSON.stringify(p)); } catch (e) { /* private mode */ }
}

/* A buy fills a little worse than quoted and a sell a little worse again —
   that difference is most of why paper results beat live ones. */
function paperFill(price, kind, side) {
  const c = PAPER_COSTS[kind === "crypto" ? "crypto" : "stock"];
  const slipped = side === "buy" ? price * (1 + c.slip) : price * (1 - c.slip);
  return slipped * (side === "buy" ? 1 + c.comm : 1 - c.comm);
}

function paperEquity(p) {
  return p.startCash + p.realized;
}

/* True while a symbol is still inside its post-exit cooldown. */
function paperCooledDown(p, symbol, cooldownMs) {
  const last = (p.closed || []).find((t) => t.symbol === symbol);
  return !!last && (Date.now() - last.closed) < cooldownMs;
}

function paperStats(p) {
  const closed = p.closed || [];
  const wins = closed.filter((t) => t.pnl > 0).length;
  return {
    trades: closed.length,
    wins,
    losses: closed.length - wins,
    winRate: closed.length ? Math.round((wins / closed.length) * 100) : null,
    equity: paperEquity(p),
    pnl: p.realized,
    openCount: Object.keys(p.open || {}).length,
  };
}

/* ------------------------------------------------------------ the loop */

async function paperValidate(showToast) {
  const box = $("#paperRules");
  const out = $("#paperValidation");
  let doc;
  try {
    doc = JSON.parse(box.value);
  } catch (err) {
    out.className = "paper-validation bad";
    out.textContent = "Not valid JSON: " + err.message;
    return null;
  }
  try {
    const r = await fetch("/api/strategy/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy: doc }),
    });
    const d = await r.json();
    if (d.ok) {
      out.className = "paper-validation ok";
      out.textContent = "Valid. These are the rules that will trade.";
      const p = getPaper();
      p.strategy = doc;
      savePaper(p);
      if (showToast && typeof toast === "function") toast("buy", "Rules saved", doc.name || "");
      return doc;
    }
    out.className = "paper-validation bad";
    out.innerHTML = "<b>Fix these first:</b><br>" +
      d.problems.map((x) => "· " + esc(x)).join("<br>");
    return null;
  } catch (err) {
    out.className = "paper-validation bad";
    out.textContent = "Couldn't reach the validator.";
    return null;
  }
}

async function paperTick() {
  if (paperBusy) return;               // never overlap two runs
  const p = getPaper();
  if (!p.running || !p.strategy) return;
  paperBusy = true;
  try {
    // Send what we hold so the server knows to look for exits, not entries.
    const openEntries = {};
    for (const [sym, pos] of Object.entries(p.open || {})) openEntries[sym] = pos.entry;

    const r = await fetch("/api/paper/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy: p.strategy, open: openEntries }),
    });
    const d = await r.json();
    if (d.error) {
      p.lastError = d.error;
      savePaper(p);
      renderPaper();
      return;
    }
    p.lastError = "";

    const sizing = (p.strategy.sizing || {});
    const notional = Number(sizing.notional) || 50;
    const maxOpen = Number(sizing.max_open) || 3;
    const cooldownMs = Math.max(0, Number(sizing.cooldown_min) || 0) * 60000;

    for (const dec of d.decisions || []) {
      const sym = String(dec.symbol || "").toUpperCase();
      if (!sym || dec.price == null) continue;

      if (dec.exit && p.open[sym]) {
        const pos = p.open[sym];
        const fill = paperFill(dec.price, pos.kind, "sell");
        const pnl = (fill - pos.entry) * pos.qty;
        p.realized += pnl;
        p.closed.unshift({
          symbol: sym, kind: pos.kind, qty: pos.qty,
          entry: pos.entry, exit: fill, pnl,
          why: dec.why || "exit rule", opened: pos.ts, closed: Date.now(),
        });
        delete p.open[sym];
        if (typeof toast === "function") {
          toast(pnl >= 0 ? "buy" : "sell", `Paper close · ${sym}`,
                `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} · ${dec.why || ""}`);
        }
      } else if (dec.entry && !p.open[sym]) {
        if (Object.keys(p.open).length >= maxOpen) continue;
        // Don't re-enter a symbol we just exited. Without this, a rule that is
        // broadly true re-buys on the very next tick after a stop — which is
        // revenge trading with extra steps, and it turns a paper record into
        // noise. Off by default; set sizing.cooldown_min to use it.
        if (cooldownMs && paperCooledDown(p, sym, cooldownMs)) continue;
        const fill = paperFill(dec.price, dec.kind, "buy");
        if (!fill) continue;
        p.open[sym] = {
          symbol: sym, kind: dec.kind, entry: fill,
          qty: notional / fill, notional, ts: Date.now(),
        };
        if (typeof toast === "function") {
          toast("buy", `Paper open · ${sym}`, `${notional} at ${fmtPrice(fill)}`);
        }
      }
    }
    p.lastRun = Date.now();
    savePaper(p);
    renderPaper();
  } catch (err) {
    // A transient network blip must not stop the run.
  } finally {
    paperBusy = false;
  }
}

function startPaper() {
  stopPaper();
  paperTimer = setInterval(paperTick, PAPER_POLL_MS);
  paperTick();
}

function stopPaper() {
  if (paperTimer) clearInterval(paperTimer);
  paperTimer = null;
}

async function togglePaperRun() {
  const p = getPaper();
  if (p.running) {
    p.running = false;
    savePaper(p);
    stopPaper();
    renderPaper();
    return;
  }
  const doc = await paperValidate(false);
  if (!doc) return;                    // never start on rules that don't validate
  const fresh = getPaper();
  fresh.running = true;
  fresh.startedAt = fresh.startedAt || Date.now();
  savePaper(fresh);
  startPaper();
  renderPaper();
}

function resetPaper() {
  if (!confirm("Clear the whole paper record — positions, trades and P&L?")) return;
  const p = getPaper();
  const keep = p.strategy;
  const fresh = paperDefaults();
  fresh.strategy = keep;               // keep their rules, drop the results
  savePaper(fresh);
  stopPaper();
  renderPaper();
}

/* ---------------------------------------------------------- rendering */

function paperMoney(v) {
  const sign = v < 0 ? "-" : "";
  return sign + "$" + Math.abs(v).toFixed(2);
}

function renderPaper() {
  const p = getPaper();
  const s = paperStats(p);

  const btn = $("#paperRunBtn");
  if (btn) {
    btn.textContent = p.running ? "■ Stop paper run" : "▶ Start paper run";
    btn.className = "ltc-tool" + (p.running ? " is-active" : "");
  }
  const status = $("#paperStatus");
  if (status) {
    status.textContent = p.lastError
      ? p.lastError
      : p.running
        ? (p.lastRun ? `running · last check ${new Date(p.lastRun).toLocaleTimeString()}` : "running · first check…")
        : "stopped";
    status.className = "paper-status" + (p.lastError ? " bad" : p.running ? " live" : "");
  }

  const stats = $("#paperStats");
  if (stats) {
    stats.innerHTML =
      `<div class="pst"><span>Equity</span><b>${paperMoney(s.equity)}</b></div>` +
      `<div class="pst"><span>P&amp;L</span><b class="${s.pnl >= 0 ? "up" : "down"}">${paperMoney(s.pnl)}</b></div>` +
      `<div class="pst"><span>Trades</span><b>${s.trades}</b></div>` +
      `<div class="pst"><span>Win rate</span><b>${s.winRate == null ? "—" : s.winRate + "%"}</b></div>` +
      `<div class="pst"><span>Open</span><b>${s.openCount}</b></div>`;
  }

  const openBox = $("#paperOpen");
  if (openBox) {
    const rows = Object.values(p.open || {});
    openBox.innerHTML = rows.length
      ? rows.map((pos) =>
          `<div class="paper-row"><b>${esc(pos.symbol)}</b>
             <span>${(pos.qty).toFixed(4)} @ ${fmtPrice(pos.entry)}</span>
             <span class="muted">${paperMoney(pos.notional)}</span></div>`).join("")
      : `<div class="proof-empty">No open paper positions.</div>`;
  }

  const closedBox = $("#paperClosed");
  if (closedBox) {
    const rows = (p.closed || []).slice(0, 25);
    closedBox.innerHTML = rows.length
      ? rows.map((t) =>
          `<div class="paper-row ${t.pnl >= 0 ? "win" : "loss"}">
             <b>${esc(t.symbol)}</b>
             <span>${fmtPrice(t.entry)} → ${fmtPrice(t.exit)}</span>
             <span class="${t.pnl >= 0 ? "up" : "down"}">${paperMoney(t.pnl)}</span>
             <span class="muted">${esc(t.why || "")}</span></div>`).join("")
      : `<div class="proof-empty">No closed trades yet. Most rules lose some — that's the point of paper.</div>`;
  }
}

function initPaper() {
  const box = $("#paperRules");
  if (!box || box.dataset.wired === "1") return;
  box.dataset.wired = "1";

  const p = getPaper();
  box.value = JSON.stringify(p.strategy || {
    name: "My rules (edit me)",
    kind: "stock",
    universe: ["TSLA", "NVDA", "MU"],
    entry: { all: [["squeeze_state", "==", "fired"], ["stack", "==", "bull"], ["rsi", "<", 70]] },
    exit: { any: [["label", "in", ["SELL", "STRONG SELL"]]], stop_loss_pct: 8, take_profit_pct: 15 },
    sizing: { notional: 50, max_open: 3 },
  }, null, 2);

  const v = $("#paperValidateBtn");
  if (v) v.addEventListener("click", () => paperValidate(true));
  const run = $("#paperRunBtn");
  if (run) run.addEventListener("click", togglePaperRun);
  const reset = $("#paperResetBtn");
  if (reset) reset.addEventListener("click", resetPaper);

  // Resume a run that was live when the tab was closed.
  if (p.running && p.strategy) startPaper();
  renderPaper();
}
