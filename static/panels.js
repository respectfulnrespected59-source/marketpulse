/* MarketPulse — options chain, pot tracker, and live tracker panels.
 *
 * The three trading panels that hang off the main grid.
 *
 * Split out of app.js to keep each file readable. Classic script, so it
 * shares one global scope with app.js and the other panels; everything
 * here is a declaration and nothing runs at load time. app.js is loaded
 * last because its init() call reaches into these.
 */

/* ----------------------------------------------------- options chain */

async function scanPot() {
  const pot = parseInt($("#optPot").value, 10) || 300;
  $("#optScan").innerHTML = `<div class="proof-empty">Scanning volatile low-dollar names + crypto for a $${pot} pot… (~20–40s, checks a basket live)</div>`;
  try {
    const d = await (await fetch(`/api/probe-scan?pot=${pot}`)).json();
    if (d.error) { $("#optScan").innerHTML = `<div class="proof-empty">Scan error: ${esc(d.error)}</div>`; return; }
    renderScan(d);
  } catch (e) {
    $("#optScan").innerHTML = `<div class="proof-empty">Scan error: ${esc(e.message)}</div>`;
  }
}

function renderScan(d) {
  const box = $("#optScan");
  const q = d.qualifiers || [], n = d.near || [], c = d.crypto || [];
  const dirTag = (dir) => dir === "call" ? `<span class="sc-dir bull">CALL ▲</span>`
    : dir === "put" ? `<span class="sc-dir bear">PUT ▼</span>` : `<span class="sc-dir">—</span>`;
  const qHtml = q.length ? q.map((r) => `<div class="scan-row ok" data-sym="${esc(r.symbol)}">
      <span class="sc-sym">${esc(r.symbol)}</span> ${dirTag(r.direction)}
      <span class="sc-cost">probe <b>$${r.probe_cost}</b></span>
      <span class="sc-meta">$${r.strike} · +${r.move_pct}% OTM · Δ${r.delta}</span>
    </div>`).join("")
    : `<div class="scan-empty">No basket names qualify at $${d.pot} right now (IVs are hot). Try a bigger pot, or the crypto spot probes below.</div>`;
  const nHtml = n.length ? `<div class="scan-sub">Close — would fit a bigger pot:</div>` + n.map((r) =>
    `<div class="scan-row near" data-sym="${esc(r.symbol)}"><span class="sc-sym">${esc(r.symbol)}</span>
      <span class="sc-meta">probe $${r.probe_cost} · needs ~$${r.min_pot} pot</span></div>`).join("") : "";
  const cHtml = c.length ? `<div class="scan-sub">₿ Crypto spot probes — buy $${d.budget} of the coin (fractional, always affordable), read the signal, escalate:</div>` +
    c.map((r) => `<div class="scan-row crypto"><span class="sc-sym">${esc(r.symbol)}</span>
      <span class="sc-dir ${r.dir === "long" ? "bull" : "bear"}">${r.dir === "long" ? "LONG ▲" : "SHORT ▼"}</span>
      <span class="sc-meta">${esc(r.label)} · ${fmtPrice(r.price)}</span></div>`).join("") : "";
  box.innerHTML = `<div class="scan">
    <div class="scan-head">🔍 Qualifies at a $${d.pot} pot — option probe ≤ $${d.budget} (scanned ${d.scanned})</div>
    ${qHtml}${nHtml}${cHtml}
    <div class="scan-note">Click a stock to load its chain + full plan. Probes are mostly losers — tiny risk is the point. Educational, not advice.</div>
  </div>`;
  box.querySelectorAll(".scan-row[data-sym]").forEach((el) =>
    el.addEventListener("click", () => { $("#optSymbol").value = el.dataset.sym; loadOptions(); }));
}

async function loadOptions(expiry) {
  const symbol = ($("#optSymbol").value.trim() || "TSLA").toUpperCase();
  $("#optScan").innerHTML = "";
  $("#optHint").innerHTML = "";
  $("#optTables").innerHTML = `<div class="proof-empty">Loading ${esc(symbol)} chain…</div>`;
  try {
    const qs = new URLSearchParams({ symbol });
    if (expiry) qs.set("expiry", expiry);
    const pot = parseInt($("#optPot").value, 10);
    if (pot > 0) qs.set("pot", pot);
    const d = await (await fetch(`/api/options?${qs}`)).json();
    if (d.error) {
      $("#optTables").innerHTML = `<div class="proof-empty">Couldn’t load ${esc(symbol)}: ${esc(d.error)}</div>`;
      return;
    }
    renderExpiries(d);
    renderChain(d);
  } catch (err) {
    $("#optTables").innerHTML = `<div class="proof-empty">Error: ${esc(err.message)}</div>`;
  }
}

function renderExpiries(d) {
  const sel = $("#optExpiry");
  sel.innerHTML = (d.expirations || []).map((e) => {
    const days = Math.round((new Date(e + "T16:00:00") - Date.now()) / 86400000);
    return `<option value="${esc(e)}" ${e === d.expiry ? "selected" : ""}>${esc(e)} (${days}d)</option>`;
  }).join("");
}

function renderProbe(pp) {
  // $-pot Probe → Read → Escalate sizer (scaled to the stock's price).
  const box = $("#optProbe");
  if (!pp) { box.innerHTML = ""; return; }
  const head = `<div class="probe-head">🎯 $${pp.pot} pot · Probe → Read → Escalate
    <span class="probe-bud">probe budget $${pp.budget} (20%)</span></div>`;
  if (pp.qualifies === null) {
    box.innerHTML = `<div class="probe none">${head}<div class="probe-line">${esc(pp.note)}</div></div>`;
    return;
  }
  if (!pp.qualifies) {
    const p = pp.probe;
    const detail = p
      ? `<div class="probe-line">Cheapest <i>usable</i> probe (Δ${pp.min_delta}, ${esc(pp.direction)}) = <b>$${p.cost}</b> —
           the $${p.strike} strike (+${p.move_pct}% OTM). That's ${(p.cost / pp.budget).toFixed(1)}× your $${pp.budget} budget.</div>
         <div class="probe-line">Probe this name responsibly and you'd need ~<b>$${pp.min_pot}</b> pot.
           Anything cheaper here is a dead lottery, not a read. <b>Walk — or load a cheaper name.</b></div>`
      : `<div class="probe-line">${esc(pp.note || "Doesn’t fit this pot.")}</div>`;
    box.innerHTML = `<div class="probe toorich">${head}
      <div class="probe-verdict bad">✋ Too rich for a $${pp.pot} pot</div>${detail}</div>`;
    return;
  }
  const p = pp.probe;
  const escHtml = pp.escalate
    ? `<div class="probe-step"><span class="ps esc">ESCALATE</span> on confirmation: 2× ~$${pp.escalate.cost_each}
         → $${pp.escalate.strike} (Δ${pp.escalate.delta}), closer-to-money. Total capped at $${pp.pot}.</div>`
    : `<div class="probe-step"><span class="ps esc">ESCALATE</span> on confirmation, closer-to-money, from the
         remaining ~$${pp.pot - p.cost}. Cap total at $${pp.pot}.</div>`;
  box.innerHTML = `<div class="probe ok">${head}
    <div class="probe-verdict good">✓ Qualifies — most affordable usable probe</div>
    <div class="probe-step"><span class="ps">PROBE</span> <b>$${p.cost}</b>: buy the $${p.strike} ${esc(pp.direction)}
      (Δ${p.delta}, +${p.move_pct}% OTM, ~1wk). The cheapest read that still moves.</div>
    <div class="probe-step"><span class="ps">READ</span> rising → escalate same way · cratering → <b>FLIP</b> to the other side.</div>
    ${escHtml}
    <div class="probe-note">Single directional option = <b>no straddle</b>. Cap $${pp.pot}. Never revenge-size a melter.</div></div>`;
}

function renderNudge(n) {
  const box = $("#optNudge");
  if (!n) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="nudge ${esc(n.dir)}">
    <span class="nudge-ic">${n.icon || ""}</span>
    <span class="nudge-body"><b>${esc(n.headline || "")}</b> ${esc(n.text || "")}</span>
  </div>`;
}

function renderStrategy(d) {
  const box = $("#optStrategy");
  const cards = [];

  // Strangle — when a TTM squeeze is coiled (either-way). Shown first.
  if (d.strangle) {
    const s = d.strangle;
    const hdr = d.either_way
      ? "coiled · direction unresolved → LONG STRANGLE (either way)"
      : "squeeze on → LONG STRANGLE available (either way)";
    cards.push(`<div class="strat either">
      <div class="strat-title"><b>⟁ ${hdr}</b></div>
      <div class="strat-legs">
        <span class="leg long">BUY CALL ${fmtPrice(s.call.strike)} <i>${(+s.call.delta).toFixed(2)}Δ</i></span>
        <span class="leg long">BUY PUT ${fmtPrice(s.put.strike)} <i>${(+s.put.delta).toFixed(2)}Δ</i></span>
      </div>
      <div class="strat-math">
        <span>Debit <b>${fmtPrice(s.debit)}</b> <i>($${s.per_contract}/contract)</i></span>
        <span>Max loss <b>${fmtPrice(s.max_loss)}</b></span>
        <span>Up BE <b>${fmtPrice(s.upper_breakeven)}</b> <i>(+${s.move_up_pct}%)</i></span>
        <span>Down BE <b>${fmtPrice(s.lower_breakeven)}</b> <i>(−${s.move_down_pct}%)</i></span>
      </div>
      <div class="strat-note">Wins on a big move EITHER way; loses if it sits. You pay two premiums — price must clear a breakeven to profit. Mind earnings &amp; theta.</div>
    </div>`);
  }

  // Directional debit spread — when the signal leans a way.
  if (d.lean && d.lean.direction && d.spread) {
    const s = d.spread, dir = d.lean.direction === "call" ? "bull" : "bear";
    cards.push(`<div class="strat ${dir}">
      <div class="strat-title"><b>Signal ${esc(d.lean.label)} → ${esc(s.type.toUpperCase())}</b></div>
      <div class="strat-legs">
        <span class="leg long">BUY ${fmtPrice(s.long.strike)} <i>${(+s.long.delta).toFixed(2)}Δ</i></span>
        <span class="leg short">SELL ${fmtPrice(s.short.strike)} <i>${(+s.short.delta).toFixed(2)}Δ</i></span>
      </div>
      <div class="strat-math">
        <span>Debit <b>${fmtPrice(s.debit)}</b> <i>($${s.per_contract}/contract)</i></span>
        <span>Max profit <b>${fmtPrice(s.max_profit)}</b></span>
        <span>Max loss <b>${fmtPrice(s.max_loss)}</b></span>
        <span>Breakeven <b>${fmtPrice(s.breakeven)}</b></span>
        <span>R:R <b>${s.risk_reward ?? "—"}</b></span>
      </div>
      <div class="strat-note">Defined risk — worst case is the debit. Check earnings before this expiry. Educational, not advice.</div>
    </div>`);
  }

  if (!cards.length) {
    if (d.lean && !d.lean.direction) {
      cards.push(`<div class="strat neutral"><b>Signal: ${esc(d.lean.label)}</b> — no directional edge and no squeeze coil, so no clean structure right now.</div>`);
    } else if (d.lean && d.lean.direction && !d.spread) {
      const dir = d.lean.direction === "call" ? "bull" : "bear";
      cards.push(`<div class="strat ${dir}"><b>Signal ${esc(d.lean.label)} → ${d.lean.direction.toUpperCase()} debit spread</b> — couldn't build a clean spread on this expiry. Try another date.</div>`);
    } else { box.innerHTML = ""; return; }
  }
  box.innerHTML = cards.join("");
}

function renderRead(read) {
  const box = $("#optRead");
  if (!read) { box.innerHTML = ""; return; }
  const steps = read.steps.map((s) =>
    `<div class="read-step"><span class="rk">${esc(s.k)}</span><span class="rv">${esc(s.v)}</span></div>`).join("");
  const risk = read.risk.map((r) => `<li>${esc(r)}</li>`).join("");
  box.innerHTML =
    `<div class="read-head">📖 How to read this — &amp; think about your money</div>${steps}` +
    `<div class="read-bottom">${esc(read.bottom_line)}</div>` +
    `<div class="read-risk"><div class="rr-title">Risk rules — non-negotiable</div><ul>${risk}</ul></div>` +
    `<div class="read-disc">${esc(read.disclaimer)}</div>`;
}

function renderChain(d) {
  renderNudge(d.nudge);
  renderStrategy(d);
  renderProbe(d.probe_plan);
  renderRead(d.read);
  const spot = d.spot;
  const sp = d.spread;
  const dir = d.lean && d.lean.direction;  // 'call' | 'put' | null
  // Per-side maps of strike -> leg role, covering BOTH the directional spread
  // and (if coiled) the strangle's call + put legs.
  const callLegs = {}, putLegs = {};
  if (sp && dir === "call") { callLegs[sp.long.strike] = "long"; callLegs[sp.short.strike] = "short"; }
  if (sp && dir === "put") { putLegs[sp.long.strike] = "long"; putLegs[sp.short.strike] = "short"; }
  if (d.strangle) { callLegs[d.strangle.call.strike] = "long"; putLegs[d.strangle.put.strike] = "long"; }
  const strikes = d.calls.map((c) => c.strike);
  let atm = 0, best = Infinity;
  strikes.forEach((s, i) => { const diff = Math.abs(s - spot); if (diff < best) { best = diff; atm = i; } });
  const lo = Math.max(0, atm - 12), hi = Math.min(d.calls.length, atm + 13);
  const atmIV = d.calls[atm] ? d.calls[atm].iv : null;

  $("#optHint").innerHTML =
    `<span>${esc(d.symbol)} spot <b>${fmtPrice(spot)}</b></span>` +
    `<span>${d.dte} DTE · exp ${esc(d.expiry)}</span>` +
    `<span>ATM IV <b>${atmIV != null ? atmIV + "%" : "—"}</b></span>` +
    `<span class="opt-note">Bid/Ask = real $ to trade ONE contract (premium × 100 shares)</span>` +
    `<span class="opt-note">Greeks: Δ delta · Γ gamma · Θ theta/day · V vega · ${esc(d.source || "delayed")}</span>`;

  const num = (v, d2 = 2) => (v == null ? "—" : (+v).toFixed(d2));
  // One contract = 100 shares, so the real $ to trade it = premium × 100.
  // Show that dollar amount so newcomers grok the cost at a glance.
  const dollars = (v) => (v == null ? "—" : "$" + Math.round(v * 100).toLocaleString());
  const row = (o, side) => {
    if (!o) return "";
    const isAtm = Math.abs(o.strike - spot) === best;
    const map = side === "call" ? callLegs : putLegs;
    const leg = map[o.strike] ? "leg-" + map[o.strike] : "";
    const cls = `${isAtm ? "atm" : ""} ${o.itm ? "itm" : ""} ${leg}`;
    return `<tr class="${cls}">
      <td class="k">${fmtPrice(o.strike)}</td>
      <td class="ba" title="${num(o.bid)} / ${num(o.ask)} per share">${dollars(o.bid)} / ${dollars(o.ask)}</td>
      <td>${o.iv != null ? o.iv : "—"}</td>
      <td>${num(o.delta, 2)}</td>
      <td>${num(o.gamma, 3)}</td>
      <td>${num(o.theta, 2)}</td>
      <td>${num(o.vega, 2)}</td>
      <td>${o.oi != null ? o.oi : "—"}</td>
    </tr>`;
  };
  const head = `<tr><th>Strike</th><th>Bid/Ask $/ct</th><th>IV%</th><th>Δ</th><th>Γ</th><th>Θ</th><th>V</th><th>OI</th></tr>`;
  const table = (rows) => `<table class="opt-table"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  $("#optTables").innerHTML =
    `<div class="opt-side"><h4 class="opt-h call">CALLS</h4>${table(d.calls.slice(lo, hi).map((o) => row(o, "call")).join(""))}</div>` +
    `<div class="opt-side"><h4 class="opt-h put">PUTS</h4>${table(d.puts.slice(lo, hi).map((o) => row(o, "put")).join(""))}</div>`;
}

/* ----------------------------------------------------- pot tracker */

const potMoney = (v) => (v < 0 ? "-$" : "$") + Math.abs(Math.round(v)).toLocaleString();

function getPot() { return store.get("mp_pot", { start: 300, probes: [] }); }
function savePot(p) { store.set("mp_pot", p); }

// QuickFill for the probe cost — its readout shows % of pot + a budget warning.
let potCostQf = null;
function ensurePotQf() {
  if (potCostQf || typeof QuickFill === "undefined") return;
  const el = $("#potCostQf");
  if (!el) return;
  potCostQf = QuickFill.mount(el, {
    amount: 50, chips: [25, 50, 100, 200], step: 5, min: 1,
    convert: (amt) => {
      const s = potCompute(getPot());
      const pct = s.equity ? (amt / s.equity * 100) : 0;
      const over = amt > s.budget;
      return `<span class="${over ? "qf-over" : ""}">$${Math.round(amt)} = ${pct.toFixed(1)}% of your ` +
        `$${Math.round(s.equity)} pot` +
        (over ? ` · over your $${s.budget} probe budget` : ` · budget $${s.budget}`) + `</span>`;
    },
  });
}

function potCompute(p) {
  let openCost = 0, closedCost = 0, rets = 0, closed = 0, wins = 0;
  for (const x of p.probes) {
    if (x.status === "open") { openCost += x.cost; }
    else { closed++; closedCost += x.cost; rets += (x.ret || 0); if ((x.ret || 0) - x.cost > 0) wins++; }
  }
  const realized = rets - closedCost;
  const equity = p.start + realized;     // open probes carried at cost
  return { openCost, realized, equity, closed, wins,
           open: p.probes.filter((x) => x.status === "open").length,
           winRate: closed ? Math.round((wins / closed) * 100) : null,
           budget: Math.max(0, Math.round(equity * 0.20)) };
}

function renderPot() {
  const p = getPot();
  const s = potCompute(p);
  const now = $("#potNow");
  now.textContent = potMoney(s.equity);
  now.className = "pot-now-val " + (s.realized > 0 ? "up" : s.realized < 0 ? "down" : "");
  $("#potStats").innerHTML =
    `<div class="pst"><span>Realized P/L</span><b class="${s.realized >= 0 ? "up" : "down"}">${potMoney(s.realized)}</b></div>` +
    `<div class="pst"><span>Start</span><b>${potMoney(p.start)}</b></div>` +
    `<div class="pst"><span>Open</span><b>${s.open} · $${s.openCost} at risk</b></div>` +
    `<div class="pst"><span>Win rate</span><b>${s.winRate == null ? "—" : s.winRate + "%"} (${s.wins}/${s.closed})</b></div>` +
    `<div class="pst"><span>Next probe ≤</span><b>$${s.budget} (20%)</b></div>`;
  const rows = p.probes.slice().reverse().map((x) => {
    const dir = x.dir === "call" ? "CALL ▲" : x.dir === "put" ? "PUT ▼" : "LONG ▲";
    const dc = x.dir === "put" ? "bear" : "bull";
    if (x.status === "open") {
      return `<div class="pot-row open" data-id="${esc(x.id)}">
        <span class="pr-sym">${esc(x.sym)}</span><span class="sc-dir ${dc}">${dir}</span>
        <span class="pr-cost">$${x.cost}</span>
        <span class="pr-close">close $<input class="pr-ret" type="number" step="1" placeholder="got back" />
          <button class="pr-win" type="button">✓</button>
          <button class="pr-loss" type="button" title="total loss">✗ zero</button></span>
        <button class="pr-del" type="button" title="delete">🗑</button></div>`;
    }
    const pl = (x.ret || 0) - x.cost;
    return `<div class="pot-row closed" data-id="${esc(x.id)}">
      <span class="pr-sym">${esc(x.sym)}</span><span class="sc-dir ${dc}">${dir}</span>
      <span class="pr-cost">$${x.cost} → $${x.ret || 0}</span>
      <span class="pr-pl ${pl >= 0 ? "up" : "down"}">${potMoney(pl)}</span>
      <button class="pr-del" type="button" title="delete">🗑</button></div>`;
  }).join("");
  $("#potList").innerHTML = rows ||
    `<div class="scan-empty">No probes logged yet. Log your first $${s.budget}-or-less probe above — small enough to be wrong cheaply.</div>`;
  $("#potStart").value = p.start;
  $("#potList").querySelectorAll(".pot-row").forEach((el) => {
    const id = el.dataset.id;
    el.querySelector(".pr-del")?.addEventListener("click", () => removeProbe(id));
    el.querySelector(".pr-win")?.addEventListener("click", () =>
      closeProbe(id, parseFloat(el.querySelector(".pr-ret").value) || 0));
    el.querySelector(".pr-loss")?.addEventListener("click", () => closeProbe(id, 0));
  });
  if (potCostQf) potCostQf.refreshConversion();   // pot equity changed -> update % readout
}

function logProbe() {
  const sym = $("#potSym").value.trim().toUpperCase();
  const cost = Math.round(potCostQf ? potCostQf.getAmount() : 0);
  if (!sym || !(cost > 0)) return;
  const p = getPot();
  const s = potCompute(p);
  $("#potWarn").innerHTML = cost > s.budget
    ? `<div class="warn">⚠ $${cost} is over your $${s.budget} probe budget (20% of pot). That's bigger than a probe — size down, or it's not the method.</div>`
    : "";
  p.probes.push({ id: "p" + Date.now(), date: new Date().toISOString().slice(0, 10),
                  sym, dir: $("#potDir").value, cost, status: "open", ret: 0 });
  savePot(p);
  $("#potSym").value = "";
  renderPot();   // re-renders + refreshes the QuickFill % readout
}

function closeProbe(id, ret) {
  const p = getPot();
  const x = p.probes.find((y) => y.id === id);
  if (!x) return;
  x.status = "closed"; x.ret = Math.max(0, Math.round(ret) || 0);
  savePot(p); renderPot();
}
function removeProbe(id) {
  const p = getPot();
  p.probes = p.probes.filter((y) => y.id !== id);
  savePot(p); renderPot();
}
function setPotStart(v) {
  const p = getPot(); const n = Math.round(parseFloat(v));
  if (n > 0) { p.start = n; savePot(p); renderPot(); }
}
function resetPot() {
  if (!confirm("Reset the pot and clear all logged probes?")) return;
  savePot({ start: Math.round(parseFloat($("#potStart").value)) || 300, probes: [] });
  renderPot();
}

/* ----------------------------------------------------- live tracker */

// Same honest cost model as backtest.py (per-side bps): stocks 0 comm / 5bps
// slip, crypto 25bps comm / 20bps slip. Round-trip cost is subtracted from the
// directional move so the P&L is what you'd realistically KEEP, not a fantasy.
const LIVE_BPS = { stock: { comm: 0, slip: 0.0005 }, crypto: { comm: 0.0025, slip: 0.0020 } };
const LIVE_SIDE = {
  long: { label: "LONG / DCA", cls: "bull" },
  call: { label: "CALL lean ▲", cls: "bull" },
  put: { label: "PUT lean ▼", cls: "bear" },
};

let liveTimer = null, liveClock = null;

function getLive() { return store.get("mp_livetrack", null); }
function saveLive(p) { store.set("mp_livetrack", p); }

/* =============== Sprint 3: Cockpit home + saved DCA plans + backup =========== */
function getDcaPlans() { return store.get("mp_dca_plans", []); }
function saveDcaPlans(a) { store.set("mp_dca_plans", a); }
const PER_YEAR = { weekly: 52, biweekly: 26, monthly: 12 };

function renderHome() {
  // Pot card
  const s = potCompute(getPot());
  $("#homePot").innerHTML =
    `<div class="hc-head">🫙 Pot <a class="hc-link" data-goto="pot">open →</a></div>` +
    `<div class="hc-big ${s.realized > 0 ? "up" : s.realized < 0 ? "down" : ""}">${potMoney(s.equity)}</div>` +
    `<div class="hc-sub">realized ${potMoney(s.realized)} · ${s.open} open ($${s.openCost} at risk)</div>` +
    `<div class="hc-sub">win ${s.winRate == null ? "—" : s.winRate + "%"} · next probe ≤ <b>$${s.budget}</b></div>`;

  // Live play card
  const p = getLive();
  if (!p) {
    $("#homeLive").innerHTML =
      `<div class="hc-head">🔴 Live play <a class="hc-link" data-goto="live">open →</a></div>` +
      `<div class="hc-empty">No active play. Pin one to track it live.</div>`;
  } else {
    const price = p.current ?? p.entry;
    const r = livePnl(p, price);
    const cls = r.netUsd > 0 ? "up" : r.netUsd < 0 ? "down" : "";
    const side = (LIVE_SIDE[p.side] || LIVE_SIDE.long).label;
    const liveSym = p.kind === "crypto" ? String(p.sym).toLowerCase() : p.sym;
    $("#homeLive").innerHTML =
      `<div class="hc-head">🔴 Live play <a class="hc-link" data-goto="live">open →</a></div>` +
      `<div class="hc-big ${cls}"><span class="sym-tap" role="button" tabindex="0"
          data-live-kind="${esc(p.kind)}" data-live-sym="${esc(liveSym)}"
          title="Open ${esc(p.sym)} live chart">${esc(p.sym)}</span> ${r.netUsd >= 0 ? "+" : "-"}$${Math.abs(r.netUsd).toFixed(2)}</div>` +
      `<div class="hc-sub">${esc(side)} · $${p.stake} stake · ${esc(p.status)}</div>` +
      `<div class="hc-sub">entry ${fmtPrice(p.entry)} → ${fmtPrice(price)} (${r.netPct >= 0 ? "+" : ""}${r.netPct.toFixed(2)}%)</div>`;
  }
  renderHomePlans();
  renderHomeState();
  renderOnboard();
}

