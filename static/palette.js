/* MarketPulse — quick search: Ctrl+K (Cmd+K on a Mac), or "/".
 *
 * Type a ticker, a company name or a coin and jump straight to its chart. When
 * the chart is already on screen (Live tab or the /chart page) it switches in
 * place; from anywhere else it opens the chart page. Empty, it offers what you
 * opened recently and a few liquid names. Results come from /api/search, the
 * same lookup the watchlist's "add" box uses.
 *
 * Classic script; nothing runs at load except the one global key listener.
 */

const PAL_RECENT_KEY = "mp_recent_syms";
const PAL_RECENT_MAX = 6;
const PAL_DEBOUNCE_MS = 140;
const PAL_POPULAR = [
  { symbol: "NVDA", kind: "stock", name: "NVIDIA Corporation" },
  { symbol: "TSLA", kind: "stock", name: "Tesla, Inc." },
  { symbol: "AAPL", kind: "stock", name: "Apple Inc." },
  { symbol: "SPY", kind: "stock", name: "SPDR S&P 500 ETF" },
  { symbol: "BTC", kind: "crypto", name: "Bitcoin" },
  { symbol: "ETH", kind: "crypto", name: "Ethereum" },
  { symbol: "SOL", kind: "crypto", name: "Solana" },
];

let pal = null;   // { root, input, list, items, active, timer, seq, returnFocus }

function _palRecent() {
  try {
    const v = JSON.parse(localStorage.getItem(PAL_RECENT_KEY) || "[]");
    return Array.isArray(v) ? v.filter((r) => r && r.symbol && r.kind).slice(0, PAL_RECENT_MAX) : [];
  } catch (e) { return []; }
}

function _palRemember(item) {
  const key = (r) => `${r.kind}:${String(r.symbol).toUpperCase()}`;
  const next = [{ symbol: item.symbol, kind: item.kind, name: item.name || "" },
                ..._palRecent().filter((r) => key(r) !== key(item))].slice(0, PAL_RECENT_MAX);
  try { localStorage.setItem(PAL_RECENT_KEY, JSON.stringify(next)); } catch (e) { /* private mode */ }
}

function _palBuild() {
  const root = document.createElement("div");
  root.className = "pal-backdrop";
  root.hidden = true;
  root.innerHTML = `
    <div class="pal" role="dialog" aria-modal="true" aria-label="Search markets">
      <div class="pal-head">
        <i class="mi mi-search" aria-hidden="true"></i>
        <input class="pal-input" type="text" role="combobox" aria-expanded="true"
               aria-controls="palList" aria-autocomplete="list" autocomplete="off"
               spellcheck="false" maxlength="64"
               placeholder="Search a stock or coin: NVDA, Tesla, bitcoin…" />
        <kbd>Esc</kbd>
      </div>
      <ul class="pal-list" id="palList" role="listbox" aria-label="Results"></ul>
      <div class="pal-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open chart</span><span class="pal-status" role="status"></span></div>
    </div>`;
  document.body.appendChild(root);
  const input = root.querySelector(".pal-input");
  const list = root.querySelector(".pal-list");
  root.addEventListener("pointerdown", (e) => { if (e.target === root) closePalette(); });
  input.addEventListener("input", () => _palQueue(input.value));
  input.addEventListener("keydown", _palKeys);
  list.addEventListener("pointermove", (e) => {
    const li = e.target.closest("[data-i]");
    if (li) _palActivate(Number(li.dataset.i));
  });
  list.addEventListener("click", (e) => {
    const li = e.target.closest("[data-i]");
    if (li) _palChoose(pal.items[Number(li.dataset.i)]);
  });
  return { root, input, list, status: root.querySelector(".pal-status"),
           items: [], active: 0, timer: 0, seq: 0, returnFocus: null };
}

function openPalette() {
  if (!pal) pal = _palBuild();
  pal.returnFocus = document.activeElement;
  pal.root.hidden = false;
  document.documentElement.classList.add("pal-open");
  pal.input.value = "";
  _palShowDefaults();
  pal.input.focus();
}

function closePalette() {
  if (!pal || pal.root.hidden) return;
  clearTimeout(pal.timer);
  pal.timer = 0;
  pal.seq++;                                   // drop any search still in flight
  pal.root.hidden = true;
  document.documentElement.classList.remove("pal-open");
  const back = pal.returnFocus;
  if (back && typeof back.focus === "function" && document.contains(back)) back.focus();
}

function _palShowDefaults() {
  const recent = _palRecent();
  const seen = new Set(recent.map((r) => `${r.kind}:${String(r.symbol).toUpperCase()}`));
  const popular = PAL_POPULAR.filter((r) => !seen.has(`${r.kind}:${r.symbol}`));
  const sections = [];
  if (recent.length) sections.push({ title: "Recent", items: recent });
  sections.push({ title: "Popular", items: popular });
  _palRender(sections);
  pal.status.textContent = "";
}

function _palQueue(raw) {
  clearTimeout(pal.timer);
  pal.timer = 0;
  const q = raw.trim();
  if (!q) { pal.seq++; _palShowDefaults(); return; }
  pal.timer = setTimeout(() => { pal.timer = 0; _palSearch(q); }, PAL_DEBOUNCE_MS);
}

async function _palSearch(q) {
  const seq = ++pal.seq;
  pal.status.textContent = "Searching…";
  let hits = [];
  let failed = false;
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    if (!res.ok) throw new Error(`server said ${res.status}`);
    const data = await res.json();
    hits = Array.isArray(data.results) ? data.results : [];
  } catch (e) {
    failed = true;
  }
  if (seq !== pal.seq) return false;           // a newer keystroke owns the list now
  const typed = q.toUpperCase();
  const items = hits.slice(0, 10);
  // Search is a convenience. When it finds nothing, or is down, still let the
  // trader open exactly what they typed.
  if (CHART_SYMBOL_RE.test(q) && !items.length) {
    items.push({ symbol: typed, kind: "stock", name: `Open "${typed}" as typed`, typed: true });
  }
  _palRender([{ title: failed ? "Search is unavailable" : "Results", items }]);
  pal.status.textContent = failed ? "Couldn't reach search" : (hits.length ? "" : "No matches");
  return true;
}

/* Every string here came from the network or the user, so all of it is escaped. */
function _palRender(sections) {
  pal.items = [];
  let html = "";
  for (const sec of sections) {
    if (!sec.items.length) continue;
    html += `<li class="pal-sec" role="presentation">${esc(sec.title)}</li>`;
    for (const it of sec.items) {
      const i = pal.items.push(it) - 1;
      const where = it.kind === "crypto" ? "Crypto" : (it.exchange ? `Stock · ${it.exchange}` : "Stock");
      html += `<li class="pal-item" role="option" id="pal-opt-${i}" data-i="${i}" aria-selected="false">`
        + `<span class="pal-sym">${esc(String(it.symbol).toUpperCase())}</span>`
        + `<span class="pal-name">${esc(it.name || "")}</span>`
        + `<span class="pal-kind${it.kind === "crypto" ? " is-crypto" : ""}">${esc(it.typed ? "Go" : where)}</span></li>`;
    }
  }
  pal.list.innerHTML = html;
  _palActivate(0);
}

function _palActivate(i) {
  if (!pal.items.length) { pal.input.removeAttribute("aria-activedescendant"); return; }
  pal.active = Math.max(0, Math.min(pal.items.length - 1, i));
  pal.list.querySelectorAll(".pal-item").forEach((li) => {
    const on = Number(li.dataset.i) === pal.active;
    li.classList.toggle("is-active", on);
    li.setAttribute("aria-selected", String(on));
    if (on) li.scrollIntoView({ block: "nearest" });
  });
  pal.input.setAttribute("aria-activedescendant", `pal-opt-${pal.active}`);
}

function _palKeys(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); _palActivate(pal.active + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); _palActivate(pal.active - 1); }
  else if (e.key === "Enter") {
    e.preventDefault();
    // Enter before the debounce fires must search what was typed, not open
    // whatever the list happened to be showing a keystroke ago.
    if (pal.timer && pal.input.value.trim()) {
      clearTimeout(pal.timer); pal.timer = 0;
      _palSearch(pal.input.value.trim()).then((fresh) => { if (fresh && pal.items[0]) _palChoose(pal.items[0]); });
      return;
    }
    if (pal.items[pal.active]) _palChoose(pal.items[pal.active]);
  } else if (e.key === "Escape") { e.preventDefault(); closePalette(); }
  else if (e.key === "Tab") { e.preventDefault(); }   // keep focus inside the dialog
}

function _palChoose(item) {
  if (!item) return;
  const kind = item.kind === "crypto" ? "crypto" : "stock";
  const sym = kind === "crypto" ? String(item.symbol).toLowerCase() : String(item.symbol).toUpperCase();
  _palRemember({ ...item, symbol: String(item.symbol).toUpperCase(), kind });
  const chartShowing = typeof _chartOnScreen === "function" && _chartOnScreen();
  closePalette();
  if (chartShowing) {
    $("#liveSymbol").value = sym;
    $("#liveKind").value = kind;
    loadLiveTradeChart();
    return;
  }
  location.href = chartPageUrl(sym, kind, typeof liveTf === "string" ? liveTf : "");
}

window.addEventListener("keydown", (e) => {
  const chord = (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K");
  const t = e.target;
  const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
  const slash = e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey;
  if (!chord && !slash) return;
  e.preventDefault();                          // Ctrl+K would otherwise jump to the browser's search bar
  if (pal && !pal.root.hidden) closePalette(); else openPalette();
});

// The visible way in, for anyone who doesn't know the shortcut (or has no keyboard).
(function wirePaletteButton() {
  const btn = document.getElementById("paletteBtn");
  if (btn) btn.addEventListener("click", () => openPalette());
  const kbd = document.getElementById("paletteKbd");
  if (kbd && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) kbd.textContent = "⌘K";
})();
