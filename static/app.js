/* MarketPulse front-end — vanilla JS, no framework.
   State (watchlist, alerts, custom symbols) persists in localStorage. */

const $ = (sel) => document.querySelector(sel);
const grid = $("#grid");

const store = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
    catch { return fallback; }
  },
  set(key, val) { localStorage.setItem(key, JSON.stringify(val)); },
};

const state = {
  view: "crypto",
  cryptoIds: store.get("mp_crypto_ids", null),   // null => use server defaults
  stockSyms: store.get("mp_stock_syms", null),
  watch: new Set(store.get("mp_watch", [])),      // "CRYPTO:BTC"
  alerts: store.get("mp_alerts", {}),             // { "CRYPTO:BTC": [{dir,price}] }
  lastPrice: {},                                  // for flash + alert crossing
  rows: [],
  timer: null,
};

const keyOf = (r) => `${r.kind.toUpperCase()}:${r.symbol}`;

// Escape external strings (coin/stock names) before injecting into HTML.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ----------------------------------------------------- data */

async function getMarkets(type, symbols) {
  const qs = new URLSearchParams({ type });
  if (symbols && symbols.length) qs.set("symbols", symbols.join(","));
  const res = await fetch(`/api/markets?${qs}`);
  if (!res.ok) throw new Error((await res.json()).error || res.statusText);
  return (await res.json()).rows || [];
}

async function loadView() {
  setStatus("Fetching live data…");
  $("#refreshBtn").classList.add("spin");
  try {
    let rows = [];
    if (state.view === "crypto") {
      rows = await getMarkets("crypto", state.cryptoIds);
    } else if (state.view === "stocks") {
      rows = await getMarkets("stocks", state.stockSyms);
    } else {
      const [c, s] = await Promise.all([
        getMarkets("crypto", state.cryptoIds),
        getMarkets("stocks", state.stockSyms),
      ]);
      rows = [...c, ...s].filter((r) => state.watch.has(keyOf(r)));
    }
    state.rows = rows;
    checkAlerts(rows);
    render(rows);
    setStatus(`Updated ${new Date().toLocaleTimeString()} · ${rows.length} assets`);
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  } finally {
    $("#refreshBtn").classList.remove("spin");
  }
}

/* ----------------------------------------------------- render */

function render(rows) {
  updateBreadth(rows);
  grid.innerHTML = "";
  if (!rows.length) {
    const msg = state.view === "watchlist"
      ? "No starred assets yet. Tap ★ on any card to track it here."
      : "No data.";
    grid.innerHTML = `<div class="empty">${msg}</div>`;
    return;
  }
  for (const r of rows) grid.appendChild(card(r));
}

function card(r) {
  const el = document.createElement("article");
  el.className = "card";
  if (r.error) {
    el.classList.add("err");
    el.innerHTML = `<div class="card-top"><div><div class="sym">${esc(r.symbol)}</div>
      <div class="name">unavailable</div></div></div>`;
    return el;
  }

  const k = keyOf(r);
  const up = (r.change ?? 0) >= 0;
  const starred = state.watch.has(k);
  const hasAlert = (state.alerts[k] || []).length > 0;
  const sig = r.signal || { label: "NEUTRAL", css: "neutral", reasons: [] };

  // price flash vs last seen
  const prev = state.lastPrice[k];
  if (prev != null && r.price != null && r.price !== prev) {
    el.classList.add(r.price > prev ? "flash-up" : "flash-down");
  }
  state.lastPrice[k] = r.price;

  el.innerHTML = `
    <div class="card-top">
      <div>
        <div class="sym">${esc(r.symbol)}</div>
        <div class="name">${esc(r.name || "")}</div>
      </div>
      <div class="card-actions">
        <button class="icon-btn alert ${hasAlert ? "on" : ""}" title="Price alert">${hasAlert ? "🔔" : "🔕"}</button>
        <button class="icon-btn star ${starred ? "on" : ""}" title="Watchlist">${starred ? "★" : "☆"}</button>
      </div>
    </div>
    <div class="price-row">
      <span class="price">${fmtPrice(r.price)}</span>
      <span class="chg ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(r.change ?? 0).toFixed(2)}%</span>
    </div>
    ${sparkline(r.spark, up)}
    <div class="card-bottom">
      <span class="badge ${sig.css}">${sig.label}</span>
      <span class="meta">${sig.rsi != null ? "RSI " + sig.rsi : ""}</span>
    </div>
    <div class="reasons">${(sig.reasons || []).join(" · ")}</div>
    ${squeezeRow(r.squeeze)}
    ${guidesRow(r.guides)}
  `;

  el.querySelector(".star").addEventListener("click", () => toggleWatch(r));
  el.querySelector(".alert").addEventListener("click", () => openAlert(r));
  return el;
}

function guidesRow(g) {
  // 5/14/21 MA stack (daily) + intraday session VWAP. Stocks only.
  if (!g) return "";
  const stackWord = g.stack === "bull" ? "stacked ▲"
    : g.stack === "bear" ? "stacked ▼" : "mixed";
  const stackCls = g.stack === "bull" ? "bull" : g.stack === "bear" ? "bear" : "";
  const mas = `5 ${fmtPrice(g.ma5)} · 14 ${fmtPrice(g.ma14)} · 21 ${fmtPrice(g.ma21)}`;
  let vw;
  if (g.vwap != null) {
    const cls = g.vs_vwap === "above" ? "bull" : "bear";
    const ar = g.vs_vwap === "above" ? "▲" : "▼";
    vw = `<span class="g vwap ${cls}" title="Session VWAP ${fmtPrice(g.vwap)} — price ${esc(g.vs_vwap)}">VWAP <b>${ar}</b></span>`;
  } else {
    vw = `<span class="g vwap na" title="No intraday VWAP (market closed / no data)">VWAP —</span>`;
  }
  return `<div class="guides"><span class="g ma ${stackCls}" title="${mas}">MA 5/14/21 ${stackWord}</span>${vw}</div>`;
}

function squeezeRow(sq) {
  // Weekly + bi-weekly TTM squeeze chips. Crypto rows have no squeeze => skip.
  if (!sq) return "";
  const cell = (tf, d) => {
    if (!d) return `<span class="sqz na">${tf}&nbsp;—</span>`;
    const arrow = d.mom === "bull"
      ? (d.accel === "rising" ? "▲" : "△")
      : (d.accel === "falling" ? "▼" : "▽");
    const txt = d.state === "on" ? `ON·${d.bars}` : d.state === "fired" ? "FIRED" : "off";
    return `<span class="sqz ${esc(d.state)} ${esc(d.mom)}" title="${tf} TTM squeeze ${esc(d.state)} · momentum ${esc(d.mom)} ${esc(d.accel)}">${tf} ${txt} <b>${arrow}</b></span>`;
  };
  return `<div class="squeeze"><span class="sqz-lbl">TTM</span>${cell("W", sq.weekly)}${cell("2W", sq.biweekly)}</div>`;
}

function sparkline(values, up) {
  if (!values || values.length < 2) return `<div class="spark"></div>`;
  const w = 100, h = 40, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = pad + (1 - (v - min) / span) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = up ? "var(--buy)" : "var(--sell)";
  const area = `${pad},${h} ${pts.join(" ")} ${w - pad},${h}`;
  const gid = "g" + Math.random().toString(36).slice(2, 8);
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon points="${area}" fill="url(#${gid})"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.5"
      stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

function updateBreadth(rows) {
  let b = 0, n = 0, s = 0;
  for (const r of rows) {
    const sc = r.signal ? r.signal.score : 0;
    if (sc > 0) b++; else if (sc < 0) s++; else n++;
  }
  $("#cntBuy").textContent = b;
  $("#cntNeutral").textContent = n;
  $("#cntSell").textContent = s;
  $("#watchCount").textContent = state.watch.size;
}

const setStatus = (t) => { $("#status").textContent = t; };

function fmtPrice(p) {
  if (p == null) return "—";
  if (p >= 1000) return "$" + p.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (p >= 1) return "$" + p.toFixed(2);
  return "$" + p.toFixed(p >= 0.01 ? 4 : 6);
}

/* ----------------------------------------------------- watchlist */

function toggleWatch(r) {
  const k = keyOf(r);
  if (state.watch.has(k)) state.watch.delete(k); else state.watch.add(k);
  store.set("mp_watch", [...state.watch]);
  if (state.view === "watchlist") loadView(); else render(state.rows);
}

/* ----------------------------------------------------- alerts */

let alertTarget = null;

function openAlert(r) {
  if (!features.alerts) { openUpgrade(); return; }
  alertTarget = r;
  const k = keyOf(r);
  $("#alertTitle").textContent = `Alert · ${r.symbol}`;
  $("#alertSub").textContent = `Current price ${fmtPrice(r.price)}`;
  $("#alertPrice").value = "";
  renderExistingAlerts(k);
  $("#alertModal").hidden = false;
}

function renderExistingAlerts(k) {
  const box = $("#alertExisting");
  const list = state.alerts[k] || [];
  box.innerHTML = list.map((a, i) =>
    `<div class="alert-chip">${a.dir === "above" ? "▲ above" : "▼ below"} ${fmtPrice(a.price)}
     <button data-i="${i}">✕</button></div>`).join("");
  box.querySelectorAll("button").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.alerts[k].splice(+btn.dataset.i, 1);
      if (!state.alerts[k].length) delete state.alerts[k];
      store.set("mp_alerts", state.alerts);
      renderExistingAlerts(k);
      render(state.rows);
    }));
}

function saveAlert() {
  if (!alertTarget) return;
  const price = parseFloat($("#alertPrice").value);
  if (!isFinite(price)) return;
  const k = keyOf(alertTarget);
  (state.alerts[k] ||= []).push({ dir: $("#alertDir").value, price });
  store.set("mp_alerts", state.alerts);
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  $("#alertModal").hidden = true;
  render(state.rows);
  toast("buy", `Alert set · ${alertTarget.symbol}`, `${$("#alertDir").value} ${fmtPrice(price)}`);
}

function checkAlerts(rows) {
  for (const r of rows) {
    const k = keyOf(r);
    const list = state.alerts[k];
    if (!list || r.price == null) continue;
    const remaining = [];
    for (const a of list) {
      const hit = (a.dir === "above" && r.price >= a.price) ||
                  (a.dir === "below" && r.price <= a.price);
      if (hit) fireAlert(r, a); else remaining.push(a);
    }
    if (remaining.length) state.alerts[k] = remaining; else delete state.alerts[k];
  }
  store.set("mp_alerts", state.alerts);
}

function fireAlert(r, a) {
  const msg = `${r.symbol} ${a.dir === "above" ? "rose above" : "dropped below"} ${fmtPrice(a.price)}`;
  toast(a.dir === "above" ? "buy" : "sell", `🔔 ${r.symbol} alert`, msg + ` · now ${fmtPrice(r.price)}`);
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification("MarketPulse alert", { body: msg });
  }
}

function toast(kind, title, body) {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.innerHTML = `<b>${title}</b><span>${body}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 7000);
}

/* ----------------------------------------------------- add symbol */

function addSymbol(raw) {
  const v = raw.trim();
  if (!v) return;
  const looksLikeTicker = /^[A-Za-z.\-]{1,6}$/.test(v) && v === v.toUpperCase();
  if (state.view === "stocks" || (state.view === "watchlist" && looksLikeTicker)) {
    const sym = v.toUpperCase();
    state.stockSyms = [...new Set([...(state.stockSyms || defaults.stocks), sym])];
    store.set("mp_stock_syms", state.stockSyms);
  } else {
    const id = v.toLowerCase();
    state.cryptoIds = [...new Set([...(state.cryptoIds || defaults.crypto), id])];
    store.set("mp_crypto_ids", state.cryptoIds);
  }
  loadView();
}

/* ----------------------------------------------------- wiring */

let defaults = { crypto: [], stocks: [] };
let features = { proof: true, alerts: true, unlimited_symbols: true };
let upgradeUrl = "https://quantummelaninmedia.gumroad.com";

function openUpgrade() {
  toast("buy", "Pro feature 🔒", "Opening upgrade page…");
  window.open(upgradeUrl, "_blank");
}

function applyGating() {
  // Hide Proof tab in the free build.
  const proofTab = document.querySelector('.tab[data-view="proof"]');
  if (proofTab) proofTab.style.display = features.proof ? "" : "none";
  // Upgrade banner for the free build.
  if (!features.proof || !features.alerts) {
    const bar = document.createElement("div");
    bar.className = "upgrade-bar";
    bar.innerHTML = `🔒 Free edition — Proof Mode, price alerts & unlimited symbols are in
      <b>Pro</b>. <a href="${upgradeUrl}" target="_blank">Unlock Pro →</a>`;
    document.querySelector(".controls").appendChild(bar);
  }
}

let proofLoaded = false;
let optionsLoaded = false;

function setView(v) {
  state.view = v;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.view === v));

  const isProof = v === "proof";
  const isOpt = v === "options";
  const isPot = v === "pot";
  const isPanel = isProof || isOpt || isPot;
  $("#proofPanel").hidden = !isProof;
  $("#optionsPanel").hidden = !isOpt;
  $("#potPanel").hidden = !isPot;
  $("#grid").hidden = isPanel;
  document.querySelector(".controls").hidden = isPanel;
  document.querySelector(".breadth").hidden = isPanel;
  if (isProof) {
    if (!proofLoaded) { proofLoaded = true; runProof(); }
    return;
  }
  if (isOpt) {
    if (!optionsLoaded) { optionsLoaded = true; loadOptions(); }
    return;
  }
  if (isPot) { renderPot(); return; }

  $("#addInput").placeholder = v === "stocks"
    ? "Add stock ticker (e.g. NVDA)…"
    : v === "crypto" ? "Add coin id (e.g. solana)…" : "Add ticker or coin id…";
  loadView();
}

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
}

function logProbe() {
  const sym = $("#potSym").value.trim().toUpperCase();
  const cost = Math.round(parseFloat($("#potCost").value));
  if (!sym || !(cost > 0)) return;
  const p = getPot();
  const s = potCompute(p);
  $("#potWarn").innerHTML = cost > s.budget
    ? `<div class="warn">⚠ $${cost} is over your $${s.budget} probe budget (20% of pot). That's bigger than a probe — size down, or it's not the method.</div>`
    : "";
  p.probes.push({ id: "p" + Date.now(), date: new Date().toISOString().slice(0, 10),
                  sym, dir: $("#potDir").value, cost, status: "open", ret: 0 });
  savePot(p);
  $("#potSym").value = ""; $("#potCost").value = "";
  renderPot();
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

/* ----------------------------------------------------- proof mode */

async function runProof() {
  const symbol = $("#proofSymbol").value.trim();
  const kind = $("#proofKind").value;
  if (!symbol) return;
  $("#proofStats").innerHTML = `<div class="proof-empty">Running the engine over history…</div>`;
  $("#proofEvents").innerHTML = "";
  $("#proofChart").innerHTML = "";
  try {
    const res = await fetch(`/api/proof?symbol=${encodeURIComponent(symbol)}&kind=${kind}`);
    const d = await res.json();
    if (d.error) {
      $("#proofStats").innerHTML = `<div class="proof-empty">Couldn’t backtest ${esc(symbol)}: ${esc(d.error)}</div>`;
      return;
    }
    renderProof(d);
  } catch (err) {
    $("#proofStats").innerHTML = `<div class="proof-empty">Error: ${esc(err.message)}</div>`;
  }
}

function strategyCards(st) {
  const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);
  const cls = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
  if (!st || st.error) {
    return `<div class="stat" style="grid-column:1/-1"><div class="label">Strategy P&amp;L</div>
      <div class="val">—</div><div class="sub">${esc(st && st.error ? st.error : "unavailable")}</div></div>`;
  }
  const n = st.net;
  const hold = st.buy_hold_return_pct;
  return `
    <div class="stat"><div class="label">Strategy return (net)</div>
      <div class="val ${cls(n.return_pct)}">${pct(n.return_pct)}</div>
      <div class="sub">gross ${pct(st.gross_return_pct)} before costs</div></div>
    <div class="stat"><div class="label">vs Buy &amp; Hold</div>
      <div class="val ${cls(hold)}">${pct(hold)}</div>
      <div class="sub">${st.beats_buy_hold ? "strategy ahead" : "holding won"}</div></div>
    <div class="stat"><div class="label">Cost drag</div>
      <div class="val neg">-${st.cost_drag_pct}%</div>
      <div class="sub">fees $${n.fees_paid} · slippage $${n.slippage_cost}</div></div>
    <div class="stat"><div class="label">Trades / win-rate</div>
      <div class="val ${(n.win_rate ?? 0) >= 50 ? "pos" : ""}">${n.win_rate ?? "—"}%</div>
      <div class="sub">${n.num_trades} trades · max DD ${n.max_drawdown_pct}%</div></div>`;
}

function walkForwardCards(wf) {
  const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);
  const cls = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
  if (!wf || wf.error) {
    return `<div class="stat" style="grid-column:1/-1"><div class="label">Walk-forward</div>
      <div class="val">—</div><div class="sub">${esc(wf && wf.error ? wf.error : "unavailable")}</div></div>`;
  }
  const h = wf.holdout, fs = wf.fold_summary;
  return `
    <div class="stat"><div class="label">Out-of-sample (test)</div>
      <div class="val ${cls(h.test.return_pct)}">${pct(h.test.return_pct)}</div>
      <div class="sub">train ${pct(h.train.return_pct)} · split ${esc(h.split_date)}</div></div>
    <div class="stat"><div class="label">Holds up unseen?</div>
      <div class="val ${h.holds_up ? "pos" : "neg"}">${h.holds_up ? "yes" : "no"}</div>
      <div class="sub">test vs hold ${pct(h.test_vs_buy_hold)} · ${h.test.num_trades} trades</div></div>
    <div class="stat"><div class="label">Fold consistency</div>
      <div class="val ${fs.positive_folds * 2 >= fs.folds ? "pos" : "neg"}">${fs.positive_folds}/${fs.folds}+</div>
      <div class="sub">avg ${pct(fs.avg_return_pct)} · beat hold ${fs.beat_hold_folds}/${fs.folds}</div></div>
    <div class="stat"><div class="label">Best / worst fold</div>
      <div class="val ${cls(fs.best_fold_pct)}">${pct(fs.best_fold_pct)}</div>
      <div class="sub">worst ${pct(fs.worst_fold_pct)}</div></div>`;
}

function renderProof(d) {
  const s = d.summary;
  const pn = (v) => (v == null ? "—" : (v >= 0 ? "pos" : "neg"));
  const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);

  const head = (t) => `<div class="proof-section" style="grid-column:1/-1">${t}</div>`;
  const signalCards = `
    <div class="stat"><div class="label">Signals fired (2y)</div>
      <div class="val">${s.signals}</div><div class="sub">${d.symbol} · ${d.kind}</div></div>
    <div class="stat"><div class="label">Directional hit-rate</div>
      <div class="val ${s.win_rate >= 50 ? "pos" : ""}">${s.win_rate ?? "—"}%</div>
      <div class="sub">raw · net ${s.net_win_rate ?? "—"}%</div></div>
    <div class="stat"><div class="label">STRONG BUY win-rate</div>
      <div class="val ${(s.buy_win_rate ?? 0) >= 50 ? "pos" : ""}">${s.buy_win_rate ?? "—"}%</div>
      <div class="sub">${s.buy_signals} signals</div></div>
    <div class="stat"><div class="label">Avg move (signal dir)</div>
      <div class="val ${pn(s.avg_move_30d)}">${pct(s.avg_move_30d)}</div>
      <div class="sub">net ${pct(s.net_avg_move_30d)} · cost ${s.round_trip_cost_pct ?? "—"}%</div></div>`;

  $("#proofStats").innerHTML =
    head(`Strategy result — after fees &amp; slippage (traded, not just signaled)`)
    + strategyCards(d.strategy)
    + head(`Walk-forward — does the edge hold out-of-sample?`)
    + walkForwardCards(d.walkforward)
    + head(`Signal quality — raw forward outcomes`)
    + signalCards;

  renderProofChart(d.series, d.events);

  const rows = d.events.slice().reverse().slice(0, 14).map((e) => {
    const cls = e.fwd30 == null ? "" : (e.fwd30 >= 0 ? "pos" : "neg");
    const dir = e.fwd30 == null ? "" : cls;
    const win = e.fwd30 == null ? "(open)"
      : ((e.dir === "buy" && e.fwd30 > 0) || (e.dir === "sell" && e.fwd30 < 0) ? "✓" : "✗");
    return `<div class="ev-row">
      <span class="date">${esc(e.date)}</span>
      <span class="badge ${e.type === "STRONG BUY" ? "strong-buy" : "strong-sell"}">${e.type}</span>
      <span class="px">@ ${fmtPrice(e.price)} · RSI ${e.rsi ?? "—"}</span>
      <span class="fwd ${dir}">${e.fwd30 == null ? "(open)" : (e.fwd30 > 0 ? "+" : "") + e.fwd30 + "% " + win}</span>
    </div>`;
  }).join("");
  $("#proofEvents").innerHTML =
    `<div class="ev-row head"><span>Date</span><span>Signal</span><span>Entry</span><span>30-bar</span></div>`
    + (rows || `<div class="proof-empty">No strong signals in this window.</div>`);
}

function renderProofChart(series, events) {
  const svg = $("#proofChart");
  const closes = series.closes, W = 1000, H = 280, pad = 8;
  if (!closes || closes.length < 2) { svg.innerHTML = ""; return; }
  const min = Math.min(...closes), max = Math.max(...closes), span = max - min || 1;
  const X = (i) => pad + (i / (closes.length - 1)) * (W - pad * 2);
  const Y = (v) => pad + (1 - (v - min) / span) * (H - pad * 2);
  const line = closes.map((c, i) => `${X(i).toFixed(1)},${Y(c).toFixed(1)}`).join(" ");
  const marks = events.map((e) => {
    const x = X(e.idx), y = Y(e.price);
    const col = e.dir === "buy" ? "var(--buy)" : "var(--sell)";
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.5" fill="${col}"
      stroke="#0a0d12" stroke-width="1.5"><title>${e.date} ${e.type}</title></circle>`;
  }).join("");
  svg.innerHTML = `
    <polyline points="${line}" fill="none" stroke="#3a4757" stroke-width="1.4"/>
    ${marks}`;
}

function startAuto() {
  clearInterval(state.timer);
  if ($("#autoRefresh").checked) state.timer = setInterval(loadView, 60000);
}

function tickClock() {
  $("#clock").textContent = new Date().toLocaleTimeString();
}

async function init() {
  try {
    const u = await (await fetch("/api/universe")).json();
    defaults = u;
    if (u.features) features = u.features;
    if (u.upgrade) upgradeUrl = u.upgrade;
  } catch (e) { /* keep defaults */ }
  applyGating();
  $("#tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) setView(btn.dataset.view);
  });
  $("#refreshBtn").addEventListener("click", loadView);
  $("#autoRefresh").addEventListener("change", startAuto);
  $("#addForm").addEventListener("submit", (e) => {
    e.preventDefault();
    addSymbol($("#addInput").value);
    $("#addInput").value = "";
  });
  $("#proofForm").addEventListener("submit", (e) => { e.preventDefault(); runProof(); });
  $("#optForm").addEventListener("submit", (e) => { e.preventDefault(); optionsLoaded = true; loadOptions(); });
  $("#optExpiry").addEventListener("change", (e) => loadOptions(e.target.value));
  $("#optPot").addEventListener("change", () => loadOptions($("#optExpiry").value || undefined));
  $("#optScanBtn").addEventListener("click", scanPot);
  $("#potForm").addEventListener("submit", (e) => { e.preventDefault(); logProbe(); });
  $("#potReset").addEventListener("click", resetPot);
  $("#potStart").addEventListener("change", (e) => setPotStart(e.target.value));
  $("#alertCancel").addEventListener("click", () => { $("#alertModal").hidden = true; });
  $("#alertSave").addEventListener("click", saveAlert);
  $("#alertModal").addEventListener("click", (e) => {
    if (e.target.id === "alertModal") $("#alertModal").hidden = true;
  });

  tickClock();
  setInterval(tickClock, 1000);
  startAuto();
  loadView();
}

init();
