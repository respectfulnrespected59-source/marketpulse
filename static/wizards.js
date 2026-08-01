/* MarketPulse — DCA wizard and Proof Mode.
 *
 * The two long-form tools: dollar-cost-average planning and the backtest that shows what a rule would have done.
 *
 * Split out of app.js to keep each file readable. Classic script, so it
 * shares one global scope with app.js and the other panels; everything
 * here is a declaration and nothing runs at load time. app.js is loaded
 * last because its init() call reaches into these.
 */

/* ----------------------------------------------------- dca wizard */

let dcaLoaded = false;

const DCA_LABEL = { plain: "Plain DCA", tilt: "Signal-Tilt DCA", lump: "Lump Sum" };

// QuickFill for the DCA per-period contribution — readout shows annualized $.
let dcaMonthlyQf = null;

/* The amount used to be inert until you pressed "Build plan" again, so the
 * cards kept showing the OLD budget while the input said something else — the
 * wizard read as if it were ignoring you entirely. The dial drives the numbers
 * now. Debounced, so typing "1000" is one rebuild instead of four, and any
 * explicit load cancels a pending one (home.js sets the amount and then calls
 * loadDca itself — without the cancel that would fetch the same plan twice). */
let dcaRerunTimer = null;
const DCA_RERUN_MS = 550;
function dcaScheduleRerun() {
  if (!dcaLoaded) return;   // still mounting; the first load is about to fire
  clearTimeout(dcaRerunTimer);
  dcaRerunTimer = setTimeout(loadDca, DCA_RERUN_MS);
}

function ensureDcaQf() {
  if (dcaMonthlyQf || typeof QuickFill === "undefined") return;
  const el = $("#dcaMonthlyQf");
  if (!el) return;
  dcaMonthlyQf = QuickFill.mount(el, {
    amount: 200, chips: [50, 100, 200, 500, 1000], step: 25, min: 10,
    onChange: dcaScheduleRerun,
    convert: (amt) => {
      const cad = $("#dcaCadence").value;
      const perYr = cad === "weekly" ? 52 : cad === "biweekly" ? 26 : 12;
      const annual = Math.round(amt * perYr);
      return `$${Math.round(amt)} ${cad} = <b>$${annual.toLocaleString()}/yr</b> invested`;
    },
  });
  $("#dcaCadence").addEventListener("change", () => {
    if (dcaMonthlyQf) dcaMonthlyQf.refreshConversion();
    dcaScheduleRerun();
  });
}

async function loadDca() {
  clearTimeout(dcaRerunTimer);   // an explicit load supersedes a pending one
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

/* The headline is the DOLLAR outcome, not the return %.
 *
 * Return % is mathematically identical at every contribution size — double the
 * buy and you double the dollars, not the rate. Leading with % therefore made
 * the whole wizard look broken: change $200 to $2,000 and the big number on
 * every card stayed put. The dollars are what your amount actually moves, so
 * the dollars lead and the (invariant) rate rides shotgun. */
function dcaCard(key, x, win) {
  const rc = (x.return_pct ?? 0) >= 0 ? "up" : "down";
  const ret = x.return_pct == null ? "—" : `${x.return_pct > 0 ? "+" : ""}${x.return_pct}%`;
  const prof = x.profit == null ? "—"
    : `${x.profit >= 0 ? "+" : "−"}${potMoney(Math.abs(x.profit))}`;
  return `<div class="dca-card ${win ? "win" : ""}">
    <div class="dc-name">${DCA_LABEL[key]}${win ? ` <span class="dc-crown">▲ won</span>` : ""}</div>
    <div class="dc-val ${rc}">${potMoney(x.final_value)}</div>
    <div class="dc-sub">${potMoney(x.invested)} in → <b class="${rc}">${prof}</b>
      <span class="dc-ret ${rc}">${ret}</span></div>
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
    <div class="dv-scale">📐 <b>Why the percentages don't move when you change your amount.</b>
      At ${potMoney(p.per_period)} every ${esc(p.cadence)}, this window put
      <b>${potMoney(b.plain.invested)}</b> to work. Change that to
      ${potMoney(p.per_period * 10)} and every dollar figure above scales by 10× —
      but the return %, the winner, and the read stay <i>exactly</i> the same.
      DCA is linear in the contribution: your amount sets <b>how much money</b> is
      at stake, the asset and the window set <b>the rate</b>. That's the math, not
      a stuck calculator — change the <b>symbol</b>, <b>cadence</b> or <b>window</b>
      to move the percentages.</div>
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

