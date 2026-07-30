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
  view: "home",
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

  // Click-to-live handoff: for crypto we need the CoinGecko id (falls back to
  // lowercased name if the backend didn't send one); for stocks the ticker is
  // what /api/intraday expects.
  const liveSym = r.kind === "crypto"
    ? (r.id || (r.name || r.symbol || "").toLowerCase())
    : r.symbol;

  el.innerHTML = `
    <div class="card-top">
      <div class="sym-tap" role="button" tabindex="0"
           data-live-kind="${esc(r.kind)}" data-live-sym="${esc(liveSym)}"
           title="Open ${esc(r.symbol)} live chart">
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

  el.querySelector(".star").addEventListener("click", (e) => { e.stopPropagation(); toggleWatch(r); });
  el.querySelector(".alert").addEventListener("click", (e) => { e.stopPropagation(); openAlert(r); });
  return el;
}

/* Jump straight to the Live tab with a symbol preloaded and start the chart. */
function openLiveFor(kind, sym) {
  if (!sym) return;
  const k = (kind === "crypto") ? "crypto" : "stock";
  const symEl = $("#liveSymbol"), kindEl = $("#liveKind");
  if (symEl) symEl.value = k === "crypto" ? String(sym).toLowerCase() : String(sym).toUpperCase();
  if (kindEl) kindEl.value = k;
  setView("live");
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
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2.2"
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
  // Hide Proof + DCA tabs in the free build (both are Pro features).
  const proofTab = document.querySelector('.tab[data-view="proof"]');
  if (proofTab) proofTab.style.display = features.proof ? "" : "none";
  const dcaTab = document.querySelector('.tab[data-view="dca"]');
  if (dcaTab) dcaTab.style.display = features.proof ? "" : "none";
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
  markSeen(v);
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.view === v));

  const isHome = v === "home";
  const isProof = v === "proof";
  const isOpt = v === "options";
  const isPot = v === "pot";
  const isDca = v === "dca";
  const isLive = v === "live";
  const isPanel = isHome || isProof || isOpt || isPot || isDca || isLive;
  $("#homePanel").hidden = !isHome;
  $("#proofPanel").hidden = !isProof;
  $("#optionsPanel").hidden = !isOpt;
  $("#potPanel").hidden = !isPot;
  $("#dcaPanel").hidden = !isDca;
  $("#livePanel").hidden = !isLive;
  $("#grid").hidden = isPanel;
  document.querySelector(".controls").hidden = isPanel;
  document.querySelector(".breadth").hidden = isPanel;
  if (!isLive) { stopLivePoll(); stopChartPoll(); }  // don't poll while off the Live tab
  if (isHome) { renderHome(); return; }
  if (isLive) {
    ensureLiveQf();
    initLiveChartInteractions();
    renderLive();
    loadLiveTradeChart();
    startChartPoll();
    const lp = getLive();
    if (lp && lp.status === "open") startLivePoll();
    return;
  }
  if (isProof) {
    if (!proofLoaded) { proofLoaded = true; runProof(); }
    return;
  }
  if (isOpt) {
    if (!optionsLoaded) { optionsLoaded = true; loadOptions(); }
    return;
  }
  if (isDca) {
    ensureDcaQf();
    if (!dcaLoaded) { dcaLoaded = true; loadDca(); }
    return;
  }
  if (isPot) { ensurePotQf(); renderPot(); return; }

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

/* ---- Live trading chart: real intraday candlesticks that refresh live ---- */
let liveChartTimer = null;
let liveTf = "5m";
const TF_ORDER = ["1m", "5m", "10m", "1h"];
const TF_LABELS = {
  stock: { "1m": "1m", "5m": "5m", "10m": "10m", "1h": "1h" },
  crypto: { "1m": "1m", "5m": "5m", "10m": "10m", "1h": "1h" },
};
const TF_GRAIN = {
  stock: { "1m": "1m · 1D", "5m": "5m · 5D", "10m": "10m · 5D", "1h": "1h · 1M" },
  crypto: { "1m": "1m · ~5h", "5m": "5m · ~1D", "10m": "10m · ~2D", "1h": "1h · ~12D" },
};
// 1m tape needs a much faster poll to feel alive; wider zooms don't.
const TF_POLL_MS = { "1m": 8000, "5m": 20000, "10m": 30000, "1h": 60000 };

// Chart overlay cache: daily EMA(14/21/57) series + TTM squeeze status. Fetched
// once per symbol, refreshed every ~5 min (daily bars only change once a day).
let liveOverlay = null;                  // last payload, or null
let liveOverlayKey = null;               // "kind:symbol" of what's currently cached
let liveOverlayAt = 0;                   // ms epoch of last successful fetch
const OVERLAY_TTL_MS = 5 * 60 * 1000;
const EMA_COLORS = { ema14: "#f5c66b", ema21: "#5b8def", ema57: "#c471ed" };

// In-memory snapshot of the last loaded intraday payload — click handlers use
// it to convert pixel coords back into (timestamp, price) space.
let liveLast = { data: null, kind: "stock", ok: false };

// Chart viewport: which slice of the loaded OHLC is currently visible.
// `pinned` = true means "keep the right edge glued to the latest bar as new
// bars arrive"; the moment the user pans back, that latches to false and the
// poll no longer yanks them forward. Reset whenever symbol or timeframe
// changes so the default compact window shows the freshest bars.
let chartView = { start: null, count: null, pinned: true };
let lastRenderSym = null, lastRenderTf = null;
const MIN_VISIBLE_BARS = 12;
// Sensible default "compact" viewport per timeframe — chosen so a new tape
// opens showing recent context at a comfortable candle width, not the whole
// loaded array crammed into 1000px. Wheel/pinch zooms out to the full history.
const DEFAULT_VISIBLE = { "1m": 90, "5m": 78, "10m": 78, "1h": 60 };
let panDrag = null;  // {startClientX, startBar, moved}
// Wheel coalescing: many trackpads fire 8-15 wheel events per gesture, each
// with deltaY ~100. Applying a full step per event compounds into a dizzying
// zoom. Instead: accumulate the raw delta between frames and apply once per
// rAF with a gentle exponential factor.
let _wheelAccum = 0;
let _wheelAnchorBarFull = null;
let _wheelIsPan = false;
let _wheelRaf = 0;
function resetChartView() { chartView = { start: null, count: null, pinned: true }; }
// Chart interaction mode: "none" | "mark" | "line".
// Trend line UX: single click drops a pending gold anchor at the target price
// (visible ring + dashed price rule). Then press-and-drag ANYWHERE on the
// chart — no timing window, no double-click — rubber-bands a gold line from
// the anchor to the cursor; release commits it. Plain click without dragging
// just relocates the anchor.
let ltcTool = "none";
let trendAnchor = null;        // {ts, price, x, y} — target price, ephemeral
let trendDragging = false;
let trendPreview = null;       // {ax, ay, bx, by} for live rubber-band
let dragState = null;          // {startX, startY, moved} — press-and-drag tracker
let suppressNextClick = false; // stop the drag's release from committing an anchor
let _rafDrag = 0;
const DRAG_THRESHOLD_PX = 4;   // how far the cursor must travel to be a "drag"

// Precision + edit state
let altHeld = false;           // hold Alt to bypass snap
let editState = null;          // {kind: "mark"|"lineA"|"lineB", idx, sym} being edited
let editPreview = null;        // {ts, price} live-follows the cursor during edit
const SNAP_PHYS_PX = 18;       // snap radius in *screen* pixels (feels the same at any zoom)
const HIT_PHYS_PX = 12;        // click hit radius in *screen* pixels

// Per-symbol persistence for user-drawn marks & trend lines. Timestamps are
// unix-seconds so switching timeframes still lines them up on the tape.
function _ltcKeys(sym) {
  const k = String(sym || "").toUpperCase();
  return { marks: `mp_marks_${k}`, lines: `mp_lines_${k}` };
}
function _readArr(key) { try { return JSON.parse(localStorage.getItem(key)) || []; } catch { return []; } }
function _writeArr(key, arr) { try { localStorage.setItem(key, JSON.stringify(arr)); } catch {} }
function getUserMarks(sym) { return _readArr(_ltcKeys(sym).marks); }
function getUserLines(sym) { return _readArr(_ltcKeys(sym).lines); }
function addUserMark(sym, m) { const k = _ltcKeys(sym).marks; const a = _readArr(k); a.push(m); _writeArr(k, a); }
function addUserLine(sym, l) { const k = _ltcKeys(sym).lines; const a = _readArr(k); a.push(l); _writeArr(k, a); }
function popUserLast(sym) {
  const k = _ltcKeys(sym); const m = _readArr(k.marks), l = _readArr(k.lines);
  // Undo whichever bucket was written most recently, using the trailing `t`.
  const lastM = m.length ? m[m.length - 1].t || 0 : -1;
  const lastL = l.length ? l[l.length - 1].t || 0 : -1;
  if (lastL >= lastM && l.length) { l.pop(); _writeArr(k.lines, l); return "line"; }
  if (m.length) { m.pop(); _writeArr(k.marks, m); return "mark"; }
  return null;
}
function clearUserAll(sym) { const k = _ltcKeys(sym); _writeArr(k.marks, []); _writeArr(k.lines, []); }

function renderTfButtons(kind) {
  const box = $("#ltcTf");
  if (!box) return;
  const labels = TF_LABELS[kind === "crypto" ? "crypto" : "stock"];
  box.innerHTML = TF_ORDER.map((tf) =>
    `<button type="button" data-tf="${tf}" class="${tf === liveTf ? "is-active" : ""}">${labels[tf]}</button>`
  ).join("");
  box.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      if (liveTf === b.dataset.tf) return;
      liveTf = b.dataset.tf;
      loadLiveTradeChart();
      startChartPoll();                       // reset cadence for new tf
    }));
}

function stopChartPoll() {
  if (liveChartTimer) { clearInterval(liveChartTimer); liveChartTimer = null; }
}
function startChartPoll() {
  stopChartPoll();
  liveChartTimer = setInterval(loadLiveTradeChart, TF_POLL_MS[liveTf] || 20000);
}

async function loadLiveTradeChart() {
  const raw = $("#liveSymbol").value.trim();
  const kind = $("#liveKind").value;
  if (!raw) return;
  const sym = kind === "crypto" ? raw.toLowerCase() : raw.toUpperCase();
  try {
    const d = await (await fetch(`/api/intraday?symbol=${encodeURIComponent(sym)}&kind=${kind}&tf=${liveTf}`)).json();
    // Fire-and-forget overlay refresh so the chart shows immediately; the
    // next full render (either this call's chain or the next poll) picks up
    // the daily EMAs + squeeze once they land.
    loadChartOverlay(kind, sym).then((ov) => {
      if (ov) renderLiveTradeChart(d, kind);
    }).catch(() => {});
    renderLiveTradeChart(d, kind);
  } catch (e) { /* keep the prior chart on a transient error */ }
}

async function loadChartOverlay(kind, sym) {
  const key = `${kind}:${sym.toLowerCase()}`;
  if (liveOverlayKey === key && Date.now() - liveOverlayAt < OVERLAY_TTL_MS) {
    return liveOverlay;
  }
  try {
    const r = await fetch(`/api/chart-overlay?symbol=${encodeURIComponent(sym)}&kind=${kind}`);
    const d = await r.json();
    if (d && !d.error) {
      liveOverlay = d;
      liveOverlayKey = key;
      liveOverlayAt = Date.now();
      return d;
    }
  } catch (e) { /* keep prior overlay */ }
  return liveOverlay && liveOverlayKey === key ? liveOverlay : null;
}

/* Interpolate an EMA value at unix-second `ts` from sorted [[ts,v]] pairs.
   Before the earliest / after the latest → clamp to the closest end. */
function _emaAt(pairs, ts) {
  if (!pairs || !pairs.length) return null;
  if (ts <= pairs[0][0]) return pairs[0][1];
  if (ts >= pairs[pairs.length - 1][0]) return pairs[pairs.length - 1][1];
  let lo = 0, hi = pairs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pairs[mid][0] <= ts) lo = mid; else hi = mid;
  }
  const [t0, v0] = pairs[lo], [t1, v1] = pairs[hi];
  const f = t1 === t0 ? 0 : (ts - t0) / (t1 - t0);
  return v0 + (v1 - v0) * f;
}

function _emaOverlaySVG(geom, clampY, emas) {
  if (!geom || !emas) return "";
  const { X, Y, ts, n } = geom;
  if (!ts || ts.length !== n || n < 2) return "";
  let out = "";
  const order = ["ema14", "ema21", "ema57"];
  for (const key of order) {
    const pairs = emas[key];
    if (!pairs || pairs.length < 1) continue;
    const pts = [];
    for (let i = 0; i < n; i++) {
      const v = _emaAt(pairs, ts[i]);
      if (v == null) continue;
      pts.push(`${X(i).toFixed(1)},${clampY(v).toFixed(1)}`);
    }
    if (pts.length < 2) continue;
    out += `<polyline points="${pts.join(" ")}" fill="none" stroke="${EMA_COLORS[key]}"
      stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" opacity="0.9"
      pointer-events="none"><title>${key.toUpperCase()} (daily)</title></polyline>`;
  }
  return out;
}

function _renderSqueezeChip(overlay) {
  const box = $("#ltcSqz");
  if (!box) return;
  const sq = overlay && overlay.squeeze;
  const wk = sq && sq.weekly;
  if (!wk || !wk.state) { box.hidden = true; box.textContent = ""; return; }
  const state = wk.state;                              // "on" | "fired" | "off"
  const mom = wk.mom;                                  // "bull" | "bear"
  const arrow = mom === "bull"
    ? (wk.accel === "rising" ? "▲" : "△")
    : (wk.accel === "falling" ? "▼" : "▽");
  const grain = sq.grain === "daily" ? "D" : "W";
  const txt = state === "on" ? `ON·${wk.bars}` : state === "fired" ? "FIRED" : "off";
  box.hidden = false;
  box.className = `ltc-sqz ${state} ${mom || ""}`;
  box.innerHTML = `<b>TTM</b> ${grain} ${txt} <span class="ltc-sqz-arr">${arrow}</span>`;
  box.title = `TTM squeeze ${state} (${grain === "D" ? "daily" : "weekly"} bars) · momentum ${mom || "—"} ${wk.accel || ""}`;
}

function _renderEmaLegend(overlay) {
  const box = $("#ltcEmas");
  if (!box) return;
  const e = overlay && overlay.emas;
  const has = e && (e.ema14.length || e.ema21.length || e.ema57.length);
  if (!has) { box.hidden = true; box.textContent = ""; return; }
  const chip = (k, label) => {
    const arr = e[k];
    const v = arr && arr.length ? arr[arr.length - 1][1] : null;
    if (v == null) return "";
    return `<span class="ltc-ema-chip"><i style="background:${EMA_COLORS[k]}"></i>${label}<b>${fmtPrice(v)}</b></span>`;
  };
  box.hidden = false;
  box.innerHTML = chip("ema14", "EMA14") + chip("ema21", "EMA21") + chip("ema57", "EMA57");
}

function renderLiveTradeChart(d, kind) {
  const svg = $("#liveTradeChart");
  const fullOhlc = (d && d.ohlc) || [];
  const fullTs = (d && d.ts) || [];
  const fullVol = (d && d.volume) || [];
  $("#ltcSym").textContent = (d && d.symbol) || "—";
  const grainMap = TF_GRAIN[kind === "crypto" ? "crypto" : "stock"];
  $("#ltcKind").textContent = (kind === "crypto" ? "Crypto · " : "Stock · ") + (grainMap[liveTf] || "");
  renderTfButtons(kind);
  _renderSqueezeChip(liveOverlay);
  _renderEmaLegend(liveOverlay);

  // Reset the viewport whenever the identity of the tape changes so a fresh
  // symbol / timeframe starts with all bars visible (not stuck on a stale window).
  const sym = d && d.symbol;
  if (sym !== lastRenderSym || liveTf !== lastRenderTf) {
    resetChartView();
    lastRenderSym = sym;
    lastRenderTf = liveTf;
  }

  // Slice to viewport. `count == null` means "use the compact per-tf default"
  // (much easier to read than the whole loaded array); otherwise clamp to
  // sane bounds. If pinned, glue to the right edge as new bars arrive.
  const nAll = fullOhlc.length;
  const defaultN = Math.min(nAll, DEFAULT_VISIBLE[liveTf] || 78);
  let count = chartView.count == null ? defaultN : Math.max(MIN_VISIBLE_BARS, Math.min(nAll, chartView.count));
  let start;
  if (chartView.pinned || chartView.start == null) {
    start = Math.max(0, nAll - count);
  } else {
    start = Math.max(0, Math.min(nAll - count, chartView.start));
  }
  const end = start + count;
  const ohlc = fullOhlc.slice(start, end);
  const tsArr = fullTs.slice(start, end);
  const volArr = fullVol.slice(start, end);

  liveLast = { data: d, kind, ok: ohlc.length >= 2 };
  if (ohlc.length < 2) {
    svg.innerHTML = "";
    $("#ltcLast").textContent = "—";
    $("#ltcChg").textContent = "";
    $("#ltcFoot").textContent = kind === "crypto"
      ? (liveTf === "1m" ? "No 1m tape for this coin — try BTC, ETH, SOL…" : "No intraday candles for this coin (try BTC, ETH, SOL…).")
      : (liveTf === "1m" ? "No 1m tape right now — Yahoo only serves 1m during the current session." : "No intraday candles right now — market may be closed.");
    return;
  }

  // Webull-style layout: candles left, price ladder right, time axis below,
  // volume pane between them.
  const W = 1000, H = 360;
  const padL = 8, padT = 10;
  const AXIS_R = 58;   // right price ladder width
  const AXIS_B = 22;   // bottom time-label strip height
  const VOL_H = 46;    // volume histogram height
  const VOL_GAP = 4;
  const priceRect = {
    x: padL, y: padT,
    w: W - padL - AXIS_R,
    h: H - padT - AXIS_B - VOL_H - VOL_GAP,
  };
  const volRect = { x: padL, y: priceRect.y + priceRect.h + VOL_GAP, w: priceRect.w, h: VOL_H };
  const timeAxisTop = volRect.y + volRect.h;

  const c = candlesInRect(ohlc, priceRect);
  const clampY = (v) => Math.max(priceRect.y, Math.min(priceRect.y + priceRect.h, c.Y(v)));
  const last = ohlc[ohlc.length - 1][3];
  liveLast.geom = {
    W, H, pad: padL, X: c.X, Y: c.Y, n: ohlc.length, ohlc, ts: tsArr,
    priceRect, volRect, timeAxisTop, axisR: AXIS_R,
    priceMin: c.min, priceMax: c.max,
    // Viewport bookkeeping so wheel/drag can operate against the full tape.
    fullOhlc, fullTs, fullVol, viewStart: start, viewCount: count, viewEnd: end, nAll,
  };

  let base = "";
  base += _priceGridSVG(priceRect, c.min, c.max);
  base += _sessionDividersSVG(priceRect, ohlc, tsArr, timeAxisTop);
  base += c.markup;
  base += _volumeSVG(volRect, ohlc, volArr);
  base += _timeAxisSVG(priceRect, ohlc, tsArr, liveTf, kind, timeAxisTop);
  base += _priceAxisSVG(priceRect, c.min, c.max, last, AXIS_R, W);

  // Overlays live on top of the chart & axes.
  let overlay = "";
  overlay += `<line x1="${priceRect.x}" y1="${clampY(last).toFixed(1)}" x2="${priceRect.x + priceRect.w}" y2="${clampY(last).toFixed(1)}"
    stroke="var(--text-dim)" stroke-width="1" stroke-dasharray="2 3" opacity="0.5"/>`;
  const p = getLive();
  if (p && p.sym && d.symbol && p.sym.toUpperCase() === String(d.symbol).toUpperCase()) {
    overlay += `<line x1="${priceRect.x}" y1="${clampY(p.entry).toFixed(1)}" x2="${priceRect.x + priceRect.w}" y2="${clampY(p.entry).toFixed(1)}"
      stroke="var(--gold)" stroke-width="1.8" stroke-dasharray="6 4" filter="url(#neonGold)"><title>your entry ${p.entry}</title></line>`;
  }
  // Daily EMA(14/21/57) polylines — interpolated onto the intraday grid so
  // they span the whole width at any timeframe.
  if (liveOverlay && liveOverlay.emas) {
    overlay += _emaOverlaySVG(liveLast.geom, clampY, liveOverlay.emas);
  }
  overlay += _userOverlaySVG(d.symbol, liveLast.geom, clampY);

  if (trendAnchor) {
    const a = _tsToXY(liveLast.geom, trendAnchor.ts, trendAnchor.price);
    if (a) {
      const ay = clampY(trendAnchor.price);
      overlay += `<line x1="${priceRect.x}" y1="${ay.toFixed(1)}" x2="${priceRect.x + priceRect.w}" y2="${ay.toFixed(1)}"
        stroke="var(--gold)" stroke-width="1" stroke-dasharray="2 4" opacity="0.55"/>`;
      overlay += `<circle cx="${a.x.toFixed(1)}" cy="${ay.toFixed(1)}" r="6.5"
        fill="var(--gold)" fill-opacity="0.35" stroke="var(--gold)" stroke-width="2"
        filter="url(#neonGold)"><title>target ${trendAnchor.price} — press &amp; drag anywhere to draw the trend</title></circle>`;
    }
  }
  if (trendPreview) {
    overlay += `<line x1="${trendPreview.ax.toFixed(1)}" y1="${trendPreview.ay.toFixed(1)}"
      x2="${trendPreview.bx.toFixed(1)}" y2="${trendPreview.by.toFixed(1)}"
      stroke="var(--gold)" stroke-width="2" stroke-dasharray="6 4" opacity="0.95"
      filter="url(#neonGold)"/>`;
  }

  // ltcCrosshair is updated separately in _drawCrosshair — no full redraw on hover.
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = _neonDefsSVG() + `<g id="ltcBase">${base}${overlay}</g><g id="ltcCrosshair" pointer-events="none"></g>`;

  const first = ohlc[0][3];
  const chg = first ? (last - first) / first * 100 : 0;
  $("#ltcLast").textContent = fmtPrice(last);
  const chgEl = $("#ltcChg");
  chgEl.textContent = (chg >= 0 ? "▲ " : "▼ ") + Math.abs(chg).toFixed(2) + "%";
  chgEl.className = "ltc-chg " + (chg >= 0 ? "up" : "down");
  const cadence = TF_POLL_MS[liveTf] / 1000;
  $("#ltcFoot").textContent = `Live candles · gold line = your entry · refreshes ~${cadence}s · Mark drops entries, Trend line = click target + drag · educational, not advice`;
}

/* ---- Webull-style chart primitives ---- */

function candlesInRect(ohlc, rect) {
  const highs = ohlc.map((b) => b[1]), lows = ohlc.map((b) => b[2]);
  const min = Math.min(...lows), max = Math.max(...highs), span = max - min || 1;
  const n = ohlc.length;
  const X = (i) => rect.x + (n === 1 ? 0.5 : i / (n - 1)) * rect.w;
  const Y = (v) => rect.y + (1 - (v - min) / span) * rect.h;
  const slot = rect.w / n;
  const bw = Math.max(1, Math.min(slot * 0.7, 9));
  const wick = Math.max(0.6, Math.min(bw * 0.28, 2));
  let out = "";
  for (let i = 0; i < n; i++) {
    const [o, h, l, c] = ohlc[i];
    const up = c >= o;
    const col = up ? "var(--buy)" : "var(--sell)";
    const x = X(i);
    const yH = Y(h), yL = Y(l);
    const yO = Y(o), yC = Y(c);
    const top = Math.min(yO, yC), bot = Math.max(yO, yC);
    const bodyH = Math.max(1, bot - top);
    out += `<line x1="${x.toFixed(1)}" y1="${yH.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yL.toFixed(1)}" stroke="${col}" stroke-width="${wick.toFixed(2)}"/>`;
    out += `<rect x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${col}" rx="0.5"/>`;
  }
  return { markup: out, X, Y, min, max };
}

function _fmtAxisPrice(v) {
  if (!isFinite(v)) return "";
  if (Math.abs(v) >= 10000) return v.toFixed(0);
  if (Math.abs(v) >= 100) return v.toFixed(1);
  if (Math.abs(v) >= 1) return v.toFixed(2);
  return v.toFixed(4);
}

/* Vertical divider + tiny date label at every session boundary — every time
   the calendar day changes bar-to-bar. Draws BEHIND the candles so the price
   action stays visually dominant, but the eye immediately clocks "new day
   here" instead of reading the overnight gap as a random blank. */
function _sessionDividersSVG(rect, ohlc, tsArr, timeAxisTop) {
  const n = ohlc.length;
  if (!tsArr || tsArr.length !== n || n < 2) return "";
  const n1 = Math.max(1, n - 1);
  const X = (i) => rect.x + (n === 1 ? 0.5 : i / n1) * rect.w;
  let out = "";
  let prevKey = null;
  // Density guard: at deep zoom-out one divider per bar is noise. Cap to
  // one label every ~55px so labels never overlap.
  const minLabelPx = 55;
  const barPx = rect.w / n;
  const labelStride = Math.max(1, Math.ceil(minLabelPx / Math.max(1, barPx)));
  let idxSinceLabel = labelStride;
  const bottom = (timeAxisTop != null ? timeAxisTop : rect.y + rect.h).toFixed(1);
  for (let i = 0; i < n; i++) {
    const t = tsArr[i];
    if (!t) continue;
    const d = new Date(t * 1000);
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    if (prevKey !== null && key !== prevKey) {
      const x = X(i).toFixed(1);
      out += `<line x1="${x}" y1="${rect.y.toFixed(1)}" x2="${x}" y2="${bottom}"
        stroke="rgba(120,180,255,0.18)" stroke-width="1" stroke-dasharray="3 5"/>`;
      if (idxSinceLabel >= labelStride) {
        const label = d.toLocaleDateString([], { month: "short", day: "numeric" });
        out += `<text x="${(X(i) + 4).toFixed(1)}" y="${(rect.y + 12).toFixed(1)}"
          fill="rgba(160,190,230,0.65)" font-family="var(--mono)" font-size="10"
          font-weight="600" letter-spacing="0.01em">${label}</text>`;
        idxSinceLabel = 0;
      }
    }
    idxSinceLabel++;
    prevKey = key;
  }
  return out;
}

function _priceGridSVG(rect, min, max) {
  const steps = 5;
  let out = "";
  for (let i = 0; i <= steps; i++) {
    const y = rect.y + rect.h * (i / steps);
    out += `<line x1="${rect.x}" y1="${y.toFixed(1)}" x2="${rect.x + rect.w}" y2="${y.toFixed(1)}"
      stroke="rgba(120,150,190,0.06)" stroke-width="1"/>`;
  }
  return out;
}

function _priceAxisSVG(rect, min, max, last, axisRW, W) {
  const steps = 5;
  const axisX = rect.x + rect.w;
  const span = max - min || 1;
  let out = "";
  for (let i = 0; i <= steps; i++) {
    const v = min + span * (1 - i / steps);   // top-to-bottom (highest first)
    const y = rect.y + rect.h * (i / steps);
    out += `<text x="${axisX + 6}" y="${(y + 3).toFixed(1)}" fill="var(--text-dim)"
      font-family="var(--mono)" font-size="10.5" font-weight="600" letter-spacing="0.01em">${_fmtAxisPrice(v)}</text>`;
  }
  // Floating last-price tag — Webull's signature.
  const ly = rect.y + (1 - (last - min) / span) * rect.h;
  const y = Math.max(rect.y + 8, Math.min(rect.y + rect.h - 8, ly));
  out += `<rect x="${(axisX + 2).toFixed(1)}" y="${(y - 8).toFixed(1)}" width="${axisRW - 6}" height="16" rx="3"
    fill="var(--gold)" opacity="0.94" filter="url(#neonGold)"/>`;
  out += `<text x="${(axisX + axisRW / 2 - 1).toFixed(1)}" y="${(y + 3).toFixed(1)}" fill="#0a0d12"
    font-family="var(--mono)" font-size="10.5" font-weight="800" text-anchor="middle">${_fmtAxisPrice(last)}</text>`;
  return out;
}

function _fmtAxisTime(dt, tf) {
  if (tf === "1m" || tf === "day") {
    return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return dt.toLocaleDateString([], { month: "short", day: "numeric" });
}

function _timeAxisSVG(rect, ohlc, tsArr, tf, kind, top) {
  const n = ohlc.length;
  if (!tsArr || tsArr.length !== n) return "";
  const steps = 5;
  let out = `<line x1="${rect.x}" y1="${top.toFixed(1)}" x2="${rect.x + rect.w}" y2="${top.toFixed(1)}"
    stroke="rgba(120,150,190,0.14)" stroke-width="1"/>`;
  for (let i = 0; i <= steps; i++) {
    const idx = Math.round((n - 1) * i / steps);
    const ts = tsArr[idx];
    if (!ts) continue;
    const x = rect.x + (n === 1 ? 0.5 : idx / (n - 1)) * rect.w;
    const label = _fmtAxisTime(new Date(ts * 1000), tf);
    out += `<line x1="${x.toFixed(1)}" y1="${top.toFixed(1)}" x2="${x.toFixed(1)}" y2="${(top + 4).toFixed(1)}"
      stroke="var(--text-dim)" stroke-width="1"/>`;
    out += `<text x="${x.toFixed(1)}" y="${(top + 14).toFixed(1)}" fill="var(--text-dim)"
      font-family="var(--mono)" font-size="10.5" font-weight="600" text-anchor="middle">${label}</text>`;
  }
  return out;
}

function _volumeSVG(rect, ohlc, volume) {
  if (!volume || volume.length !== ohlc.length || volume.every((v) => !v)) return "";
  const max = Math.max(...volume) || 1;
  const n = volume.length;
  const slot = rect.w / n;
  const bw = Math.max(1, Math.min(slot * 0.7, 9));
  let out = `<line x1="${rect.x}" y1="${rect.y.toFixed(1)}" x2="${rect.x + rect.w}" y2="${rect.y.toFixed(1)}"
    stroke="rgba(120,150,190,0.10)" stroke-width="1" stroke-dasharray="2 4"/>`;
  for (let i = 0; i < n; i++) {
    const h = (volume[i] / max) * rect.h;
    const x = rect.x + (n === 1 ? 0.5 : i / (n - 1)) * rect.w;
    const y = rect.y + rect.h - h;
    const [o, , , c] = ohlc[i];
    const col = c >= o ? "rgba(47,209,128,0.42)" : "rgba(255,93,108,0.42)";
    out += `<rect x="${(x - bw / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${col}"/>`;
  }
  out += `<text x="${(rect.x + 4).toFixed(1)}" y="${(rect.y + 11).toFixed(1)}"
    fill="var(--text-faint)" font-family="var(--mono)" font-size="9" letter-spacing="0.14em">VOL</text>`;
  return out;
}

function _drawCrosshair(x, y) {
  const g = liveLast.geom; if (!g) return _clearCrosshair();
  const r = g.priceRect;
  if (x < r.x || x > r.x + r.w || y < r.y || y > r.y + r.h) return _clearCrosshair();
  const el = $("#ltcCrosshair"); if (!el) return;

  // Snap the crosshair to the nearest OHLC point unless Alt bypasses it.
  const snap = altHeld ? null : _getSnapCandidate(x, y);
  const cx = snap ? snap.x : x;
  const cy = snap ? snap.y : y;
  const p = _pixelToTsPrice(cx, cy);
  if (snap) { p.price = snap.price; p.ts = snap.ts; }
  const priceLabelX = r.x + r.w;
  const when = p && p.ts ? _fmtAxisTime(new Date(p.ts * 1000), liveTf) : "";
  const priceStr = p ? _fmtAxisPrice(p.price) : "";
  const snapCol = snap ? snap.color : "var(--gold)";
  const snapDot = snap
    ? `<rect x="${(cx - 4).toFixed(1)}" y="${(cy - 4).toFixed(1)}" width="8" height="8"
        transform="rotate(45 ${cx.toFixed(1)} ${cy.toFixed(1)})"
        fill="${snap.color}" stroke="rgba(10,13,18,0.9)" stroke-width="1"/>
       <text x="${(cx + 8).toFixed(1)}" y="${(cy - 8).toFixed(1)}" fill="${snap.color}"
        font-family="var(--mono)" font-size="9" font-weight="700" letter-spacing="0.08em">${snap.kind.toUpperCase()}</text>`
    : "";

  // 1px physical-pixel lines regardless of chart size — sharper reads.
  const strokeW = 1 / (g.pxPerSvgY || 1);
  const lineCol = snap ? snapCol : "rgba(217,176,97,0.65)";
  el.innerHTML = `
    <line x1="${r.x}" y1="${cy.toFixed(2)}" x2="${(r.x + r.w).toFixed(2)}" y2="${cy.toFixed(2)}"
      stroke="${lineCol}" stroke-width="${strokeW.toFixed(2)}" stroke-dasharray="4 4" shape-rendering="crispEdges"/>
    <line x1="${cx.toFixed(2)}" y1="${r.y}" x2="${cx.toFixed(2)}" y2="${(r.y + r.h).toFixed(2)}"
      stroke="${lineCol}" stroke-width="${strokeW.toFixed(2)}" stroke-dasharray="4 4" shape-rendering="crispEdges"/>
    <circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="1.4" fill="${snap ? snapCol : "var(--gold)"}" opacity="0.95"/>
    <rect x="${(priceLabelX + 2).toFixed(1)}" y="${(cy - 8).toFixed(1)}"
      width="${g.axisR - 6}" height="16" rx="3"
      fill="rgba(10,13,18,0.96)" stroke="${snapCol}" stroke-width="1"/>
    <text x="${(priceLabelX + g.axisR / 2 - 1).toFixed(1)}" y="${(cy + 3).toFixed(1)}"
      fill="${snapCol}" font-family="var(--mono)" font-size="10.5" font-weight="800" text-anchor="middle">${priceStr}</text>
    <rect x="${(cx - 28).toFixed(1)}" y="${(g.timeAxisTop + 2).toFixed(1)}"
      width="56" height="16" rx="3" fill="rgba(10,13,18,0.96)" stroke="${snapCol}" stroke-width="1"/>
    <text x="${cx.toFixed(1)}" y="${(g.timeAxisTop + 13).toFixed(1)}"
      fill="${snapCol}" font-family="var(--mono)" font-size="10" font-weight="700" text-anchor="middle">${when}</text>
    ${snapDot}
  `;
}

function _clearCrosshair() {
  const el = $("#ltcCrosshair"); if (el) el.innerHTML = "";
}

/* ---- Precision snap to candle OHLC ---- */

// Return the nearest {high, low, open, close} point on candles near the
// cursor, or null if nothing is within SNAP_PHYS_PX *screen pixels*. Checks
// the nearest candle and its two neighbors so snap kicks in even when the
// cursor is between wicks. Colors follow the semantic role of the point so
// the user can eyeball which they're grabbing.
function _getSnapCandidate(x, y) {
  const g = liveLast.geom;
  if (!g || !g.ohlc || !g.ohlc.length) return null;
  const scale = g.pxPerSvgX && g.pxPerSvgY;
  // Convert the physical-pixel threshold back to SVG units on each axis.
  const thX = SNAP_PHYS_PX / (g.pxPerSvgX || 1);
  const thY = SNAP_PHYS_PX / (g.pxPerSvgY || 1);
  const r = g.priceRect;
  const relX = Math.max(0, Math.min(1, (x - r.x) / r.w));
  const nearest = Math.max(0, Math.min(g.n - 1, Math.round(relX * (g.n - 1))));
  const indices = [nearest - 1, nearest, nearest + 1].filter((i) => i >= 0 && i < g.n);
  let best = null, bestD = Infinity;
  for (const idx of indices) {
    const cx = g.X(idx);
    const [o, h, l, c] = g.ohlc[idx];
    const opts = [
      { price: h, kind: "high",  color: "var(--buy)"  },
      { price: l, kind: "low",   color: "var(--sell)" },
      { price: o, kind: "open",  color: "var(--gold)" },
      { price: c, kind: "close", color: "var(--gold)" },
    ];
    for (const opt of opts) {
      const py = g.Y(opt.price);
      // Normalize distance to physical pixels so 1px in X and 1px in Y count equally.
      const dxPx = (cx - x) * (g.pxPerSvgX || 1);
      const dyPx = (py - y) * (g.pxPerSvgY || 1);
      const d = Math.hypot(dxPx, dyPx);
      if (d < bestD) { bestD = d; best = { ...opt, x: cx, y: py, idx, ts: (g.ts && g.ts[idx]) || 0 }; }
    }
  }
  if (bestD > SNAP_PHYS_PX) return null;
  return best;
}

/* ---- Hit-testing existing marks + trend-line endpoints ---- */

function _hitTestMarker(x, y) {
  const g = liveLast.geom;
  const sym = liveLast.data && liveLast.data.symbol;
  if (!g || !sym) return null;
  const px = g.pxPerSvgX || 1, py = g.pxPerSvgY || 1;
  const inRange = (dx, dy) => Math.hypot(dx * px, dy * py) <= HIT_PHYS_PX;
  const marks = getUserMarks(sym);
  for (let i = marks.length - 1; i >= 0; i--) {
    const m = marks[i];
    const pt = _tsToXY(g, m.ts, m.price);
    if (!pt) continue;
    if (inRange(pt.x - x, g.Y(m.price) - y)) return { kind: "mark", idx: i, mark: m };
  }
  const lines = getUserLines(sym);
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    const a = _tsToXY(g, l.a && l.a.ts, l.a && l.a.price);
    const b = _tsToXY(g, l.b && l.b.ts, l.b && l.b.price);
    if (a && inRange(a.x - x, g.Y(l.a.price) - y)) return { kind: "lineA", idx: i, line: l };
    if (b && inRange(b.x - x, g.Y(l.b.price) - y)) return { kind: "lineB", idx: i, line: l };
  }
  return null;
}

function _deleteHit(hit, sym) {
  const k = _ltcKeys(sym);
  if (hit.kind === "mark") {
    const marks = getUserMarks(sym);
    marks.splice(hit.idx, 1);
    _writeArr(k.marks, marks);
  } else {
    const lines = getUserLines(sym);
    lines.splice(hit.idx, 1);
    _writeArr(k.lines, lines);
  }
  if (typeof toast === "function") toast("Deleted");
}

function _commitEdit() {
  if (!editState || !editPreview) return;
  const sym = editState.sym;
  const k = _ltcKeys(sym);
  if (editState.kind === "mark") {
    const marks = getUserMarks(sym);
    if (marks[editState.idx]) {
      marks[editState.idx] = { ...marks[editState.idx], ts: editPreview.ts, price: editPreview.price };
      _writeArr(k.marks, marks);
    }
  } else {
    const end = editState.kind === "lineA" ? "a" : "b";
    const lines = getUserLines(sym);
    if (lines[editState.idx]) {
      lines[editState.idx] = { ...lines[editState.idx], [end]: { ts: editPreview.ts, price: editPreview.price } };
      _writeArr(k.lines, lines);
    }
  }
}

/* ---- Neon defs, grid, and user overlays for the live chart ---- */

function _neonDefsSVG() {
  return `<defs>
    <filter id="neonGold" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="neonBuy" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="neonSell" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>`;
}

function _gridSVG(W, H, pad, ohlc) {
  const highs = ohlc.map((b) => b[1]), lows = ohlc.map((b) => b[2]);
  const min = Math.min(...lows), max = Math.max(...highs);
  const step = (max - min) / 4 || 1;
  let g = "";
  for (let i = 1; i < 4; i++) {
    const v = min + step * i;
    const y = pad + (1 - (v - min) / (max - min || 1)) * (H - pad * 2);
    g += `<line x1="${pad}" y1="${y.toFixed(1)}" x2="${W - pad}" y2="${y.toFixed(1)}"
      stroke="rgba(120,150,190,0.08)" stroke-width="1"/>`;
  }
  return g;
}

// Convert a stored (ts, price) point to (x, y) using current geometry. Falls
// back to first/last candle when the ts is outside the visible tape.
function _tsToXY(geom, ts, price) {
  if (!geom) return null;
  const { X, Y, ts: tsArr, n } = geom;
  let idx = 0;
  if (tsArr && tsArr.length === n && ts) {
    // Clip to the visible window so a mark whose timestamp is scrolled off
    // the chart doesn't render as a stray blob at the nearest edge candle.
    const first = tsArr[0], last = tsArr[n - 1];
    const step = n > 1 ? Math.max(1, (last - first) / (n - 1)) : 1;
    if (ts < first - step || ts > last + step) return null;
    let bestD = Infinity;
    for (let i = 0; i < tsArr.length; i++) {
      const d = Math.abs(tsArr[i] - ts);
      if (d < bestD) { bestD = d; idx = i; }
    }
  }
  return { x: X(idx), y: Y(price), idx };
}

function _userOverlaySVG(symbol, geom, clampY) {
  const marks = getUserMarks(symbol);
  const lines = getUserLines(symbol);
  const r = geom.priceRect || { x: geom.pad, y: 0, w: geom.W - geom.pad * 2, h: geom.H };
  const isEditing = editState && editState.sym === symbol && editPreview;
  let out = "";
  for (let i = 0; i < lines.length; i++) {
    let l = lines[i];
    if (isEditing && editState.idx === i) {
      if (editState.kind === "lineA") l = { ...l, a: { ...l.a, ts: editPreview.ts, price: editPreview.price } };
      if (editState.kind === "lineB") l = { ...l, b: { ...l.b, ts: editPreview.ts, price: editPreview.price } };
    }
    const a = _tsToXY(geom, l.a && l.a.ts, l.a && l.a.price);
    const b = _tsToXY(geom, l.b && l.b.ts, l.b && l.b.price);
    if (!a || !b) continue;
    const col = l.color || "var(--gold)";
    out += `<line x1="${a.x.toFixed(1)}" y1="${clampY(l.a.price).toFixed(1)}"
      x2="${b.x.toFixed(1)}" y2="${clampY(l.b.price).toFixed(1)}"
      stroke="${col}" stroke-width="1.6" opacity="0.9" filter="url(#neonGold)"/>`;
    // Endpoint handles — visible + hit-testable.
    const ax = a.x, ay = clampY(l.a.price), bx = b.x, by = clampY(l.b.price);
    const editingA = isEditing && editState.kind === "lineA" && editState.idx === i;
    const editingB = isEditing && editState.kind === "lineB" && editState.idx === i;
    out += `<circle cx="${ax.toFixed(1)}" cy="${ay.toFixed(1)}" r="${editingA ? 5 : 3.5}" fill="${col}" fill-opacity="${editingA ? 0.9 : 0.65}" stroke="var(--bg)" stroke-width="1"/>`;
    out += `<circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="${editingB ? 5 : 3.5}" fill="${col}" fill-opacity="${editingB ? 0.9 : 0.65}" stroke="var(--bg)" stroke-width="1"/>`;
  }
  for (let i = 0; i < marks.length; i++) {
    let m = marks[i];
    if (isEditing && editState.kind === "mark" && editState.idx === i) {
      m = { ...m, ts: editPreview.ts, price: editPreview.price };
    }
    const p = _tsToXY(geom, m.ts, m.price);
    if (!p) continue;
    const y = clampY(m.price);
    const col = m.dir === "put" || m.dir === "short" ? "var(--sell)"
              : m.dir === "call" || m.dir === "long" ? "var(--buy)"
              : "var(--gold)";
    const filt = col.includes("sell") ? "neonSell" : col.includes("buy") ? "neonBuy" : "neonGold";
    const editingMe = isEditing && editState.kind === "mark" && editState.idx === i;
    out += `<line x1="${r.x}" y1="${y.toFixed(1)}" x2="${(r.x + r.w).toFixed(1)}" y2="${y.toFixed(1)}"
      stroke="${col}" stroke-width="1" stroke-dasharray="2 5" opacity="0.35"/>`;
    out += `<circle cx="${p.x.toFixed(1)}" cy="${y.toFixed(1)}" r="${editingMe ? 7 : 5.5}" fill="${editingMe ? col : "none"}" fill-opacity="${editingMe ? 0.4 : 1}"
      stroke="${col}" stroke-width="${editingMe ? 2.8 : 2.2}" filter="url(#${filt})">
      <title>${m.note || (m.dir || "mark") + " @ " + m.price} — drag to move, Alt-click to delete</title></circle>`;
  }
  return out;
}

/* ---- Chart interaction: click to mark / draw / hover crosshair / fullscreen ---- */

function _svgEventToChart(evt) {
  const svg = $("#liveTradeChart");
  const rect = svg.getBoundingClientRect();
  // Use the SVG's current viewBox — it was resized when we moved to the
  // Webull layout (1000×360), so a hardcoded height throws Y off by 20%.
  const vb = svg.viewBox && svg.viewBox.baseVal;
  const W = (vb && vb.width) || 1000;
  const H = (vb && vb.height) || 360;
  const x = ((evt.clientX - rect.left) / rect.width) * W;
  const y = ((evt.clientY - rect.top) / rect.height) * H;
  return { x, y, W, H, pxPerSvgX: rect.width / W, pxPerSvgY: rect.height / H };
}

function _pixelToTsPrice(x, y) {
  const g = liveLast.geom;
  if (!g) return null;
  const r = g.priceRect || { x: g.pad, y: g.pad, w: g.W - g.pad * 2, h: g.H - g.pad * 2 };
  const t = Math.max(0, Math.min(1, (x - r.x) / r.w));
  const idx = Math.round(t * (g.n - 1));
  const ts = (g.ts && g.ts[idx]) || Math.floor(Date.now() / 1000);
  const min = g.priceMin != null ? g.priceMin : Math.min(...g.ohlc.map((b) => b[2]));
  const max = g.priceMax != null ? g.priceMax : Math.max(...g.ohlc.map((b) => b[1]));
  const span = (max - min) || 1;
  const price = min + (1 - Math.max(0, Math.min(1, (y - r.y) / r.h))) * span;
  return { ts, price: +price.toFixed(4), idx };
}

function _setTool(t) {
  ltcTool = t;
  // Any tool switch clears an in-flight trend gesture.
  trendAnchor = null; trendDragging = false; trendPreview = null; dragState = null;
  const wrap = $("#liveTradeWrap");
  if (wrap) {
    wrap.classList.toggle("tool-mark", t === "mark");
    wrap.classList.toggle("tool-line", t === "line");
    wrap.classList.toggle("tool-active", t !== "none");
  }
  document.querySelectorAll(".ltc-tool[data-tool]").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.tool === t));
  const hint = $("#ltcHint");
  if (hint) {
    if (t === "mark") { hint.hidden = false; hint.textContent = "Click the chart to drop an entry mark"; }
    else if (t === "line") { hint.hidden = false; hint.textContent = "Click target price → then press & drag to draw the trend"; }
    else { hint.hidden = true; hint.textContent = ""; }
  }
  if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _onChartClick(evt) {
  if (suppressNextClick) { suppressNextClick = false; return; }
  if (!liveLast.ok || ltcTool === "none") return;
  const { x, y } = _svgEventToChart(evt);
  // Snap to the nearest OHLC point unless Alt held.
  const snap = altHeld ? null : _getSnapCandidate(x, y);
  const p = snap ? { ts: snap.ts, price: snap.price, idx: snap.idx } : _pixelToTsPrice(x, y);
  if (!p) return;
  const sym = (liveLast.data && liveLast.data.symbol) || $("#liveSymbol").value.trim().toUpperCase();
  if (ltcTool === "mark") {
    addUserMark(sym, { ts: p.ts, price: p.price, dir: $("#liveSide").value || "mark", t: Date.now() });
    if (typeof toast === "function") toast(`◉ Marked @ ${fmtPrice(p.price)}${snap ? " (" + snap.kind + ")" : ""}`, "buy");
    renderLiveTradeChart(liveLast.data, liveLast.kind);
  } else if (ltcTool === "line") {
    trendAnchor = { ts: p.ts, price: p.price, x: snap ? snap.x : x, y: snap ? snap.y : y };
    const hint = $("#ltcHint");
    if (hint) hint.textContent = `Target @ ${fmtPrice(p.price)}${snap ? " (" + snap.kind + ")" : ""} — press & drag anywhere to draw the trend`;
    renderLiveTradeChart(liveLast.data, liveLast.kind);
  }
}

function _onChartMouseDown(evt) {
  if (!liveLast.ok) return;
  const { x, y, pxPerSvgX, pxPerSvgY } = _svgEventToChart(evt);
  if (liveLast.geom) { liveLast.geom.pxPerSvgX = pxPerSvgX; liveLast.geom.pxPerSvgY = pxPerSvgY; }

  // Hit-test existing markers/endpoints first — works from ANY tool so Rob
  // can retouch a point without switching modes.
  const hit = _hitTestMarker(x, y);
  if (hit) {
    const sym = liveLast.data && liveLast.data.symbol;
    if (evt.altKey) {
      _deleteHit(hit, sym);
      suppressNextClick = true;
      renderLiveTradeChart(liveLast.data, liveLast.kind);
      evt.preventDefault();
      return;
    }
    editState = { kind: hit.kind, idx: hit.idx, sym };
    // Initialize the preview to the marker's current location so the first
    // mousemove has something to nudge from.
    if (hit.kind === "mark") editPreview = { ts: hit.mark.ts, price: hit.mark.price };
    else editPreview = { ts: hit.line[hit.kind === "lineA" ? "a" : "b"].ts,
                         price: hit.line[hit.kind === "lineA" ? "a" : "b"].price };
    evt.preventDefault();
    return;
  }

  // Otherwise, arm a potential trend-line drag.
  if (ltcTool === "line" && trendAnchor) {
    dragState = { startX: x, startY: y, moved: false };
    return;
  }
  // Default (no tool active, not editing a marker, not a hit): drag = pan.
  if (ltcTool === "none" && liveLast.geom) {
    panDrag = { startClientX: evt.clientX, startBar: liveLast.geom.viewStart, moved: false };
    const svg = $("#liveTradeChart");
    if (svg) svg.style.cursor = "grab";
    evt.preventDefault();
  }
}

function _scheduleDragRedraw() {
  if (_rafDrag) return;
  _rafDrag = requestAnimationFrame(() => {
    _rafDrag = 0;
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  });
}

function _onChartMouseUp(evt) {
  // Commit an in-flight edit of an existing marker/endpoint.
  if (editState) {
    _commitEdit();
    if (typeof toast === "function") toast("Adjusted", "buy");
    editState = null; editPreview = null;
    suppressNextClick = true;
    const svg = $("#liveTradeChart"); if (svg) svg.style.cursor = "";
    renderLiveTradeChart(liveLast.data, liveLast.kind);
    return;
  }
  // Finish a pan-drag. Suppress the trailing click so the mouseup doesn't
  // count as a click on empty chart space.
  if (panDrag) {
    const wasDrag = panDrag.moved;
    panDrag = null;
    const svg = $("#liveTradeChart"); if (svg) svg.style.cursor = "";
    if (wasDrag) suppressNextClick = true;
    return;
  }
  if (!dragState) return;
  const wasDrag = dragState.moved;
  const startedInLine = ltcTool === "line" && trendAnchor;
  dragState = null;
  if (!wasDrag) return;   // wasn't a drag — let the click handler run normally
  const { x, y } = _svgEventToChart(evt);
  // Snap the release endpoint for precise line drawing.
  const snap = altHeld ? null : _getSnapCandidate(x, y);
  const p = snap ? { ts: snap.ts, price: snap.price } : _pixelToTsPrice(x, y);
  const sym = (liveLast.data && liveLast.data.symbol) || $("#liveSymbol").value.trim().toUpperCase();
  if (startedInLine && p) {
    addUserLine(sym, {
      a: { ts: trendAnchor.ts, price: trendAnchor.price },
      b: { ts: p.ts, price: p.price },
      color: "var(--gold)", t: Date.now(),
    });
    if (typeof toast === "function") toast("╱ Trend line saved" + (snap ? " (snapped)" : ""), "buy");
  }
  trendDragging = false; trendPreview = null; trendAnchor = null;
  suppressNextClick = true;  // the release will also fire a `click` — swallow it
  const hint = $("#ltcHint");
  if (hint) hint.textContent = "Click target price → then press & drag to draw the trend";
  renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _onChartMove(evt) {
  if (!liveLast.ok) return;
  const { x, y, pxPerSvgX, pxPerSvgY } = _svgEventToChart(evt);
  // Cache scale so snap distance can be enforced in real screen pixels.
  if (liveLast.geom) { liveLast.geom.pxPerSvgX = pxPerSvgX; liveLast.geom.pxPerSvgY = pxPerSvgY; }
  _drawCrosshair(x, y);

  const svg = $("#liveTradeChart");

  // Pan-drag beats every other hover behavior — track pixel delta, translate
  // into full-tape bar units, and re-render on rAF.
  if (panDrag && liveLast.geom) {
    const rect = svg.getBoundingClientRect();
    const dxPx = evt.clientX - panDrag.startClientX;
    if (!panDrag.moved && Math.abs(dxPx) > DRAG_THRESHOLD_PX) {
      panDrag.moved = true;
      if (svg) svg.style.cursor = "grabbing";
    }
    if (panDrag.moved) {
      const g = liveLast.geom;
      const barsPerPx = g.n / Math.max(1, rect.width);
      const deltaBars = -Math.round(dxPx * barsPerPx);
      const nAll = g.nAll || (g.fullOhlc || []).length;
      const newStart = Math.max(0, Math.min(Math.max(0, nAll - g.viewCount), panDrag.startBar + deltaBars));
      chartView = { start: newStart, count: g.viewCount, pinned: (newStart + g.viewCount) >= nAll };
      _scheduleDragRedraw();
    }
    return;
  }

  // Cursor affordance: grab-hand when hovering an editable marker.
  if (svg && !editState && !dragState) {
    const hit = _hitTestMarker(x, y);
    if (hit) svg.style.cursor = evt.altKey ? "not-allowed" : "grab";
    else svg.style.cursor = ltcTool === "none" ? "grab" : "";
  }

  // Live-edit an existing marker/endpoint being dragged.
  if (editState) {
    const snap = altHeld ? null : _getSnapCandidate(x, y);
    const p = snap ? { ts: snap.ts, price: snap.price } : _pixelToTsPrice(x, y);
    editPreview = { ts: p.ts, price: p.price };
    if (svg) svg.style.cursor = "grabbing";
    _scheduleDragRedraw();
    return;
  }

  // Trend-line drag detection: press-and-drag while trend anchor exists.
  if (dragState && ltcTool === "line" && trendAnchor) {
    const dx = x - dragState.startX, dy = y - dragState.startY;
    if (!dragState.moved && (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX)) {
      dragState.moved = true;
      trendDragging = true;
      const a = _tsToXY(liveLast.geom, trendAnchor.ts, trendAnchor.price);
      trendPreview = {
        ax: a ? a.x : trendAnchor.x,
        ay: liveLast.geom.Y(trendAnchor.price),
        bx: x, by: y,
      };
    }
    if (dragState.moved && trendPreview) {
      // Snap the drag endpoint too, for precision line drawing.
      const snap = altHeld ? null : _getSnapCandidate(x, y);
      trendPreview.bx = snap ? snap.x : x;
      trendPreview.by = snap ? snap.y : y;
      _scheduleDragRedraw();
    }
  }
}
function _onChartLeave() { _clearCrosshair(); }

/* ---- Pan + zoom: viewport ops ------------------------------------------
   All coord math funnels through liveLast.geom, so pan/zoom just rewrites
   chartView and triggers a redraw. `pinned` re-latches to true whenever the
   right edge of the window touches the latest bar, so a user who zooms back
   in to "now" gets auto-follow again for free. */

function _panBars(deltaBars) {
  const g = liveLast.geom;
  if (!g) return;
  const nAll = g.nAll || (g.fullOhlc || []).length;
  const count = g.viewCount || g.n;
  if (!nAll || !count) return;
  const newStart = Math.max(0, Math.min(Math.max(0, nAll - count), g.viewStart + deltaBars));
  chartView = { start: newStart, count, pinned: (newStart + count) >= nAll };
  renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _zoomAtBar(anchorBarFull, factor) {
  const g = liveLast.geom;
  if (!g) return;
  const nAll = g.nAll || (g.fullOhlc || []).length;
  if (!nAll) return;
  const oldCount = g.viewCount || g.n;
  const newCount = Math.max(MIN_VISIBLE_BARS, Math.min(nAll, Math.round(oldCount * factor)));
  if (newCount === oldCount) return;
  // Keep the bar under the cursor at the same fractional x position.
  const relCursor = oldCount <= 1 ? 0.5 : (anchorBarFull - g.viewStart) / (oldCount - 1);
  const newStart = Math.max(0, Math.min(Math.max(0, nAll - newCount),
    Math.round(anchorBarFull - relCursor * (newCount - 1))));
  chartView = { start: newStart, count: newCount, pinned: (newStart + newCount) >= nAll };
  renderLiveTradeChart(liveLast.data, liveLast.kind);
}

function _onChartWheel(evt) {
  if (!liveLast.ok || !liveLast.geom) return;
  evt.preventDefault();
  const g = liveLast.geom;
  const svg = $("#liveTradeChart");
  const rect = svg.getBoundingClientRect();
  const relX = Math.max(0, Math.min(1, (evt.clientX - rect.left) / rect.width));
  const cursorBarInView = Math.round(relX * Math.max(0, g.n - 1));
  _wheelAnchorBarFull = g.viewStart + cursorBarInView;
  _wheelIsPan = evt.shiftKey || Math.abs(evt.deltaX) > Math.abs(evt.deltaY);
  // Accumulate raw delta; a single rAF-scheduled callback drains it. Multiple
  // wheel events between frames collapse into one gentle step.
  _wheelAccum += _wheelIsPan
    ? (evt.shiftKey ? evt.deltaY : evt.deltaX)
    : evt.deltaY;
  if (_wheelRaf) return;
  _wheelRaf = requestAnimationFrame(_drainWheel);
}

function _drainWheel() {
  _wheelRaf = 0;
  const delta = _wheelAccum;
  _wheelAccum = 0;
  if (!liveLast.geom) return;
  const g = liveLast.geom;
  if (_wheelIsPan) {
    const svg = $("#liveTradeChart");
    const rect = svg.getBoundingClientRect();
    const barsPerPx = Math.max(0.02, g.n / rect.width);
    const step = Math.round(delta * barsPerPx / 3);
    if (step !== 0) _panBars(step);
    return;
  }
  // Gentle exponential zoom: 100 units of delta ≈ 4% zoom step. Multi-event
  // trackpad bursts still add up smoothly instead of stair-stepping.
  const factor = Math.exp(delta * 0.0004);
  const clamped = Math.min(2.5, Math.max(0.4, factor));
  _zoomAtBar(_wheelAnchorBarFull, clamped);
}

function _onChartDblClick(evt) {
  evt.preventDefault();
  if (liveLast.ok && liveLast.data) { resetChartView(); renderLiveTradeChart(liveLast.data, liveLast.kind); }
}

function _toggleFullscreen() {
  const card = $("#liveTradeCard");
  if (!card) return;
  const apply = () => {
    const on = card.classList.toggle("is-fullscreen");
    document.body.classList.toggle("mp-lock-scroll", on);
    const btn = $("#ltcFullBtn");
    if (btn) btn.textContent = on ? "⤢ Exit" : "⛶ Fullscreen";
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  };
  // View Transitions API gives a butter-smooth cross-fade + size morph
  // on Chromium; graceful fallback keeps other browsers working.
  if (document.startViewTransition) document.startViewTransition(apply);
  else apply();
}

function initLiveChartInteractions() {
  const svg = $("#liveTradeChart");
  if (!svg || svg.dataset.wired === "1") return;
  svg.dataset.wired = "1";
  svg.addEventListener("click", _onChartClick);
  svg.addEventListener("mousedown", _onChartMouseDown);
  svg.addEventListener("mousemove", _onChartMove);
  svg.addEventListener("mouseleave", _onChartLeave);
  // Mouseup on window (not just SVG) so a drag that releases outside the chart still commits.
  window.addEventListener("mouseup", _onChartMouseUp);
  svg.addEventListener("dblclick", _onChartDblClick);
  // Wheel-to-zoom / shift-wheel-to-pan. passive:false so preventDefault
  // suppresses the page's own scroll while the cursor is over the chart.
  svg.addEventListener("wheel", _onChartWheel, { passive: false });
  document.querySelectorAll(".ltc-tool[data-tool]").forEach((b) =>
    b.addEventListener("click", () => _setTool(b.dataset.tool)));
  const undo = $("#ltcUndo");
  if (undo) undo.addEventListener("click", () => {
    const sym = ($("#liveSymbol").value || "").trim().toUpperCase();
    const what = popUserLast(sym);
    if (what && liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
    if (typeof toast === "function") toast(what ? `Undid ${what}` : "Nothing to undo");
  });
  const clr = $("#ltcClear");
  if (clr) clr.addEventListener("click", () => {
    const sym = ($("#liveSymbol").value || "").trim().toUpperCase();
    if (!confirm(`Clear all marks & trend lines for ${sym}?`)) return;
    clearUserAll(sym);
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  });
  const full = $("#ltcFullBtn");
  if (full) full.addEventListener("click", _toggleFullscreen);
  const fit = $("#ltcFit");
  if (fit) fit.addEventListener("click", () => {
    resetChartView();
    if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Alt") { altHeld = true; }
    if (e.key === "Escape") {
      if (editState) { editState = null; editPreview = null; renderLiveTradeChart(liveLast.data, liveLast.kind); return; }
      if (trendAnchor || trendDragging) {
        trendAnchor = null; trendDragging = false; trendPreview = null;
        if (liveLast.data) renderLiveTradeChart(liveLast.data, liveLast.kind);
        return;
      }
      if ($("#liveTradeCard").classList.contains("is-fullscreen")) _toggleFullscreen();
    }
    if (e.key === "m" || e.key === "M") _setTool(ltcTool === "mark" ? "none" : "mark");
    if (e.key === "l" || e.key === "L") _setTool(ltcTool === "line" ? "none" : "line");
  });
  window.addEventListener("keyup", (e) => {
    if (e.key === "Alt") { altHeld = false; }
  });
  window.addEventListener("blur", () => { altHeld = false; });
  _setTool("none");
}

/* ----------------------------------------------------- dca wizard */

let dcaLoaded = false;

const DCA_LABEL = { plain: "Plain DCA", tilt: "Signal-Tilt DCA", lump: "Lump Sum" };

// QuickFill for the DCA per-period contribution — readout shows annualized $.
let dcaMonthlyQf = null;
function ensureDcaQf() {
  if (dcaMonthlyQf || typeof QuickFill === "undefined") return;
  const el = $("#dcaMonthlyQf");
  if (!el) return;
  dcaMonthlyQf = QuickFill.mount(el, {
    amount: 200, chips: [50, 100, 200, 500, 1000], step: 25, min: 10,
    convert: (amt) => {
      const cad = $("#dcaCadence").value;
      const perYr = cad === "weekly" ? 52 : cad === "biweekly" ? 26 : 12;
      const annual = Math.round(amt * perYr);
      return `$${Math.round(amt)} ${cad} = <b>$${annual.toLocaleString()}/yr</b> invested`;
    },
  });
  $("#dcaCadence").addEventListener("change", () => dcaMonthlyQf && dcaMonthlyQf.refreshConversion());
}

async function loadDca() {
  const symbol = ($("#dcaSymbol").value.trim() || "NVDA");
  const kind = $("#dcaKind").value;
  const monthly = dcaMonthlyQf ? dcaMonthlyQf.getAmount() : 200;
  const cadence = $("#dcaCadence").value;
  const years = parseFloat($("#dcaYears").value) || 10;
  $("#dcaCards").innerHTML = `<div class="proof-empty">Backtesting ${esc(symbol)} DCA over ~2 years, after costs…</div>`;
  ["dcaNudge", "dcaPlan", "dcaVerdict", "dcaProj"].forEach((id) => { $("#" + id).innerHTML = ""; });
  $("#dcaChart").innerHTML = "";
  try {
    const qs = new URLSearchParams({ symbol, kind, monthly, cadence, years });
    const d = await (await fetch(`/api/dca?${qs}`)).json();
    if (d.error) {
      $("#dcaCards").innerHTML = `<div class="proof-empty">Couldn’t build ${esc(symbol)}: ${esc(d.error)}</div>`;
      return;
    }
    renderDca(d);
  } catch (err) {
    $("#dcaCards").innerHTML = `<div class="proof-empty">Error: ${esc(err.message)}</div>`;
  }
}

function dcaCard(key, x, win) {
  const rc = (x.return_pct ?? 0) >= 0 ? "up" : "down";
  const ret = x.return_pct == null ? "—" : `${x.return_pct > 0 ? "+" : ""}${x.return_pct}%`;
  return `<div class="dca-card ${win ? "win" : ""}">
    <div class="dc-name">${DCA_LABEL[key]}${win ? ` <span class="dc-crown">▲ won</span>` : ""}</div>
    <div class="dc-val ${rc}">${ret}</div>
    <div class="dc-sub">${potMoney(x.invested)} in → <b>${potMoney(x.final_value)}</b></div>
    <div class="dc-meta">avg cost ${fmtPrice(x.avg_cost)} · ${x.periods} buy${x.periods === 1 ? "" : "s"} · worst paper dip ${x.max_paper_dd_pct}%</div>
  </div>`;
}

function renderDca(d) {
  const b = d.backtest, v = d.verdict, p = d.plan, rg = d.regime, n = d.nudge;

  const ncls = n.tilt > 1.05 ? "bullish" : n.tilt < 0.95 ? "bearish" : "stand-aside";
  $("#dcaNudge").innerHTML = `<div class="nudge ${ncls}">
    <span class="nudge-ic">${n.icon || ""}</span>
    <span class="nudge-body"><b>${esc(n.headline)}</b> ${esc(n.text)}</span></div>`;

  $("#dcaPlan").innerHTML = `<div class="dca-planbar">
    <span><b>${potMoney(p.per_period)}</b> every ${esc(p.cadence)}</span>
    <span>${p.periods_per_year}×/yr</span>
    <span>backtest window: ${p.window_periods} buys · ${potMoney(p.window_budget)} deployed</span></div>`;

  const win = v.winner_by_return;
  $("#dcaCards").innerHTML =
    dcaCard("plain", b.plain, win === "plain") +
    dcaCard("tilt", b.tilt, win === "tilt") +
    dcaCard("lump", b.lump, win === "lump");

  const tiltTxt = v.tilt_vs_plain_pct == null ? "—"
    : `${v.tilt_vs_plain_pct > 0 ? "+" : ""}${v.tilt_vs_plain_pct} pts`;
  $("#dcaVerdict").innerHTML = `<div class="dca-vbox">
    <div class="dv-head">📊 Regime: <b>${rg.tag.toUpperCase()}</b>
      (${rg.move_pct > 0 ? "+" : ""}${rg.move_pct}% over window) · winner per-dollar:
      <b>${DCA_LABEL[win]}</b></div>
    <div class="dv-note">${esc(v.regime_note)}</div>
    <div class="dv-tilt ${v.tilt_helped ? "good" : "bad"}">Signal-tilt vs plain DCA:
      <b>${tiltTxt}</b> — ${v.tilt_helped
        ? "the tilt added value on this asset & window."
        : "the tilt did NOT beat plain DCA here (the engine’s “cheap” kept moving the same way)."}</div>
    <div class="dv-truth">${esc(v.honest_truth)}</div>
    <div class="dv-truth sub">${esc(v.same_dollars_note)}</div>
  </div>`;

  renderMoneyMap(d.series, b);
  renderDcaChart(d.series, b.tilt.contributions);
  renderProjGrowth(d.projection);

  const pj = d.projection, sc = pj.scenarios;
  const pcard = (cls, label, o) => `<div class="pj-card ${cls}">
    <div class="pj-name">${label} <i>${o.annual_rate_pct}%/yr</i></div>
    <div class="pj-val">${potMoney(o.future_value)}</div>
    <div class="pj-sub">+${potMoney(o.growth)} growth</div></div>`;
  $("#dcaProj").innerHTML = `<div class="pj-head">🌱 Keep it up ${pj.years} yr —
      ${potMoney(pj.per_period)}/period × ${pj.periods} = <b>${potMoney(pj.contributed)}</b> contributed</div>
    <div class="pj-cards">${pcard("bear", "Bear", sc.bear)}${pcard("base", "Base", sc.base)}${pcard("bull", "Bull", sc.bull)}</div>
    <div class="pj-disc">${esc(pj.disclaimer)}</div>`;
}

function renderDcaChart(series, contribs) {
  const svg = $("#dcaChart");
  const closes = series.closes, W = 1000, H = 280, pad = 8;
  if (!closes || closes.length < 2) { svg.innerHTML = ""; return; }
  const min = Math.min(...closes), max = Math.max(...closes), span = max - min || 1;
  const X = (i) => pad + (i / (closes.length - 1)) * (W - pad * 2);
  const Y = (v) => pad + (1 - (v - min) / span) * (H - pad * 2);
  const line = closes.map((c, i) => `${X(i).toFixed(1)},${Y(c).toFixed(1)}`).join(" ");
  const dm = new Map(series.dates.map((dt, i) => [dt, i]));
  // Each dot = a tilt buy. Bigger + greener = the engine leaned IN (cheaper);
  // smaller + red = it eased off (richer). Amber = a flat ~1.0x buy.
  const dots = (contribs || []).map((c) => {
    const i = dm.get(c.date);
    if (i == null) return "";
    const col = c.tilt > 1.05 ? "var(--buy)" : c.tilt < 0.95 ? "var(--sell)" : "#c9a227";
    const r = (3 + (c.tilt - 0.5) * 2.4).toFixed(1);
    return `<circle cx="${X(i).toFixed(1)}" cy="${Y(c.price).toFixed(1)}" r="${r}"
      fill="${col}" fill-opacity="0.85" stroke="#0a0d12" stroke-width="1">
      <title>${c.date} · $${c.amount} (${c.tilt}× tilt) @ ${fmtPrice(c.price)}</title></circle>`;
  }).join("");
  svg.innerHTML = `<polyline points="${line}" fill="none" stroke="#4aa3ff" stroke-width="1.9" stroke-linejoin="round"/>${dots}`;
}

// "Where your money SITS" — cost paid in (gray area) vs each strategy's holdings
// value over the window. A value line above the gray = profit; below = underwater.
const DCA_COLORS = { invested: "#7d8b9c", plain: "var(--buy)", tilt: "var(--gold)", lump: "#5b8def" };

function renderMoneyMap(series, b) {
  const svg = $("#dcaGrowth");
  const invested = b.plain.invested_curve || [];
  const curves = { plain: b.plain.value_curve || [], tilt: b.tilt.value_curve || [], lump: b.lump.value_curve || [] };
  const n = curves.plain.length;
  if (!n) { svg.innerHTML = ""; $("#dcaGrowthLegend").innerHTML = ""; return; }
  const W = 1000, H = 280, pad = 8;
  const all = [...invested, ...curves.plain, ...curves.tilt, ...curves.lump];
  const max = Math.max(...all, 1), span = max || 1;
  const X = (i) => pad + (i / (n - 1)) * (W - pad * 2);
  const Y = (v) => pad + (1 - v / span) * (H - pad * 2);
  const pts = (arr) => arr.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const investedArea = `${pad},${H} ${pts(invested)} ${W - pad},${H}`;
  const poly = (arr, color, w) =>
    `<polyline points="${pts(arr)}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linejoin="round"/>`;
  // Gray "money in" fill first, then value lines on top (tilt gold drawn last).
  svg.innerHTML =
    `<polygon points="${investedArea}" fill="#3a4757" fill-opacity="0.28"/>` +
    poly(invested, DCA_COLORS.invested, 1.9) +
    poly(curves.lump, DCA_COLORS.lump, 2.2) +
    poly(curves.plain, DCA_COLORS.plain, 2.4) +
    poly(curves.tilt, DCA_COLORS.tilt, 2.8);
  const chip = (c, t) => `<span class="lg"><i style="background:${c}"></i>${t}</span>`;
  $("#dcaGrowthLegend").innerHTML =
    chip(DCA_COLORS.invested, "money in") + chip(DCA_COLORS.plain, "Plain") +
    chip(DCA_COLORS.tilt, "Tilt") + chip(DCA_COLORS.lump, "Lump");
}

// "Where it's GOING" — forward projection: money contributed (gray area) vs the
// compounding value, with a bear→bull band and the base case as the gold line.
function renderProjGrowth(pj) {
  const svg = $("#dcaProjChart");
  const c = pj.curve || [];
  if (c.length < 2) { svg.innerHTML = ""; return; }
  const W = 1000, H = 280, pad = 8;
  const max = Math.max(...c.map((p) => p.bull), 1), span = max || 1;
  const X = (i) => pad + (i / (c.length - 1)) * (W - pad * 2);
  const Y = (v) => pad + (1 - v / span) * (H - pad * 2);
  const line = (key) => c.map((p, i) => `${X(i).toFixed(1)},${Y(p[key]).toFixed(1)}`).join(" ");
  const contribArea = `${pad},${H} ${line("contributed")} ${W - pad},${H}`;
  const bandTop = c.map((p, i) => `${X(i).toFixed(1)},${Y(p.bull).toFixed(1)}`).join(" ");
  const bandBot = c.map((p, i) => ({ i, p })).reverse()
    .map(({ i, p }) => `${X(i).toFixed(1)},${Y(p.bear).toFixed(1)}`).join(" ");
  svg.innerHTML =
    `<polygon points="${bandTop} ${bandBot}" fill="var(--buy)" fill-opacity="0.10"/>` +
    `<polygon points="${contribArea}" fill="#3a4757" fill-opacity="0.32"/>` +
    `<polyline points="${line("bear")}" fill="none" stroke="var(--sell)" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.9"/>` +
    `<polyline points="${line("bull")}" fill="none" stroke="var(--buy)" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.9"/>` +
    `<polyline points="${line("contributed")}" fill="none" stroke="#9fb0c2" stroke-width="1.9"/>` +
    `<polyline points="${line("base")}" fill="none" stroke="var(--gold)" stroke-width="2.6"/>`;
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

/* Reusable candlestick SVG. ohlc = [[open,high,low,close], ...].
   Bright green up / red down bodies + wicks, auto-scaled. Returns markup. */
function candlesSVG(ohlc, W, H, pad) {
  const highs = ohlc.map((b) => b[1]), lows = ohlc.map((b) => b[2]);
  const min = Math.min(...lows), max = Math.max(...highs), span = max - min || 1;
  const n = ohlc.length;
  const X = (i) => pad + (n === 1 ? 0.5 : i / (n - 1)) * (W - pad * 2);
  const Y = (v) => pad + (1 - (v - min) / span) * (H - pad * 2);
  const slot = (W - pad * 2) / n;
  const bw = Math.max(1, Math.min(slot * 0.7, 9));      // candle body width
  const wick = Math.max(0.6, Math.min(bw * 0.28, 2));   // wick thickness
  let out = "";
  for (let i = 0; i < n; i++) {
    const [o, h, l, c] = ohlc[i];
    const up = c >= o;
    const col = up ? "var(--buy)" : "var(--sell)";
    const x = X(i);
    const yH = Y(h), yL = Y(l);
    const yO = Y(o), yC = Y(c);
    const top = Math.min(yO, yC), bot = Math.max(yO, yC);
    const bodyH = Math.max(1, bot - top);
    out += `<line x1="${x.toFixed(1)}" y1="${yH.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yL.toFixed(1)}" stroke="${col}" stroke-width="${wick.toFixed(2)}"/>`;
    out += `<rect x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${col}" rx="0.5"/>`;
  }
  return { markup: out, X, Y };
}

function renderProofChart(series, events) {
  const svg = $("#proofChart");
  const closes = series.closes, W = 1000, H = 280, pad = 10;
  if (!closes || closes.length < 2) { svg.innerHTML = ""; return; }

  let X, Y, base;
  if (series.ohlc && series.ohlc.length === closes.length) {
    // Real candlesticks (stocks) — bright green up / red down.
    const c = candlesSVG(series.ohlc, W, H, pad);
    X = c.X; Y = c.Y; base = c.markup;
  } else {
    // Bright price line (crypto / no-OHLC) — no more dim gray.
    const min = Math.min(...closes), max = Math.max(...closes), span = max - min || 1;
    X = (i) => pad + (i / (closes.length - 1)) * (W - pad * 2);
    Y = (v) => pad + (1 - (v - min) / span) * (H - pad * 2);
    const line = closes.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
    base = `<polyline points="${line}" fill="none" stroke="#4aa3ff" stroke-width="2.2" stroke-linejoin="round"/>`;
  }

  const marks = events.map((e) => {
    const x = X(e.idx), y = Y(e.price);
    const buy = e.dir === "buy";
    const col = buy ? "var(--buy)" : "var(--sell)";
    // hollow ring so it reads clearly on top of candles
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5.5" fill="none"
      stroke="${col}" stroke-width="2.5"><title>${e.date} ${e.type}</title></circle>`;
  }).join("");
  svg.innerHTML = base + marks;
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

  // Quick-load presets — swap the Stocks watchlist to a curated universe.
  const loadPreset = (list) => {
    state.stockSyms = [...list];
    store.set("mp_stock_syms", state.stockSyms);
    setView("stocks");
  };
  const addPreset = (list, label, title) => {
    if (!list || !list.length) return;
    const btn = document.createElement("button");
    btn.className = "add-btn ghost";
    btn.type = "button";
    btn.textContent = label;
    btn.title = title;
    btn.addEventListener("click", () => loadPreset(list));
    document.querySelector(".add-form").appendChild(btn);
  };
  addPreset(defaults.ai, "🤖 AI names", "Load the AI Come-Up universe (apply the method — not a buy list)");
  addPreset(defaults.africa, "🌍 Africa (JSE)", "Load Johannesburg Stock Exchange tickers");

  $("#tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) setView(btn.dataset.view);
  });
  $("#refreshBtn").addEventListener("click", loadView);
  $("#autoRefresh").addEventListener("change", startAuto);

  // Click any ticker header on the grid or the cockpit's live card → jump to
  // that symbol's live chart. Handler is delegated so it survives re-renders.
  const onTapLive = (e) => {
    const tap = e.target.closest(".sym-tap");
    if (!tap) return;
    if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    openLiveFor(tap.dataset.liveKind, tap.dataset.liveSym);
  };
  $("#grid").addEventListener("click", onTapLive);
  $("#grid").addEventListener("keydown", onTapLive);
  $("#homePanel").addEventListener("click", onTapLive);
  $("#homePanel").addEventListener("keydown", onTapLive);
  $("#addForm").addEventListener("submit", (e) => {
    e.preventDefault();
    addSymbol($("#addInput").value);
    $("#addInput").value = "";
  });
  $("#proofForm").addEventListener("submit", (e) => { e.preventDefault(); runProof(); });
  $("#dcaForm").addEventListener("submit", (e) => { e.preventDefault(); dcaLoaded = true; loadDca(); });
  $("#dcaSavePlan").addEventListener("click", saveDcaPlan);
  $("#liveForm").addEventListener("submit", (e) => { e.preventDefault(); pinLive(); });

  // Cockpit / Home wiring
  $("#homeNewPlan").addEventListener("click", () => setView("dca"));
  $("#homeExport").addEventListener("click", exportData);
  $("#homeImport").addEventListener("click", () => $("#homeImportFile").click());
  $("#homeImportFile").addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) importData(e.target.files[0]);
  });
  $("#homePanel").addEventListener("click", (e) => {
    const link = e.target.closest("[data-goto]");
    if (link) setView(link.dataset.goto);
  });
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

  // Deep-link support for PWA home-screen shortcuts (e.g. /?view=dca).
  const VIEWS = ["home", "crypto", "stocks", "options", "watchlist", "pot", "dca", "live", "proof"];
  const wanted = new URLSearchParams(location.search).get("view");
  const initial = (wanted && VIEWS.includes(wanted)) ? wanted : state.view;
  // Activate the initial view. Home is a panel, so it needs setView to hide the
  // grid + render the cockpit; setView also drives loadView() for grid views.
  setView(initial);
}

init();
