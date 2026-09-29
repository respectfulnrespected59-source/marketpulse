/* MarketPulse — options paper positions on the live chart.
 *
 * A paper put spread used to live only in the Options book, so watching it
 * meant flipping between two tabs and doing the arithmetic in your head. Now
 * any open position on the symbol the chart shows draws its breakeven and
 * strikes as price lines, and a strip under the price says where it stands.
 *
 * Two numbers, never blended, because they are not the same thing:
 *   * "at mark" — what /api/options/mark last said you could close for. The
 *     options chain is CBOE-delayed ~15 minutes, so this lags the candles.
 *   * "est now" — that mark moved by the position's own delta and gamma to the
 *     stock's LIVE price. An estimate, labelled as one, and held inside the
 *     spread's max profit and max loss. When any input is missing it says
 *     nothing rather than guess.
 *
 * Loaded after options-paper.js (getOptBook, optBookTick, optBookLabel,
 * optBookMoney, optNum) and before app.js. Globals are prefixed optChart.
 */

const OPT_CHART_MULTIPLIER = 100;
// Delta-gamma is a local approximation. Beyond this move from the marked spot
// the quadratic stops describing the spread, so the estimate is withheld.
const OPT_CHART_MAX_MOVE = 0.05;
// A mark older than this is from another session (or a sleeping tab); showing
// it as "at mark" would present yesterday's number as today's.
const OPT_CHART_STALE_MS = 30 * 60 * 1000;

let optChartTimer = null;

function _optChartNum(v) {
  if (v == null || v === "") return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

/** Open options positions on `sym`, each paired with its last server mark (or null).
 *  Given `now`, marks older than OPT_CHART_STALE_MS (or of unknown age) are dropped. */
function optChartPositions(book, sym, now) {
  const want = String(sym || "").trim().toUpperCase();
  if (!want || !book || !Array.isArray(book.open)) return [];
  const age = now == null ? 0 : now - (_optChartNum(book.lastMark) ?? -Infinity);
  const marks = age <= OPT_CHART_STALE_MS ? (book.marks || {}) : {};
  return book.open
    .filter((p) => p && String(p.symbol || "").toUpperCase() === want)
    .map((p) => ({ pos: p, mark: marks[p.id] || null }));
}

/** Price lines: each position's breakeven, plus every distinct strike. */
function optChartLines(entries) {
  const lines = [];
  const strikes = new Set();
  const bes = new Set();
  for (const { pos } of entries || []) {
    const be = _optChartNum(pos.breakeven);
    if (be != null && !bes.has(be)) {
      bes.add(be);
      lines.push({ price: be, kind: "be", title: `BE ${pos.symbol}` });
    }
    for (const leg of pos.legs || []) {
      const k = _optChartNum(leg.strike);
      if (k == null) continue;
      const tag = `${leg.side === "short" ? "-" : "+"}${k}${leg.right === "put" ? "P" : "C"}`;
      if (strikes.has(tag)) continue;
      strikes.add(tag);
      lines.push({ price: k, kind: "strike", title: tag });
    }
  }
  return lines;
}

/** Live P&L estimate: the last marked P&L moved by delta/gamma to the live price.
 *  Null whenever it would have to guess. Clamped to the position's own limits. */
function optChartEstimate(pos, mark, liveSpot) {
  const spot = _optChartNum(liveSpot);
  if (!pos || !mark || mark.status !== "open" || spot == null) return null;
  const net = _optChartNum(mark.net_usd);
  const at = _optChartNum(mark.spot);
  const delta = _optChartNum(mark.greeks && mark.greeks.delta);
  if (net == null || at == null || delta == null) return null;
  const gamma = _optChartNum(mark.greeks.gamma) || 0;
  const dS = spot - at;
  if (at <= 0 || Math.abs(dS) > at * OPT_CHART_MAX_MOVE) return null;
  // Integrate delta(s) = delta + gamma*s, but stop where delta reaches zero: a
  // put spread never turns bullish, however far the quadratic would take it.
  let move = dS;
  if (gamma !== 0 && delta !== 0) {
    const toZero = -delta / gamma;
    if (toZero * dS > 0 && Math.abs(toZero) < Math.abs(dS)) move = toZero;
  }
  let est = net + (delta * move + 0.5 * gamma * move * move) * OPT_CHART_MULTIPLIER;
  // net_usd already paid both commissions; the limits are gross, so shift them
  // by exactly what the server charged (gross - net) rather than a local copy
  // of the commission rate.
  const gross = _optChartNum(mark.gross_usd);
  const fees = gross != null ? Math.max(0, gross - net) : 0;
  const best = _optChartNum(pos.max_profit_usd);
  const worst = _optChartNum(pos.max_loss_usd);
  if (best != null) est = Math.min(est, best - fees);
  if (worst != null) est = Math.max(est, -worst - fees);
  return Math.round(est * 100) / 100;
}

function _optChartPnl(v) {
  return `<b class="${v >= 0 ? "up" : "down"}">${optBookMoney(v)}</b>`;
}

/** The strip under the chart price: one row per position. */
function optChartStripHtml(entries, liveSpot) {
  if (!entries || !entries.length) return "";
  return entries.map(({ pos, mark }) => {
    const n = optNum(pos.contracts);
    const head = `<span class="oc-name">${esc(optBookLabel(pos))}</span><span>${n}x</span>`;
    const be = `<span>BE <b>${fmtPrice(_optChartNum(pos.breakeven))}</b></span>`;
    const dte = mark && mark.dte != null ? `<span class="muted">${optNum(mark.dte)}d left</span>` : "";
    if (!mark || mark.net_usd == null) {
      const why = mark && mark.status === "unquoted" ? "no quote on a leg" : "marking…";
      return `<div class="oc-row">${head}<span class="muted">${esc(why)}</span>${be}${dte}</div>`;
    }
    const est = optChartEstimate(pos, mark, liveSpot);
    const estHtml = est == null ? ""
      : `<span title="Last mark moved by the position's delta and gamma to the live stock price. An estimate, not a quote.">est now ${_optChartPnl(est)}</span>`;
    return `<div class="oc-row ${mark.net_usd >= 0 ? "win" : "loss"}">${head}`
      + `<span title="What you could close for at the last mark. The options chain is ~15 min delayed.">at mark ${_optChartPnl(mark.net_usd)} <span class="muted">(delayed ~15m)</span></span>`
      + `${estHtml}${be}${dte}</div>`;
  }).join("");
}

function _optChartBookLoopRunning() {
  return typeof optBookTimer !== "undefined" && !!optBookTimer;
}

/* One interval beat. Polices itself: once the book is empty, or the Options
 * book's own loop has started, this loop stands down instead of doubling up. */
function _optChartBeat() {
  const b = getOptBook();
  if (_optChartBookLoopRunning() || !(b.open || []).length) {
    optChartEnsureMarking(false);
    return;
  }
  optBookTick();
}

/** Keep marking while the chart shows a held symbol, even if the Options tab
 *  was never opened. Stopped when the Live tab closes (app.js setView). */
function optChartEnsureMarking(on) {
  if (on && !optChartTimer && typeof optBookTick === "function") {
    if (_optChartBookLoopRunning()) return;
    optBookTick();
    optChartTimer = setInterval(_optChartBeat, OPT_BOOK_POLL_MS);
  } else if (!on && optChartTimer) {
    clearInterval(optChartTimer);
    optChartTimer = null;
  }
}

/** Everything the live chart needs for `sym`: price lines and the strip markup. */
function optChartFor(sym, kind, liveSpot) {
  if (kind === "crypto" || typeof getOptBook !== "function") {
    optChartEnsureMarking(false);
    return { lines: [], html: "" };
  }
  const entries = optChartPositions(getOptBook(), sym, Date.now());
  optChartEnsureMarking(entries.length > 0);
  return { lines: optChartLines(entries), html: optChartStripHtml(entries, liveSpot) };
}
