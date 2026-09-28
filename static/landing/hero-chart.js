/* MarketPulse — the landing page's live chart.
 *
 * The same chart as the app (chart-theme.js on Lightweight Charts): real intraday
 * candles with the EMA lines, updating while you watch. It opens on the name the
 * engine is most convinced about when the US market is open, and on Bitcoin when
 * it is not, because a visitor should see candles MOVE, not last Friday's tape.
 *
 * Read-only on purpose. Drawing, replay and Learning Mode are one click away on
 * /chart. The mouse wheel is left to the page: a landing chart that swallows the
 * scroll is a trap, not a feature.
 *
 *   HeroChart.setChoices([{ symbol, kind, row }])   // rows from /api/markets
 *   HeroChart.ok()                                  // false = engine didn't load
 */
(function () {
  "use strict";

  var TF = "5m";
  // The server keeps a coin's tape fresh for 5s and a stock's for 15s; polling
  // faster than that would only fetch the same candle again.
  var POLL_MS = { crypto: 5000, stock: 15000 };
  var CLOCK_MS = 1000;
  var OVERLAY_MS = 60000;
  var EMA = [14, 21, 57];
  var MIN_BAR_PX = 7, MAX_BARS = 84;

  var hc = null;                     // chart + series, built on first data
  var choices = [], pick = null, userPicked = false;
  var timer = 0, seq = 0, onScreen = true, lastOverlayAt = 0, overlay = null;
  var clockTimer = 0, freshAt = 0, lastShown = { key: null, price: null };

  function el(id) { return document.getElementById(id); }
  function setLive(key, text, cls) {
    Array.prototype.forEach.call(document.querySelectorAll('[data-live="' + key + '"]'), function (n) {
      n.textContent = text;
      if (cls !== undefined) n.className = cls;
    });
  }

  /* Cents on everything priced over a dollar: on a live chart the cents are
   * the digits that move, and rounding them away is what reads as "frozen". */
  function money(v) {
    if (v == null || !isFinite(v)) return "…";
    if (v >= 1) return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return "$" + Number(v).toPrecision(4);
  }

  function pad(n) { return String(n).padStart(2, "0"); }

  /* The seconds roll every second; "updated Ns ago" counts up between
   * refreshes and resets when fresh data lands, so the stamp is honest about
   * how old the candle on screen is. */
  function tickClock() {
    var now = new Date();
    var clock = el("heroClock");
    if (clock) clock.textContent = pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
    var stamp = el("heroStamp");
    if (!stamp) return;
    var ago = freshAt ? Math.max(0, Math.round((now.getTime() - freshAt) / 1000)) : null;
    stamp.textContent = ago == null ? "connecting" : ago < 2 ? "updated just now"
      : ago > 90 ? "reconnecting" : "updated " + ago + "s ago";
  }

  /* A green or red flash on the price when it changes, like a trading screen. */
  function flashPrice(key, price) {
    var prev = lastShown.key === key ? lastShown.price : null;
    lastShown = { key: key, price: price };
    if (prev == null || price == null || price === prev) return;
    var cls = price > prev ? "tick-up" : "tick-down";
    Array.prototype.forEach.call(document.querySelectorAll('[data-live="featPrice"]'), function (n) {
      n.classList.remove("tick-up", "tick-down");
      void n.offsetWidth;                    // restart the fade even on back-to-back ticks
      n.classList.add(cls);
      setTimeout(function () { n.classList.remove(cls); }, 700);
    });
  }

  /* Regular US session, Monday to Friday 9:30 to 16:00 New York time. Holidays
   * are not modelled: on one, the chart simply opens on a quiet stock. */
  function usMarketOpen(now) {
    try {
      var parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false,
      }).formatToParts(now || new Date());
      var get = function (t) { var p = parts.find(function (x) { return x.type === t; }); return p ? p.value : ""; };
      if (get("weekday") === "Sat" || get("weekday") === "Sun") return false;
      var mins = (Number(get("hour")) % 24) * 60 + Number(get("minute"));
      return mins >= 570 && mins < 960;
    } catch (e) { return false; }
  }

  function ensure() {
    if (hc) return hc;
    var LW = window.LightweightCharts, box = el("heroChart");
    if (!LW || !box || typeof pcChartOptions !== "function") return null;
    var colors = pcColors();
    var opts = pcChartOptions(LW, colors, function () { return TF; });
    opts.handleScroll = { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false };
    opts.handleScale = { mouseWheel: false, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true };
    opts.rightPriceScale.scaleMargins = { top: 0.1, bottom: 0.2 };
    var chart = LW.createChart(box, opts);
    var candles = chart.addSeries(LW.CandlestickSeries, pcCandleOptions(LW, colors), 0);
    var volume = pcAddVolume(chart, LW);
    var emas = EMA.map(function (p, i) {
      return chart.addSeries(LW.LineSeries, {
        color: PC_EMA_COLORS[i], lineWidth: i === 0 ? 2 : 1, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: function () { return null; },
      }, 0);
    });
    hc = { LW: LW, chart: chart, candles: candles, volume: volume, emas: emas, colors: colors, key: null, times: [] };
    box.closest(".ep-chart").classList.add("has-live-chart");
    return hc;
  }

  function getJSON(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }

  function chartUrl(c) {
    var sym = c.kind === "crypto" ? c.symbol.toLowerCase() : c.symbol.toUpperCase();
    return "/chart?symbol=" + encodeURIComponent(sym) + "&kind=" + c.kind + "&tf=" + TF;
  }

  function draw(d, identityChanged) {
    var n = Math.min((d.ohlc || []).length, (d.ts || []).length);
    if (n < 2) return false;
    var times = pcTimes(d.ts, n), buy = hc.colors.buy, sell = hc.colors.sell;
    var lr = hc.chart.timeScale().getVisibleLogicalRange();
    var pinned = identityChanged || !lr || lr.to >= hc.times.length - 1.5;
    var candles = [], vols = [], idx = {};
    for (var i = 0; i < n; i++) {
      var b = d.ohlc[i];
      candles.push({ time: times[i], open: b[0], high: b[1], low: b[2], close: b[3] });
      if (d.volume && d.volume[i]) vols.push({ time: times[i], value: d.volume[i], color: (b[3] >= b[0] ? buy : sell) + "59" });
      idx[d.ts[i]] = times[i];
    }
    hc.candles.applyOptions({ priceFormat: pcPriceFormat(d.ohlc[n - 1][3]) });
    hc.candles.setData(candles);
    hc.volume.setData(vols);
    hc.times = times;
    EMA.forEach(function (p, k) {
      var pairs = (overlay && overlay.emas && overlay.emas[String(p)]) || [];
      hc.emas[k].setData(pairs.filter(function (q) { return idx[q[0]] != null && q[1] != null; })
        .map(function (q) { return { time: idx[q[0]], value: q[1] }; }));
    });
    if (pinned) {
      var w = hc.chart.timeScale().width() || 600;
      var count = Math.max(20, Math.min(MAX_BARS, Math.floor(w / MIN_BAR_PX), n));
      hc.chart.timeScale().setVisibleLogicalRange({ from: n - count, to: n - 1 + PC_RIGHT_PAD });
    }
    return d.ohlc[n - 1][3];
  }

  function header(c, last) {
    var row = c.row || {};
    var sig = (row.signal && row.signal.label) || "";
    setLive("featTag", (c.kind === "crypto" ? "Trades 24/7" : "Strongest read") + (sig ? " · " + sig : ""));
    setLive("featSym", c.symbol.toUpperCase());
    setLive("featPrice", money(last != null ? last : row.price));
    if (row.change != null) {
      setLive("featChg", (row.change >= 0 ? "+" : "") + row.change.toFixed(2) + "%", row.change >= 0 ? "up" : "down");
    }
    var open = el("heroOpen");
    if (open) open.href = chartUrl(c);
    if (last != null) {
      freshAt = Date.now();
      flashPrice(c.kind + ":" + c.symbol, last);
    }
    tickClock();
  }

  function load(identityChanged) {
    if (!pick || !ensure()) return;
    var c = pick, my = ++seq, key = c.kind + ":" + c.symbol;
    var sym = encodeURIComponent(c.kind === "crypto" ? c.symbol.toLowerCase() : c.symbol.toUpperCase());
    var needOverlay = identityChanged || Date.now() - lastOverlayAt > OVERLAY_MS;
    // Stamped when the request STARTS, so two polls landing before it answers
    // don't both fetch; a failure clears the stamp so the next poll retries.
    if (needOverlay) lastOverlayAt = Date.now();
    var ov = needOverlay
      ? getJSON("/api/chart-overlay?symbol=" + sym + "&kind=" + c.kind + "&tf=" + TF + "&ema=" + EMA.join(",") + "&squeeze=0&prepost=0")
          .catch(function () { lastOverlayAt = 0; return null; })
      : Promise.resolve(overlay);
    Promise.all([getJSON("/api/intraday?symbol=" + sym + "&kind=" + c.kind + "&tf=" + TF), ov]).then(function (res) {
      if (my !== seq) return;                  // a newer pick owns the chart now
      if (res[1] && !res[1].error) overlay = res[1];
      var last = draw(res[0], identityChanged || hc.key !== key);
      hc.key = key;
      header(c, last === false ? null : last);
      el("heroChart").classList.toggle("is-stale", last === false);
    }).catch(function () {
      if (my === seq) el("heroChart").classList.add("is-stale");
    });
  }

  function schedule() {
    clearInterval(timer);
    clearInterval(clockTimer);
    timer = clockTimer = 0;
    if (!onScreen || document.visibilityState === "hidden") return;
    timer = setInterval(function () { load(false); }, POLL_MS[(pick && pick.kind) || "stock"] || POLL_MS.stock);
    clockTimer = setInterval(tickClock, CLOCK_MS);
    tickClock();
  }

  function renderChips() {
    var box = el("heroChips");
    if (!box) return;
    box.innerHTML = "";
    choices.forEach(function (c) {
      var b = document.createElement("button");
      var on = pick && c.kind === pick.kind && c.symbol === pick.symbol;
      b.type = "button";
      b.className = "hc-chip" + (on ? " is-on" : "") + (c.kind === "crypto" ? " is-crypto" : "");
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.textContent = c.symbol.toUpperCase();
      b.addEventListener("click", function () {
        userPicked = true;
        choose(c);
      });
      box.appendChild(b);
    });
  }

  function choose(c) {
    var changed = !pick || pick.kind !== c.kind || pick.symbol !== c.symbol;
    pick = c;
    if (changed) overlay = null;
    renderChips();
    load(changed);
    schedule();
  }

  /* Called by landing.js whenever the scan lands. The visitor's own pick wins
   * over the automatic one; the chips and rows refresh either way, and the next
   * poll brings the header's price and signal up to date. */
  function setChoices(list) {
    choices = list.filter(function (c) { return c && c.symbol; });
    if (!choices.length || !ensure()) return;
    var same = pick && choices.find(function (c) { return c.kind === pick.kind && c.symbol === pick.symbol; });
    var crypto = choices.find(function (c) { return c.kind === "crypto"; });
    var auto = (!usMarketOpen() && crypto) || choices[0];
    if (same && (userPicked || same === auto)) { pick = same; renderChips(); return; }
    choose(auto);
  }

  document.addEventListener("visibilitychange", function () {
    schedule();
    if (document.visibilityState === "visible" && pick) load(false);
  });
  document.addEventListener("DOMContentLoaded", function () {
    var panel = el("enginePanel");
    if (panel && "IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        var was = onScreen;
        onScreen = entries[0].isIntersecting;
        schedule();
        if (onScreen && !was && pick) load(false);
      }, { threshold: 0.05 }).observe(panel);
    }
  });

  window.HeroChart = {
    setChoices: setChoices,
    ok: function () { return !!ensure(); },
  };
})();
