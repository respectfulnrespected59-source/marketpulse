/* MarketPulse — the Para-Sail rules on the options paper book (owner 2026-09-30).
 *
 * "C both": the app's signal picks the spread (the owner used "Load the signal's spread" on TSLA), and
 * these rules wrap it. Pure functions only — options-paper.js calls them; tests/test_options_parasail.py
 * pins them in Node's vm.
 *
 *   ON PLAN     bounce    = a CALL spread with the stock inside its 8 % low zone (buy the low)
 *               breakdown = a PUT spread with the stock within 2 % of its 30-day low (the TSLA trade:
 *                           entered at the low on 9/29, it broke to $345.88 the next morning)
 *               anything else is OFF PLAN: it can still be opened, and it is logged that way
 *   CAP         a spread costing more than 10 % of equity is off plan
 *   PARA-SAIL   once the position is up 40 % on what it cost — after the commission to open AND the one to
 *               close — close half. With one contract the icing is the whole position.
 *   TIME CHUTE  from noon New York time on expiry day: take it or cut it. TSLA 9/30 was near its $5 max at
 *               the morning low and worth $0.19 at the 4 PM close. On an expiring option the icing is the
 *               trade.
 *   NEWS CORD   same as stocks: withdrawals halted, bankruptcy, delisting, fraud, the team gone -> out.
 *   SCORECARD   a pre-registered forward test (docs/PARASAIL_OPTIONS_PREREG.md): trades grouped (a
 *               para-sail half is part of its trade), losers counted, on plan vs off. The verdict waits for
 *               25 trades and is decided by one number set in advance: expectancy after every cost > $0.
 */

const OPT_PS = {
  capPct: 10,          // most of equity one spread may cost
  sailAt: 0.40,        // the icing: up 40 % on what it cost
  atLowPct: 2,         // "at the low": within 2 % of the 30-day low
  chuteHourNY: 12,     // expiry day, from noon New York time
  target: 25,          // trades before the scorecard gives its verdict
};

function optRound2(v) {
  return Math.round(Number(v) * 100) / 100;
}

/* Is the signal's spread on plan? `zone` is /api/parasail's read on the underlying: {low, top, close, where}. */
function optSetup(direction, zone) {
  if (!zone || !isFinite(Number(zone.low)) || !isFinite(Number(zone.close)) || Number(zone.low) <= 0) {
    return { setup: "unknown", onPlan: false, why: "no 30-day read on the stock — can't tell if it's at the low" };
  }
  const overLow = (Number(zone.close) / Number(zone.low) - 1) * 100;
  const over = `${overLow.toFixed(1)}% over its 30-day low`;
  if (direction === "call" && zone.where === "inside") {
    return { setup: "bounce", onPlan: true, overLow, why: `calls in the low zone — ${over}` };
  }
  if (direction === "put" && overLow <= OPT_PS.atLowPct) {
    return { setup: "breakdown", onPlan: true, overLow, why: `puts at the low — ${over}, betting it breaks` };
  }
  return {
    setup: "off plan", onPlan: false, overLow,
    why: direction === "call"
      ? `calls ${over} — outside the 8% low zone`
      : `puts ${over} — not at the low (within ${OPT_PS.atLowPct}%)`,
  };
}

/* The cap: one spread may cost at most 10 % of equity. */
function optCapCheck(costUsd, equity) {
  const pct = Number(equity) > 0 ? optRound2((Number(costUsd) / Number(equity)) * 100) : Infinity;
  return { ok: pct <= OPT_PS.capPct, pct };
}

/* Para-sail due: up 40 % on cost after every commission, once per trade, and only on a real mark. */
function optSailDue(pos, mark) {
  if (!pos || pos.sailed || !mark || mark.net_usd == null || !isFinite(Number(mark.net_usd))) return false;
  return Number(mark.net_usd) >= OPT_PS.sailAt * Number(pos.cost_usd) - 1e-9;
}

/* Half the contracts, rounded down — but never zero: with one contract the icing is all of it. */
function optHalf(contracts) {
  return Math.max(1, Math.floor(Number(contracts) / 2));
}

/* Close `k` of the position's contracts at the current mark. Every dollar total scales with the contracts
 * (gross P&L and commissions are both per contract), so the closed part and the rest add back up exactly.
 * The rest keeps the position's id, so the book's live mark follows it; the closed record keeps the trade id. */
function optSplitClose(pos, mark, k) {
  const n = Number(pos.contracts);
  const shut = Math.min(n, Math.max(1, Math.floor(Number(k))));
  const f = shut / n;
  const trade = pos.trade || pos.id;
  const closed = {
    id: `${pos.id}-c${shut}of${n}`, trade, symbol: pos.symbol, contracts: shut, entry_debit: pos.entry_debit,
    exit: mark.mark, pnl: optRound2(Number(mark.net_usd) * f), setup: pos.setup, onPlan: pos.onPlan,
    sailed: shut < n, opened: pos.opened, closed: Date.now(),
  };
  if (shut === n) return { closed, rest: null };
  const keep = 1 - f;
  const rest = {
    ...pos, trade, contracts: n - shut, sailed: true,
    cost_usd: optRound2(Number(pos.cost_usd) * keep),
    commission: optRound2(Number(pos.commission) * keep),
    max_loss_usd: pos.max_loss_usd == null ? null : optRound2(Number(pos.max_loss_usd) * keep),
    max_profit_usd: pos.max_profit_usd == null ? null : optRound2(Number(pos.max_profit_usd) * keep),
    legs: (pos.legs || []).map((l) => ({ ...l, qty: n - shut })),
  };
  return { closed, rest };
}

/* New York's calendar date and hour at `nowMs` — the exchange's clock, DST and all. */
function optNewYorkNow(nowMs) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(nowMs));
  const get = (type) => (parts.find((p) => p.type === type) || {}).value;
  return { date: `${get("year")}-${get("month")}-${get("day")}`, hour: Number(get("hour")) };
}

/* Time parachute: expiry day from noon New York time — or any time after expiry if it's somehow still open. */
function optTimeParachute(expiry, nowMs) {
  const ny = optNewYorkNow(nowMs);
  if (ny.date > String(expiry)) return true;
  return ny.date === String(expiry) && ny.hour >= OPT_PS.chuteHourNY;
}

/* The pre-registered forward test. Only trades opened under these rules (they carry a `setup`) count, and
 * only once they are fully closed: `openTrades` lists trade ids still holding contracts (a para-sailed half
 * with the rest still riding can still turn into a loss). */
function optScorecard(closed, openTrades) {
  const stillOpen = new Set(openTrades || []);
  const trades = new Map();
  for (const rec of closed || []) {
    if (!rec || !rec.setup) continue;
    const key = rec.trade || rec.id;
    if (stillOpen.has(key)) continue;
    const tr = trades.get(key) || { pnl: 0, onPlan: rec.onPlan === true, setup: rec.setup };
    tr.pnl += Number(rec.pnl) || 0;
    trades.set(key, tr);
  }
  const list = [...trades.values()];
  const part = (xs) => ({ n: xs.length, total: optRound2(xs.reduce((a, x) => a + x.pnl, 0)) });
  const wins = list.filter((x) => x.pnl > 0);
  const losses = list.filter((x) => x.pnl <= 0);
  const total = optRound2(list.reduce((a, x) => a + x.pnl, 0));
  const n = list.length;
  const expectancy = n ? total / n : 0;
  const done = n >= OPT_PS.target;
  return {
    n, target: OPT_PS.target, done, total, expectancy, open: stillOpen.size,
    wins: wins.length, losses: losses.length,
    winRate: n ? Math.round((wins.length / n) * 100) : null,
    avgWin: wins.length ? wins.reduce((a, x) => a + x.pnl, 0) / wins.length : null,
    avgLoss: losses.length ? losses.reduce((a, x) => a + x.pnl, 0) / losses.length : null,
    onPlan: part(list.filter((x) => x.onPlan)),
    offPlan: part(list.filter((x) => !x.onPlan)),
    verdict: done ? (expectancy > 0 ? "pass" : "fail") : null,
  };
}
