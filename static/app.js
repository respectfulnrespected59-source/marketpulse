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
  `;

  el.querySelector(".star").addEventListener("click", () => toggleWatch(r));
  el.querySelector(".alert").addEventListener("click", () => openAlert(r));
  return el;
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

function setView(v) {
  state.view = v;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.view === v));

  const isProof = v === "proof";
  $("#proofPanel").hidden = !isProof;
  $("#grid").hidden = isProof;
  document.querySelector(".controls").hidden = isProof;
  document.querySelector(".breadth").hidden = isProof;
  if (isProof) {
    if (!proofLoaded) { proofLoaded = true; runProof(); }
    return;
  }

  $("#addInput").placeholder = v === "stocks"
    ? "Add stock ticker (e.g. NVDA)…"
    : v === "crypto" ? "Add coin id (e.g. solana)…" : "Add ticker or coin id…";
  loadView();
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

function renderProof(d) {
  const s = d.summary;
  const pn = (v) => (v == null ? "—" : (v >= 0 ? "pos" : "neg"));
  const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);

  $("#proofStats").innerHTML = `
    <div class="stat"><div class="label">Signals fired (2y)</div>
      <div class="val">${s.signals}</div><div class="sub">${d.symbol} · ${d.kind}</div></div>
    <div class="stat"><div class="label">Directional hit-rate</div>
      <div class="val ${s.win_rate >= 50 ? "pos" : ""}">${s.win_rate ?? "—"}%</div>
      <div class="sub">over next 30 bars</div></div>
    <div class="stat"><div class="label">STRONG BUY win-rate</div>
      <div class="val ${(s.buy_win_rate ?? 0) >= 50 ? "pos" : ""}">${s.buy_win_rate ?? "—"}%</div>
      <div class="sub">${s.buy_signals} signals</div></div>
    <div class="stat"><div class="label">Avg move (signal dir)</div>
      <div class="val ${pn(s.avg_move_30d)}">${pct(s.avg_move_30d)}</div>
      <div class="sub">best ${pct(s.best)} · worst ${pct(s.worst)}</div></div>`;

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
