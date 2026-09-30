/* MarketPulse — the Para-Sail strategy card and the buy-zone watcher (owner 2026-09-30).
 *
 * Shop the low, take the icing, cap every name: the same engine the Classes lessons run
 * (parasail.py, served by /api/parasail). BTC is held — the coin we treat as money — and never
 * para-sailed. The card tells the truth about this history: whichever of para-sailing or holding the
 * same buys did better is the one it names.
 *
 * Classic script sharing the page's global scope (esc, fmtPrice, potMoney, $, state, store, keyOf,
 * getMarkets, toast, features, openUpgrade live in app.js and friends). The pure parts — alertHit,
 * alertText, alertFiredMsg, parasailCard — are unit-tested in tests/test_parasail_ui.py; app.js's
 * alert loop calls the first three for every alert, old and new.
 */

/* ----------------------------------------------------- alerts (all kinds) */

function alertHit(a, price) {
  if (a.dir === "above") return price >= a.price;
  if (a.dir === "below" || a.dir === "zone") return price <= a.price;   // zone: at or under today's zone top
  return false;
}

function alertText(a) {
  if (a.dir === "zone") return `◆ buy zone ≤ ${fmtPrice(a.price)}`;
  return `${a.dir === "above" ? "▲ above" : "▼ below"} ${fmtPrice(a.price)}`;
}

function alertFiredMsg(symbol, a) {
  if (a.dir === "zone") {
    return `${symbol} entered its Para-Sail buy zone: at or under ${fmtPrice(a.price)} `
      + `(${a.zone_pct ?? 8} % over its ${a.low_days ?? 30}-day low ${fmtPrice(a.low)})`;
  }
  return `${symbol} ${a.dir === "above" ? "rose above" : "dropped below"} ${fmtPrice(a.price)}`;
}

/* ----------------------------------------------------- the card */

function parasailCard(p) {
  if (p.locked) return `<div class="proof-empty">${esc(p.error || "The Para-Sail strategy is a Pro feature.")}</div>`;
  if (p.error) return `<div class="proof-empty">Couldn’t run Para-Sail on ${esc(p.symbol || "")}: ${esc(p.error)}</div>`;
  // Every interpolated number is forced to a Number: text goes through esc(), so nothing reaches
  // innerHTML unescaped even if the payload were ever not what the server sends.
  const z = p.zone;
  const capped = p.rules.cap != null;     // read BEFORE coercing: Number(null) is 0, and uncapped BTC is not "cap $0"
  const r = Object.fromEntries(Object.entries(p.rules).map(([k, v]) => [k, Number(v)]));
  p = { ...p, n: Number(p.n), n_sails: Number(p.n_sails) };
  const money = (v) => `${v >= 0 ? "+" : "−"}${potMoney(Math.abs(v))}`;
  const pct = (v) => `${v >= 0 ? "+" : ""}${Number(v).toFixed(1)}%`;
  const zoneLine = z.where === "inside"
    ? `<b class="up">In the buy zone</b> — ${fmtPrice(z.close)} is within ${r.zone_pct}% of the `
      + `${r.low_days}-day low ${fmtPrice(z.low)} (${esc(z.low_date)}).`
    : `<b>Above the buy zone</b> — ${fmtPrice(z.close)} sits ${Number(z.gap_pct).toFixed(1)}% over its top `
      + `${fmtPrice(z.top)} (${r.zone_pct}% over the ${r.low_days}-day low ${fmtPrice(z.low)}, ${esc(z.low_date)}).`;
  const result = p.hold
    ? `<b>${esc(p.symbol)} is held</b> — the coin we treat as money, so it's never sold for icing. `
      + `${p.n} buy${p.n === 1 ? "" : "s"} · most in at once ${potMoney(p.peak)} → <b>${money(p.profit)}</b> (${pct(p.roi)}).`
    : `${p.n} buy${p.n === 1 ? "" : "s"} · ${p.n_sails} para-sail${p.n_sails === 1 ? "" : "s"} `
      + `(sells ${r.sell_pct === 50 ? "half" : `${r.sell_pct}%`} at +${r.sail_pct}%) · most in at once ${potMoney(p.peak)} → `
      + `<b>${money(p.profit)}</b> (${pct(p.roi)}) · the same buys held: ${money(p.hold_profit)} (${pct(p.hold_roi)}).`;
  // Judged per dollar at risk: sold icing goes back into later buys, so para-sail never has more than
  // `peak` in, while holding the SAME buys needs every one of them paid for (`invested`). Comparing raw
  // dollars once told NVDA "holding did better by $553" when it needed $5,400 in against $2,000.
  const moreDollars = p.hold_profit > p.profit
    ? ` Holding made more dollars (${money(p.hold_profit)}) — with ${potMoney(p.invested)} in instead of ${potMoney(p.peak)}.`
    : "";
  const verdict = p.hold ? "" : p.n_sails === 0
    ? `<div class="dv-tilt">No wave has reached +${r.sail_pct}% yet — nothing sold, so para-sailing and holding are the same trades here so far.</div>`
    : Number(p.roi) >= Number(p.hold_roi)
    ? `<div class="dv-tilt good">Per dollar at risk, para-sailing did better here: ${pct(p.roi)} on the most it ever had in
        (${potMoney(p.peak)}) vs ${pct(p.hold_roi)} on the ${potMoney(p.invested)} it takes to hold the same buys.${moreDollars}</div>`
    : `<div class="dv-tilt bad">Holding the same buys did better here: ${pct(p.hold_roi)} on ${potMoney(p.invested)} vs
        ${pct(p.roi)} on ${potMoney(p.peak)} para-sailed — the icing trims the runners. That’s the trade.</div>`;
  const sellRule = p.hold ? " · held, never sold for icing" : ` · +${r.sail_pct}% → sell ${r.sell_pct === 50 ? "half" : `${r.sell_pct}%`}`;
  return `<div class="dca-vbox ps-card">
    <div class="dv-head"><i class="mi mi-sprout" aria-hidden="true"></i>Para-Sail strategy · <b>${esc(p.symbol)}</b>
      <span class="ps-when">${esc(p.since)} → ${esc(p.until)}</span></div>
    <div class="dv-note">${zoneLine}</div>
    <div class="dv-note">${result}</div>
    ${verdict}
    <div class="dv-truth sub">Rules: ${r.low_days}-day low · buy within ${r.zone_pct}% of it · one ${potMoney(r.fill)} fill a week at most
      · ${capped ? `cap ${potMoney(r.cap)} per name` : "no cap — held as money"}${sellRule}. <b>News cord:</b> withdrawals halted, bankruptcy, delisting,
      fraud charges or the team gone → sell all and stop buying. A price crash alone is not a death.</div>
    <div class="dca-form-actions"><button class="add-btn ghost" id="psWatch" type="button">Watch the zone</button></div>
    <div class="dv-truth sub">Backtested on this history after fees. Educational — not advice. Past prices don’t tell you the next move.</div>
  </div>`;
}

/* ----------------------------------------------------- page wiring (not unit-tested: DOM + network) */

/* A ticket per load: the tab opens on its default symbol and that first request can land AFTER the one
 * you asked for — 09-30 it painted NVDA over ETH. Only the newest load may paint the card. */
let parasailSeq = 0;

async function loadParasail(symbol, kind) {
  const box = $("#dcaParasail");
  if (!box) return;
  const ticket = ++parasailSeq;
  box.innerHTML = `<div class="proof-empty">Running Para-Sail on ${esc(symbol)}…</div>`;
  try {
    const p = await (await fetch(`/api/parasail?${new URLSearchParams({ symbol, kind })}`)).json();
    if (ticket !== parasailSeq) return;   // a newer symbol was asked for while this one was in flight
    box.innerHTML = parasailCard(p);
    const btn = $("#psWatch");
    if (btn) btn.addEventListener("click", () => watchZone(p, symbol, kind));
  } catch (err) {
    if (ticket === parasailSeq) box.innerHTML = `<div class="proof-empty">Para-Sail error: ${esc(err.message)}</div>`;
  }
}

/* One zone watcher per name: set it at today's zone top (the monthly low rolls, so the top moves —
 * running Para-Sail again resets it). Alerts are checked against Watchlist rows, so the name is added
 * there too; like every MarketPulse alert it fires while the app is open. */
async function watchZone(p, input, kind) {
  if (typeof features !== "undefined" && !features.alerts) { openUpgrade(); return; }
  try {
    const r = (await getMarkets(kind, [input]))[0];
    if (!r) { toast("sell", "Couldn’t find it", `${input} isn’t in the market feed`); return; }
    const k = keyOf(r);
    state.alerts[k] = (state.alerts[k] || []).filter((a) => a.dir !== "zone");
    state.alerts[k].push({ dir: "zone", price: p.zone.top, low: p.zone.low,
                           zone_pct: p.rules.zone_pct, low_days: p.rules.low_days });
    store.set("mp_alerts", state.alerts);
    state.watch.add(k);
    store.set("mp_watch", [...state.watch]);
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    toast("buy", `Watching ${r.symbol}’s buy zone`,
      `at or under ${fmtPrice(p.zone.top)} — today’s zone top. Added to your Watchlist; alerts fire while the app is open.`);
  } catch (err) {
    toast("sell", "Couldn’t set the watcher", err.message);
  }
}
