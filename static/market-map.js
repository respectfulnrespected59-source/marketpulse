/* MarketPulse — the Market Map.
 *
 * A heatmap of the board: each tile is one name, SIZED by dollars traded (where
 * the money is actually moving) and COLOURED by today's move, with our signal
 * printed on it and a gold edge on every STRONG BUY. Every tile is a link to
 * that name's full chart.
 *
 * Used by the landing page and the app's Home tab, so it depends on nothing
 * from either: give it a container and rows from /api/markets.
 *
 *   MarketMap.render(el, { groups: [{ key, title, rows }], chartHref(row) })
 *
 * Size is the square root of dollars traded: linear sizing lets one mega-cap
 * swallow the map and leaves small names as unreadable slivers. A name with no
 * volume figure takes the group's median rather than an invented number, and a
 * group with no figures at all is drawn in equal sizes.
 */
(function () {
  "use strict";

  var GAP = 2;
  var CLAMP = 3;                     // ±3% saturates the colour scale

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function money(p) {
    if (p == null || !isFinite(p)) return "";
    if (p >= 1000) return "$" + Math.round(p).toLocaleString("en-US");
    if (p >= 1) return "$" + p.toFixed(2);
    return "$" + Number(p).toPrecision(3);
  }

  function dollars(v) {
    if (!v) return "n/a";
    if (v >= 1e12) return "$" + (v / 1e12).toFixed(2) + "T";
    if (v >= 1e9) return "$" + (v / 1e9).toFixed(1) + "B";
    if (v >= 1e6) return "$" + (v / 1e6).toFixed(0) + "M";
    return "$" + Math.round(v / 1e3) + "K";
  }

  function pct(ch) {
    var arrow = ch > 0 ? "▲" : ch < 0 ? "▼" : "●";
    return arrow + " " + (ch > 0 ? "+" : ch < 0 ? "−" : "") + Math.abs(ch).toFixed(2) + "%";
  }

  /* Diverging scale, two hues and a neutral middle; the arrow and signed % on
   * every tile carry the same fact for anyone who can't tell red from green. */
  function tone(ch) {
    var a = Math.min(Math.abs(ch), CLAMP);
    var step = a < 0.25 ? 0 : a < 1 ? 1 : a < 2 ? 2 : 3;
    return step === 0 ? "mm-flat" : (ch > 0 ? "mm-up" : "mm-dn") + step;
  }

  function median(xs) {
    var s = xs.slice().sort(function (a, b) { return a - b; });
    return s.length ? s[Math.floor(s.length / 2)] : 0;
  }

  /* Squarified treemap (Bruls, Huizing & van Wijk): rows of tiles laid along the
   * short side, each row kept only while it improves the worst aspect ratio. */
  function squarify(items, x, y, w, h) {
    var total = items.reduce(function (s, i) { return s + i.v; }, 0);
    var scale = total > 0 ? (w * h) / total : 0;
    var rest = items.map(function (i) { return { item: i, a: i.v * scale }; });
    var out = [];
    function worst(row, side) {
      var sum = 0, mx = 0, mn = Infinity;
      row.forEach(function (r) { sum += r.a; mx = Math.max(mx, r.a); mn = Math.min(mn, r.a); });
      return Math.max((side * side * mx) / (sum * sum), (sum * sum) / (side * side * mn));
    }
    while (rest.length) {
      var side = Math.min(w, h), row = [rest[0]], best = worst(row, side), k = 1;
      for (; k < rest.length; k++) {
        var cand = row.concat([rest[k]]), wv = worst(cand, side);
        if (wv > best) break;
        row = cand; best = wv;
      }
      var sum = row.reduce(function (s, r) { return s + r.a; }, 0);
      if (w >= h) {
        var cw = h ? sum / h : 0, cy = y;
        row.forEach(function (r) { var rh = cw ? r.a / cw : 0; out.push({ item: r.item, x: x, y: cy, w: cw, h: rh }); cy += rh; });
        x += cw; w -= cw;
      } else {
        var ch = w ? sum / w : 0, cx = x;
        row.forEach(function (r) { var rw = ch ? r.a / ch : 0; out.push({ item: r.item, x: cx, y: y, w: rw, h: ch }); cx += rw; });
        y += ch; h -= ch;
      }
      rest = rest.slice(row.length);
    }
    return out;
  }

  function weighted(rows) {
    var known = rows.map(function (r) { return r.dollar_vol; }).filter(function (v) { return v > 0; });
    var fill = median(known) || 1;
    return rows.map(function (r) {
      return { row: r, v: Math.sqrt(r.dollar_vol > 0 ? r.dollar_vol : fill) };
    }).sort(function (a, b) { return b.v - a.v; });
  }

  /* Show what fits, dropping the least important line first: signal, then
   * price, then the move, and the ticker last. A narrow tile shrinks its type
   * before it drops anything; "▲ +1.11%" needs ~80px at full size, ~62 small.
   * Clipped text is worse than none, because a cut-off number reads as a
   * different number. */
  function fitClass(w, h) {
    var small = w < 90 || h < 58;
    var pctFits = small ? w >= 62 : w >= 82;
    return (w >= 150 && h >= 110 ? " mm-big" : "") + (small ? " mm-sm" : "") +
      (!pctFits || h < 40 ? " mm-no-pct" : "") + (!pctFits || h < 70 ? " mm-no-px" : "") +
      (h < 92 || w < 84 ? " mm-no-sig" : "") + (w < 40 || h < 22 ? " mm-no-sym" : "");
  }

  function tileHtml(t, href) {
    var r = t.row, sig = (r.signal && r.signal.label) || "NEUTRAL";
    var strong = sig === "STRONG BUY";
    var label = r.symbol + ", " + pct(r.change) + " today, " + dollars(r.dollar_vol) + " traded, our signal " + sig;
    return '<a class="mm-t ' + tone(r.change) + (strong ? " mm-strong" : "") + fitClass(t.w, t.h) + '"' +
      ' href="' + esc(href) + '" role="listitem" aria-label="' + esc(label) + '" data-sym="' + esc(r.symbol) + '"' +
      ' style="left:' + (t.x + GAP / 2).toFixed(1) + "px;top:" + (t.y + GAP / 2).toFixed(1) + "px;width:" +
      Math.max(0, t.w - GAP).toFixed(1) + "px;height:" + Math.max(0, t.h - GAP).toFixed(1) + 'px">' +
      '<span class="mm-head"><b class="mm-sym">' + esc(r.symbol) + '</b><span class="mm-pct">' + esc(pct(r.change)) +
      '</span><span class="mm-px">' + esc(money(r.price)) + "</span></span>" +
      '<span class="mm-sig' + (strong ? " is-strong" : "") + '">' + esc(sig) + "</span></a>";
  }

  function tipHtml(r) {
    var sig = (r.signal && r.signal.label) || "NEUTRAL";
    return "<b>" + esc(r.symbol) + "</b> " + esc(r.name && r.name !== r.symbol ? "· " + r.name : "") +
      '<div class="mm-tr"><span>Price</span><span>' + esc(money(r.price)) + "</span></div>" +
      '<div class="mm-tr"><span>Today</span><span>' + esc(pct(r.change)) + "</span></div>" +
      '<div class="mm-tr"><span>Traded</span><span>' + esc(dollars(r.dollar_vol)) + "</span></div>" +
      '<div class="mm-tr"><span>Our signal</span><span>' + esc(sig) + "</span></div>" +
      '<div class="mm-tr mm-go"><span>Click for the live chart</span></div>';
  }

  function layout(state) {
    var board = state.el.querySelector(".mm-board");
    var groups = state.groups.filter(function (g) {
      return g.rows.length && (state.filter === "all" || state.filter === g.key);
    });
    board.classList.toggle("mm-single", groups.length < 2);
    board.innerHTML = groups.map(function (g) {
      var total = g.rows.reduce(function (s, r) { return s + (r.dollar_vol || 0); }, 0);
      return '<section class="mm-grp" data-key="' + esc(g.key) + '"><h3>' + esc(g.title) +
        "<span>" + (total ? esc(dollars(total)) + " traded" : "") + "</span></h3>" +
        '<div class="mm-tiles" role="list" aria-label="' + esc(g.title) + '"></div></section>';
    }).join("");
    groups.forEach(function (g) {
      var box = board.querySelector('.mm-grp[data-key="' + g.key + '"] .mm-tiles');
      var tiles = squarify(weighted(g.rows), 0, 0, box.clientWidth, box.clientHeight);
      box.innerHTML = tiles.map(function (t) {
        return tileHtml({ row: t.item.row, x: t.x, y: t.y, w: t.w, h: t.h }, state.chartHref(t.item.row));
      }).join("");
    });
    state.bySym = Object.create(null);   // keyed by feed-supplied symbols: no prototype to reach
    state.groups.forEach(function (g) { g.rows.forEach(function (r) { state.bySym[r.symbol] = r; }); });
  }

  function wire(state) {
    var el = state.el, tip = el.querySelector(".mm-tip");
    el.querySelector(".mm-filters").addEventListener("click", function (e) {
      var b = e.target.closest("[data-f]");
      if (!b) return;
      state.filter = b.getAttribute("data-f");
      Array.prototype.forEach.call(el.querySelectorAll("[data-f]"), function (x) {
        var on = x === b; x.classList.toggle("is-on", on); x.setAttribute("aria-pressed", on ? "true" : "false");
      });
      layout(state);
    });
    el.addEventListener("pointermove", function (e) {
      var t = e.pointerType === "mouse" && e.target.closest(".mm-t");
      if (!t) { tip.hidden = true; return; }
      var r = state.bySym[t.getAttribute("data-sym")];
      if (!r) return;
      tip.innerHTML = tipHtml(r);
      tip.hidden = false;
      var box = el.getBoundingClientRect();
      var x = Math.min(e.clientX - box.left + 14, box.width - tip.offsetWidth - 6);
      var y = e.clientY - box.top + 16;
      if (y + tip.offsetHeight > box.height) y = e.clientY - box.top - tip.offsetHeight - 12;
      tip.style.left = Math.max(6, x) + "px"; tip.style.top = Math.max(6, y) + "px";
    });
    el.addEventListener("pointerleave", function () { tip.hidden = true; });
    if ("ResizeObserver" in window) {
      var lastW = 0, raf = 0;
      new ResizeObserver(function (entries) {
        var w = Math.round(entries[0].contentRect.width);
        if (w === lastW) return;
        lastW = w;
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(function () { layout(state); });
      }).observe(el);
    }
  }

  function shell(el, groups) {
    var chips = [["all", "All"]].concat(groups.map(function (g) { return [g.key, g.title]; }));
    el.innerHTML = '<div class="mm">' +
      '<div class="mm-bar"><div class="mm-filters" role="group" aria-label="Show">' +
      chips.map(function (c, i) {
        return '<button type="button" class="mm-chip' + (i ? "" : " is-on") + '" data-f="' + esc(c[0]) +
          '" aria-pressed="' + (i ? "false" : "true") + '">' + esc(c[1]) + "</button>";
      }).join("") + "</div>" +
      '<div class="mm-legend" aria-hidden="true"><span>−3%</span><i class="mm-dn3"></i><i class="mm-dn2"></i><i class="mm-dn1"></i>' +
      '<i class="mm-flat"></i><i class="mm-up1"></i><i class="mm-up2"></i><i class="mm-up3"></i><span>+3%</span></div></div>' +
      '<div class="mm-board"></div><div class="mm-tip" role="tooltip" hidden></div></div>';
  }

  function render(el, opts) {
    if (!el) return;
    var groups = (opts.groups || []).map(function (g, i) {
      return {
        key: g.key || "g" + i, title: g.title,
        rows: (g.rows || []).filter(function (r) { return r && !r.error && r.price != null && r.symbol; }),
      };
    });
    var state = el.__mm;
    if (!state) {
      shell(el, groups);
      state = el.__mm = { el: el, filter: "all", groups: groups, bySym: Object.create(null),
                          chartHref: opts.chartHref || function () { return "#"; } };
      wire(state);
    }
    state.groups = groups;
    layout(state);
  }

  window.MarketMap = { render: render };
})();
