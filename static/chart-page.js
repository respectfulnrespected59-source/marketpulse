/* MarketPulse — the full-screen chart page, /chart.
 *
 * The page is the app shell with everything except the chart put away: same
 * scripts, same chart, same replay and Learning Mode, behind one URL a trader
 * can bookmark or share (/chart?symbol=NVDA&kind=stock&tf=5m). The Live tab
 * keeps a compact copy of the same chart, and its "Full chart" button opens
 * this page. index.html sets the `mode-chart` class before first paint so the
 * app layout never flashes on the way in.
 *
 * Classic script; loaded after chart.js (it reads TF_ORDER and liveTf) and
 * before app.js, whose init() calls bootChartPage() on this path.
 */

const CHART_PAGE = /^\/chart\/?$/.test(location.pathname);
// Tickers and coin ids as the app writes them: NVDA, BRK-B, NPN.JO, ^GSPC,
// avalanche-2. Anything else in the URL falls back to a default symbol.
const CHART_SYMBOL_RE = /^[A-Za-z0-9.^=-]{1,32}$/;

function chartPageUrl(sym, kind, tf) {
  const q = new URLSearchParams({ symbol: String(sym || ""), kind: kind === "crypto" ? "crypto" : "stock" });
  if (tf) q.set("tf", tf);
  return `/chart?${q}`;
}

/* chart.js calls this whenever the symbol or timeframe on screen changes, so
 * the address bar always describes the chart and a refresh reopens it. */
function onChartIdentity(sym, kind, tf) {
  if (!CHART_PAGE) return;
  const typed = ($("#liveSymbol").value || "").trim() || sym;
  history.replaceState(null, "", chartPageUrl(typed, kind, tf));
  document.title = `${String(typed).toUpperCase()} · ${tf} chart · MarketPulse`;
}

/* The toolbar's expand button: from the Live tab it opens this page; on this
 * page it takes the chart truly full-screen (Esc hands the screen back). */
function chartExpand() {
  if (!CHART_PAGE) {
    location.href = chartPageUrl(($("#liveSymbol").value || "").trim(), $("#liveKind").value, liveTf);
    return;
  }
  const card = $("#liveTradeCard");
  if (document.fullscreenElement) { document.exitFullscreen().catch(() => {}); return; }
  if (card && card.requestFullscreen) {
    card.requestFullscreen().catch(() => toast("", "This browser won't go full screen here"));
  }
}

function _syncFullscreenLabel() {
  const lbl = $("#ltcFullLbl");
  if (lbl && CHART_PAGE) lbl.textContent = document.fullscreenElement ? "Exit" : "Fullscreen";
}

/* Read the URL, seed the Live tab's inputs from it, and open the chart. */
function bootChartPage() {
  const q = new URLSearchParams(location.search);
  const kind = q.get("kind") === "crypto" ? "crypto" : "stock";
  const raw = (q.get("symbol") || "").trim();
  const sym = CHART_SYMBOL_RE.test(raw) ? raw : (kind === "crypto" ? "bitcoin" : "NVDA");
  const tf = q.get("tf");
  if (tf && TF_ORDER.includes(tf)) liveTf = tf;
  $("#liveSymbol").value = kind === "crypto" ? sym.toLowerCase() : sym.toUpperCase();
  $("#liveKind").value = kind;
  document.documentElement.classList.add("mode-chart");
  const full = $("#ltcFullBtn");
  if (full) {
    full.title = "Fill the whole screen (Esc to leave)";
    full.setAttribute("aria-label", "Full screen");
  }
  _syncFullscreenLabel();
  document.addEventListener("fullscreenchange", _syncFullscreenLabel);
  setView("live");
}
