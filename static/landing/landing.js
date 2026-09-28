/* MarketPulse landing.
 *
 * 1. Before paint: an installed app (display-mode standalone) or an old deep
 *    link ("/?view=dca", "/?src=pwa") belongs in the app, so forward to /app.
 * 2. After load: every live number is read from /api/markets. Until the engine
 *    answers, numbers show an ellipsis, never a fake zero.
 */
(function forwardToApp() {
  var q = new URLSearchParams(location.search);
  var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;
  if (standalone || q.has("view") || q.get("src") === "pwa") {
    location.replace("/app" + location.search + location.hash);
  }
})();
document.documentElement.classList.add("js");

/* Prices confirmed by the owner 2026-09-27. One place to change them. */
var PRICING = [
  {
    id: "free", name: "Free", monthly: 0, lifetime: 0,
    per: { monthly: "Free while execution is built", lifetime: "Free while execution is built" },
    features: [
      ["Full research app: signals, options chains, Greeks", 0],
      ["DCA wizard, probe sizer, pot tracker", 0],
      ["Paper trading and the live tracker", 0],
      ["Proof Mode backtests on any ticker", 0],
    ],
    cta: "Open the app", href: "/app", style: "btn-ghost",
  },
  {
    id: "pro", name: "Pro", monthly: 29, lifetime: 297, featured: true, badge: "Founding price",
    per: { monthly: "per month, cancel anytime", lifetime: "one time, yours for life" },
    features: [
      ["Everything in Free", 0],
      ["Real-money trading on 1 brokerage account", 1],
      ["Approve every trade, or switch on auto with hard limits", 1],
      ["Kill switch, daily spend cap, loss circuit breaker", 1],
      ["License for the web app and the download", 1],
    ],
    cta: "Join the founding list", href: "https://quantummelaninmedia.gumroad.com/l/mzwrgk", style: "btn-gold",
  },
  {
    id: "proplus", name: "Pro+", monthly: 59, lifetime: 597,
    per: { monthly: "per month, cancel anytime", lifetime: "one time, yours for life" },
    features: [
      ["Everything in Pro", 0],
      ["Up to 3 brokerage accounts", 1],
      ["Run on up to 5 devices", 1],
      ["First access to every new engine upgrade", 1],
    ],
    cta: "Join the founding list", href: "https://quantummelaninmedia.gumroad.com/l/mzwrgk", style: "btn-ghost",
  },
];

var REFRESH_MS = 60000;
var RETRY_MS = 15000;

function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function $(sel, root) { return (root || document).querySelector(sel); }
function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
function money(v) {
  if (v == null || isNaN(v)) return "…";
  var d = Math.abs(v) >= 1000 ? 0 : 2;
  return "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function pct(v) {
  if (v == null || isNaN(v)) return "…";
  return (v > 0 ? "+" : v < 0 ? "-" : "") + Math.abs(v).toFixed(2) + "%";
}
function sigClass(label) {
  var l = String(label || "").toLowerCase();
  return l.indexOf("buy") >= 0 ? "buy" : l.indexOf("sell") >= 0 ? "sell" : "neutral";
}
function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
}
function setLive(key, text, cls) {
  $all('[data-live="' + key + '"]').forEach(function (el) {
    el.textContent = text;
    if (cls !== undefined) el.className = cls;
  });
}

/* ------------------------------------------------------------ status */
function setStatus(state, detail) {
  var word = { on: "ONLINE", off: "RECONNECTING", wait: "CONNECTING" }[state];
  $all("[data-status-dot]").forEach(function (d) { d.className = "dot " + (state === "wait" ? "" : state); });
  $all("[data-status-word]").forEach(function (w) { w.textContent = word; });
  $all("[data-status-text]").forEach(function (t) { t.textContent = detail; });
}

/* ------------------------------------------------------------ count-up */
function countUp(key, target) {
  var els = $all('[data-live="' + key + '"]');
  if (!els.length) return;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) { els.forEach(function (e) { e.textContent = String(target); }); return; }
  var start = performance.now(), dur = 900;
  function tick(now) {
    var t = Math.min(1, (now - start) / dur), eased = 1 - Math.pow(1 - t, 3);
    els.forEach(function (e) { e.textContent = String(Math.round(target * eased)); });
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/* ------------------------------------------------------------ hero chart */
function drawSpark(values) {
  var svg = $("#heroSpark");
  if (!svg || !values || values.length < 2) return;
  var W = 600, H = 220, pad = 14;
  var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
  var span = hi - lo || 1;
  var pts = values.map(function (v, i) {
    return [(i / (values.length - 1)) * W, pad + (1 - (v - lo) / span) * (H - pad * 2)];
  });
  var line = pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" ");
  var lineEl = $(".spark-line", svg), areaEl = $(".spark-area", svg), head = $(".spark-head", svg);
  lineEl.setAttribute("d", line);
  areaEl.setAttribute("d", line + " L" + W + " " + H + " L0 " + H + " Z");
  var last = pts[pts.length - 1];
  head.setAttribute("cx", last[0]); head.setAttribute("cy", last[1]);
  var len = lineEl.getTotalLength ? lineEl.getTotalLength() : 2000;
  lineEl.style.strokeDasharray = len; lineEl.style.setProperty("--len", len);
  svg.classList.remove("drawn"); void svg.getBoundingClientRect(); svg.classList.add("drawn");
}

/* ------------------------------------------------------------ render */
function render(rows, ts, cryptoRows) {
  var scored = rows.filter(function (r) { return r && r.signal && r.price != null; });
  if (!scored.length) throw new Error("no rows");
  var bull = scored.filter(function (r) { return r.signal.score > 0; }).length;
  var bear = scored.filter(function (r) { return r.signal.score < 0; }).length;
  var strong = scored.filter(function (r) { return /^STRONG/.test(r.signal.label); }).length;
  countUp("scanned", scored.length); countUp("strong", strong);
  countUp("bull", bull); countUp("bear", bear);
  setLive("time", clock(ts));
  setLive("sysStatus", "Online");
  setLive("scanFrac", scored.length + " / " + rows.length);
  setStatus("on", "Online · " + scored.length + " names");

  var byConviction = scored.slice().sort(function (a, b) {
    return Math.abs(b.signal.score) - Math.abs(a.signal.score);
  });
  var feat = byConviction[0];
  var crypto = (cryptoRows || []).filter(function (r) { return r && !r.error && r.price != null; });
  if (!showLiveChart(byConviction, crypto)) {
    // The chart engine didn't load: the daily sketch of the strongest read stands in.
    setLive("featTag", "Strongest read · " + feat.signal.label);
    setLive("featSym", feat.symbol);
    setLive("featPrice", money(feat.price));
    setLive("featChg", pct(feat.change), feat.change >= 0 ? "up" : "down");
    drawSpark(feat.spark);
  }
  showMarketMap(scored, crypto);

  $("#heroRows").innerHTML = byConviction.slice(0, 4).map(function (r) {
    return '<div class="ep-row"><b>' + esc(r.symbol) + '</b><span class="sig ' + sigClass(r.signal.label) + '">' +
      esc(r.signal.label) + '</span><span class="chg ' + (r.change >= 0 ? "up" : "down") + '">' + esc(pct(r.change)) + "</span></div>";
  }).join("");

  var t = clock(ts);
  var feed = [];
  byConviction.slice(0, 4).forEach(function (r) {
    var c = sigClass(r.signal.label);
    feed.push('<li><time>' + t + '</time><span>READ // <b>' + esc(r.symbol) + '</b> // <span class="' +
      (c === "buy" ? "u" : c === "sell" ? "d" : "g") + '">' + esc(r.signal.label) + "</span></span></li>");
    var why = (r.signal.reasons || []).slice(0, 3).map(esc).join(" ✓ ");
    if (why) feed.push('<li><time>' + t + '</time><span>FACTORS // ' + why + "</span></li>");
  });
  feed.push('<li><time>' + t + '</time><span>SCAN // <b>' + scored.length + '</b> NAMES // <span class="g">COMPLETE</span></span></li>');
  $("#feed").innerHTML = feed.slice(0, 9).map(function (li, i) {
    return li.replace("<li>", '<li style="animation-delay:' + (i * 0.12).toFixed(2) + 's">');
  }).join("");

  var items = scored.map(function (r) {
    return '<span class="mq-item"><b>' + esc(r.symbol) + '</b><span class="p">' + esc(money(r.price)) +
      '</span><span class="' + (r.change >= 0 ? "up" : "down") + '">' + esc(pct(r.change)) +
      '</span><span class="sig ' + sigClass(r.signal.label) + '">' + esc(r.signal.label) + "</span></span>";
  }).join("");
  $("#marquee").innerHTML = items + items;
}

/* ------------------------------------------------------------ live chart + map */
function chartHref(r) {
  var crypto = r.kind === "crypto";
  var sym = crypto ? String(r.symbol).toLowerCase() : String(r.symbol).toUpperCase();
  return "/chart?symbol=" + encodeURIComponent(sym) + "&kind=" + (crypto ? "crypto" : "stock") + "&tf=5m";
}

/* The three strongest reads plus Bitcoin, which trades while stocks sleep.
 * Guarded: nothing the chart does may take the rest of the panel down. */
function showLiveChart(byConviction, crypto) {
  try {
    if (!window.HeroChart || !window.HeroChart.ok()) return false;
    var btc = crypto.filter(function (r) { return r.symbol === "BTC"; })[0];
    var choices = byConviction.slice(0, 3).map(function (r, i) {
      return { symbol: r.symbol, kind: "stock", row: r, rank: i + 1 };
    });
    choices.push({ symbol: "BTC", kind: "crypto", row: btc });
    window.HeroChart.setChoices(choices);
    return true;
  } catch (e) {
    return false;
  }
}

function showMarketMap(stocks, crypto) {
  try {
    if (!window.MarketMap) return;
    window.MarketMap.render($("#marketMap"), {
      groups: [{ key: "stocks", title: "Stocks", rows: stocks }, { key: "crypto", title: "Crypto", rows: crypto }],
      chartHref: chartHref,
    });
  } catch (e) { /* the map is a bonus; the scan above it must still render */ }
}

/* ------------------------------------------------------------ data */
var symbolsCache = null;
function getJSON(url) {
  return fetch(url, { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  });
}
function loadSymbols() {
  if (symbolsCache) return Promise.resolve(symbolsCache);
  return getJSON("/api/universe").then(function (u) {
    var seen = {};
    symbolsCache = (u.stocks || []).concat(u.ai || []).filter(function (s) {
      if (seen[s]) return false; seen[s] = true; return true;
    });
    return symbolsCache;
  });
}
function load() {
  // Crypto feeds the map and the chart's Bitcoin chip; if it fails, stocks still render.
  var crypto = getJSON("/api/markets?type=crypto").then(function (d) { return d.rows || []; })
    .catch(function () { return []; });
  return loadSymbols().then(function (syms) {
    // lite: the landing needs price, move and signal, not the grid's extras.
    return Promise.all([getJSON("/api/markets?type=stocks&lite=1&symbols=" + encodeURIComponent(syms.join(","))), crypto]);
  }).then(function (res) {
    var d = res[0];
    render(d.rows || [], d.ts || Math.floor(Date.now() / 1000), res[1]);
    setTimeout(load, REFRESH_MS);
  }).catch(function () {
    setStatus("off", "Waking up, retrying");
    setTimeout(load, RETRY_MS);
  });
}

/* ------------------------------------------------------------ pricing */
function renderPricing(bill) {
  var grid = $("#priceGrid");
  if (!grid) return;
  grid.innerHTML = PRICING.map(function (p) {
    var amt = p[bill];
    var price = amt === 0 ? "$0" : "$" + amt + (bill === "monthly" ? "<small> /mo</small>" : "<small> once</small>");
    var feats = p.features.map(function (f) {
      return '<li class="' + (f[1] ? "soon" : "") + '">' + esc(f[0]) + (f[1] ? '<span class="tag">In build</span>' : "") + "</li>";
    }).join("");
    var external = p.href.indexOf("http") === 0 ? ' target="_blank" rel="noopener"' : "";
    return '<article class="price glass reveal in' + (p.featured ? " featured gold-edge" : "") + '">' +
      (p.badge ? '<span class="badge">' + esc(p.badge) + "</span>" : "") +
      "<h3>" + esc(p.name) + '</h3><div class="amt">' + price + '</div><p class="per">' + esc(p.per[bill]) + "</p>" +
      "<ul>" + feats + '</ul><a class="btn ' + p.style + '" href="' + esc(p.href) + '"' + external + ">" + esc(p.cta) + "</a></article>";
  }).join("");
}

/* ------------------------------------------------------------ boot */
document.addEventListener("DOMContentLoaded", function () {
  var io = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }) : null;
  $all(".reveal").forEach(function (el, i) {
    el.style.transitionDelay = ((i % 4) * 0.07).toFixed(2) + "s";
    if (io) io.observe(el); else el.classList.add("in");
  });

  var nav = $("#nav"), burger = $("#navBurger");
  burger.addEventListener("click", function () {
    var open = nav.classList.toggle("open");
    burger.setAttribute("aria-expanded", open ? "true" : "false");
  });
  $all("#navLinks a").forEach(function (a) {
    a.addEventListener("click", function () { nav.classList.remove("open"); burger.setAttribute("aria-expanded", "false"); });
  });

  renderPricing("monthly");
  $all("[data-bill]").forEach(function (b) {
    b.addEventListener("click", function () {
      $all("[data-bill]").forEach(function (x) {
        var on = x === b; x.classList.toggle("is-on", on); x.setAttribute("aria-pressed", on ? "true" : "false");
      });
      renderPricing(b.getAttribute("data-bill"));
    });
  });

  setStatus("wait", "Waking the engine");
  load();
});
