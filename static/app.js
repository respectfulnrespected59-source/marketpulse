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
  if (p >= 0.01) return "$" + p.toFixed(4);
  // Sub-penny coins: a fixed 6dp renders PEPE at ~$0.0000027 as "$0.000003",
  // hiding the digits that actually move. Keep four significant ones instead.
  if (p > 0) {
    const leadingZeros = Math.max(0, Math.floor(-Math.log10(p)));
    return "$" + p.toFixed(Math.min(12, leadingZeros + 4));
  }
  return "$" + p.toFixed(6);
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
  // A missing body used to render the literal string "undefined" on screen.
  // Both fields are escaped: some callers pass a symbol the user typed.
  t.innerHTML = `<b>${esc(title)}</b>` + (body ? `<span>${esc(body)}</span>` : "");
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 7000);
}

/* ----------------------------------------------------- add symbol */

function pinSymbol(symbol, kind) {
  if (kind === "stock") {
    const sym = symbol.toUpperCase();
    state.stockSyms = [...new Set([...(state.stockSyms || defaults.stocks), sym])];
    store.set("mp_stock_syms", state.stockSyms);
  } else {
    const id = symbol.toLowerCase();
    state.cryptoIds = [...new Set([...(state.cryptoIds || defaults.crypto), id])];
    store.set("mp_crypto_ids", state.cryptoIds);
  }
  loadView();
}

/* Add whatever the user typed, resolving it against what the venues actually
 * list. The old version guessed from a 1-6 letter regex, so anything with a
 * digit or a longer name landed in the wrong bucket and quietly showed nothing.
 * We ask the server first and fall back to the current view if it can't say. */
async function addSymbol(raw) {
  const v = (raw || "").trim();
  if (!v) return;

  const viewKind = state.view === "stocks" ? "stock" : "crypto";
  try {
    setStatus(`Looking up ${v}…`);
    const res = await fetch(`/api/search?q=${encodeURIComponent(v)}`);
    const data = await res.json();
    const hits = (data && data.results) || [];

    // Prefer an exact ticker match, and among ties respect the view the user
    // is standing in — on the Stocks tab, "ETH" means the stock if one exists.
    const exact = hits.filter((h) => h.symbol.toUpperCase() === v.toUpperCase());
    const pick =
      exact.find((h) => h.kind === viewKind) || exact[0] ||
      hits.find((h) => h.kind === viewKind) || hits[0];

    if (pick) {
      setStatus(`Added ${pick.symbol} — ${pick.name}`);
      pinSymbol(pick.symbol, pick.kind);
      return;
    }
    setStatus(`No market found for "${v}"`);
  } catch (err) {
    // Search is a convenience; if it's down, honour what the user typed.
    setStatus("");
  }
  pinSymbol(v, viewKind);
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
  const isPaper = v === "paper";
  const isCoach = v === "coach";
  const isPanel = isHome || isProof || isOpt || isPot || isDca || isLive || isPaper || isCoach;
  $("#homePanel").hidden = !isHome;
  $("#proofPanel").hidden = !isProof;
  $("#optionsPanel").hidden = !isOpt;
  $("#potPanel").hidden = !isPot;
  $("#dcaPanel").hidden = !isDca;
  $("#livePanel").hidden = !isLive;
  $("#paperPanel").hidden = !isPaper;
  $("#coachPanel").hidden = !isCoach;
  $("#grid").hidden = isPanel;
  document.querySelector(".controls").hidden = isPanel;
  document.querySelector(".breadth").hidden = isPanel;
  if (!isLive) { stopLivePoll(); stopChartPoll(); }  // don't poll while off the Live tab
  if (isHome) { renderHome(); return; }
  // Recomputed on every visit rather than cached: the record changes whenever
  // a call is made on the Live tab, and a stale grade is worse than none.
  if (isCoach) { renderCoach(); return; }
  // The paper run keeps polling when you leave the tab — a strategy that only
  // trades while you're watching it isn't testing anything.
  if (isPaper) { initPaper(); renderPaper(); return; }
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
