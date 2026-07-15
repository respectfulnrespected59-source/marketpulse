/* QuickFill — a Robinhood-style amount control.
 *
 * Big readable $ amount + one-tap chips + -/+ steppers + a live conversion
 * readout ("~ 0.76 shares - NVDA @ $394.31"). Money math runs through big.js
 * so there is no float drift. Framework-free and self-contained: it takes a
 * priceFetcher callback so it never depends on the rest of the app loading
 * first.
 *
 * Usage:
 *   const qf = QuickFill.mount(containerEl, {
 *     amount: 300,
 *     chips: [50, 100, 250, 500, 1000],
 *     step: 25,
 *     min: 1,
 *     getContext: () => ({ symbol: 'NVDA', kind: 'stock', side: 'long' }),
 *     priceFetcher: async (symbol, kind) => 394.31,   // returns a number price
 *   });
 *   qf.getAmount();          // -> 300 (Number)
 *   qf.refreshConversion();  // re-pull price for the current context
 */
(function (root) {
  "use strict";
  var B = root.Big || function (x) { return { toString: function () { return String(x); } }; };

  function money(n) {
    var neg = n < 0;
    var v = Math.abs(n);
    var s = v >= 1000 && v % 1 === 0
      ? v.toLocaleString("en-US")
      : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (neg ? "-$" : "$") + s;
  }

  function trimNum(str) {
    return str.indexOf(".") < 0 ? str : str.replace(/0+$/, "").replace(/\.$/, "");
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function mount(container, opts) {
    opts = opts || {};
    var chips = opts.chips || [50, 100, 250, 500, 1000];
    var step = opts.step || 25;
    var min = opts.min != null ? opts.min : 1;
    var amount = opts.amount != null ? opts.amount : (chips[0] || 100);
    var getContext = opts.getContext || function () { return {}; };
    var priceFetcher = opts.priceFetcher || null;
    var onChange = opts.onChange || function () {};
    var lastPrice = null;

    container.classList.add("qf");
    container.innerHTML =
      '<div class="qf-row">' +
        '<button type="button" class="qf-step" data-dir="-1" aria-label="Decrease">−</button>' +
        '<div class="qf-amount"><span class="qf-cur">$</span>' +
          '<input class="qf-input" inputmode="decimal" autocomplete="off" /></div>' +
        '<button type="button" class="qf-step" data-dir="1" aria-label="Increase">+</button>' +
      '</div>' +
      '<div class="qf-chips">' +
        chips.map(function (c) {
          var label = c >= 1000 ? "$" + (c / 1000) + "k" : "$" + c;
          return '<button type="button" class="qf-chip" data-amt="' + c + '">' + label + '</button>';
        }).join("") +
      '</div>' +
      '<div class="qf-convert" aria-live="polite"></div>';

    var input = container.querySelector(".qf-input");
    var convert = container.querySelector(".qf-convert");

    function setAmount(v, refresh) {
      var num = Number(v);
      if (!isFinite(num) || num < min) num = min;
      amount = Number(new B(num).round(2).toString());
      input.value = trimNum(new B(amount).toString());
      container.querySelectorAll(".qf-chip").forEach(function (b) {
        b.classList.toggle("is-active", Number(b.dataset.amt) === amount);
      });
      onChange(amount);
      if (refresh !== false) renderConversion();
    }

    function renderConversion() {
      var ctx = getContext() || {};
      if (lastPrice == null || !ctx.symbol) { convert.textContent = ""; return; }
      var price = lastPrice;
      var sym = escHtml((ctx.symbol || "").toUpperCase());
      if (ctx.side === "call" || ctx.side === "put") {
        convert.innerHTML = "modeled as a <b>" + money(amount) +
          "</b> directional stake &middot; " + sym + " @ " + money(price);
        return;
      }
      if (ctx.kind === "crypto") {
        var units = trimNum(new B(amount).div(price).round(6).toString());
        convert.innerHTML = "≈ <b>" + units + " " + sym + "</b> &middot; @ " + money(price);
        return;
      }
      var shares = trimNum(new B(amount).div(price).round(4).toString());
      convert.innerHTML = "≈ <b>" + shares + " shares</b> &middot; " + sym + " @ " + money(price);
    }

    function refreshConversion() {
      var ctx = getContext() || {};
      if (!priceFetcher || !ctx.symbol) { lastPrice = null; renderConversion(); return; }
      convert.textContent = "pricing …";
      Promise.resolve(priceFetcher(ctx.symbol, ctx.kind)).then(function (p) {
        lastPrice = (typeof p === "number" && isFinite(p)) ? p : null;
        renderConversion();
      }).catch(function () { lastPrice = null; convert.textContent = ""; });
    }

    container.addEventListener("click", function (e) {
      var chip = e.target.closest(".qf-chip");
      if (chip) { setAmount(Number(chip.dataset.amt)); return; }
      var stepBtn = e.target.closest(".qf-step");
      if (stepBtn) { setAmount(amount + Number(stepBtn.dataset.dir) * step); }
    });
    input.addEventListener("input", function () {
      var v = parseFloat(input.value);
      if (isFinite(v)) { amount = v; onChange(v); renderConversion(); }
    });
    input.addEventListener("blur", function () { setAmount(input.value); });

    setAmount(amount, false);
    refreshConversion();

    return {
      getAmount: function () { return amount; },
      setAmount: setAmount,
      refreshConversion: refreshConversion,
    };
  }

  root.QuickFill = { mount: mount };
})(window);
