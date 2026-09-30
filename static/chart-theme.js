/* MarketPulse — the chart look, in one place.
 *
 * Shared by the app's live chart (chart-engine.js) and the landing page's hero
 * chart (landing/hero-chart.js), so the chart a visitor meets on the front page
 * is exactly the chart they get in the app. Colours come from the page's own
 * CSS tokens; times are shifted into local time because Lightweight Charts
 * only speaks UTC.
 *
 * Classic script, declarations only. Needs window.LightweightCharts at call time.
 */

const PC_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const PC_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// Intraday bars get a clock on the axis; daily and weekly bars get a date.
const PC_INTRADAY_TFS = new Set(["1m", "5m", "10m", "15m", "30m", "1h"]);
// Assigned by position, so the first EMA period a trader lists always gets gold.
const PC_EMA_COLORS = ["#f5c66b", "#5b8def", "#c471ed", "#4ecb8f"];
const PC_RIGHT_PAD = 6;        // empty slots right of the newest bar: where the live candle forms

/* Lightweight Charts has no time zone setting and labels everything in UTC. The
 * documented fix is to hand it times already shifted into local time, so the
 * axis reads the viewer's own clock. The shift can run a bar backwards across a
 * DST fall-back, and the library rejects unsorted data, so each time is forced
 * strictly past the one before it. Nothing converts a chart time back into a
 * real one: every lookup goes through the bar index.
 *
 * Daily and weekly candles are NOT shifted. A day is a label, not a moment: the
 * candle dated the 5th is the 5th for every viewer (and in every lesson's
 * narration). Shifted into Pacific time, a crypto daily candle read the 4th. */
function pcTimes(ts, n, tf) {
  const local = tf == null || PC_INTRADAY_TFS.has(tf);
  const out = new Array(n);
  let prev = -Infinity;
  for (let i = 0; i < n; i++) {
    const t = local ? ts[i] - new Date(ts[i] * 1000).getTimezoneOffset() * 60 : ts[i];
    prev = t > prev ? t : prev + 1;
    out[i] = prev;
  }
  return out;
}

function pcToken(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/* The page's palette. Both pages define these tokens; the fallbacks are QMM's. */
function pcColors() {
  return {
    line: pcToken("--line", "#2c2140"), dim: pcToken("--text-dim", "#a99fc0"),
    buy: pcToken("--buy", "#2fd180"), sell: pcToken("--sell", "#ff5d6c"),
    mono: pcToken("--mono", "ui-monospace, monospace"),
  };
}

function _pcPad(v) { return String(v).padStart(2, "0"); }

function pcTickLabel(time, type) {
  const d = new Date(time * 1000);            // shifted: read it back with UTC getters
  if (type === 0) return String(d.getUTCFullYear());
  if (type === 1) return PC_MONTHS[d.getUTCMonth()];
  if (type === 2) return `${PC_MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
  return `${_pcPad(d.getUTCHours())}:${_pcPad(d.getUTCMinutes())}`;
}

/* Crosshair label; `getTf` says which timeframe is on screen right now. */
function pcCrosshairFormatter(getTf) {
  return (time) => {
    const d = new Date(time * 1000);
    const day = `${PC_DAYS[d.getUTCDay()]} ${PC_MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
    if (!PC_INTRADAY_TFS.has(getTf())) return `${day} ${d.getUTCFullYear()}`;
    return `${day}  ${_pcPad(d.getUTCHours())}:${_pcPad(d.getUTCMinutes())}`;
  };
}

/* Drag pans only when `drag` is on; the wheel always zooms, and a vertical
 * swipe always scrolls the page, so the chart never traps a phone user. */
function pcScrollOpts(drag) {
  return { mouseWheel: true, pressedMouseMove: drag, horzTouchDrag: drag, vertTouchDrag: false };
}

/* The terminal look: transparent over the card, hairline grid, gold crosshair. */
function pcChartOptions(LW, c, getTf) {
  const cross = { color: "rgba(232,194,90,0.55)", width: 1, style: LW.LineStyle.Dashed,
                  labelBackgroundColor: "#2c2140" };
  return {
    autoSize: true,
    layout: {
      background: { type: LW.ColorType.Solid, color: "transparent" },
      textColor: c.dim,
      fontFamily: c.mono,
      fontSize: 11,
      attributionLogo: true,   // the library's license notice asks for this credit
      panes: { separatorColor: c.line, separatorHoverColor: "rgba(232,194,90,0.35)", enableResize: true },
    },
    grid: { vertLines: { color: "rgba(169,159,192,0.05)" }, horzLines: { color: "rgba(169,159,192,0.07)" } },
    crosshair: { mode: LW.CrosshairMode.Normal, vertLine: cross, horzLine: cross },
    rightPriceScale: { borderColor: c.line, scaleMargins: { top: 0.08, bottom: 0.18 } },
    timeScale: {
      borderColor: c.line, rightOffset: PC_RIGHT_PAD, barSpacing: 8, minBarSpacing: 1,
      timeVisible: true, secondsVisible: false,
      tickMarkFormatter: pcTickLabel,
    },
    localization: { timeFormatter: pcCrosshairFormatter(getTf) },
    handleScroll: pcScrollOpts(true),
  };
}

function pcCandleOptions(LW, c) {
  return { upColor: c.buy, downColor: c.sell, wickUpColor: c.buy, wickDownColor: c.sell,
           borderVisible: false, priceLineStyle: LW.LineStyle.Dotted };
}

/* Volume sits in the bottom sixth of the candle pane, on its own hidden scale. */
function pcAddVolume(chart, LW, extra) {
  const vol = chart.addSeries(LW.HistogramSeries, {
    priceScaleId: "vol", priceFormat: { type: "volume" },
    lastValueVisible: false, priceLineVisible: false, ...(extra || {}),
  }, 0);
  chart.priceScale("vol", 0).applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false });
  return vol;
}

/* Enough decimals to see the digits that move, from $1,800 stocks to PEPE. */
function pcPrecision(price) {
  if (!(price > 0)) return 2;
  if (price >= 1) return 2;
  if (price >= 0.01) return 4;
  return Math.min(10, Math.floor(-Math.log10(price)) + 4);
}

function pcPriceFormat(price) {
  const precision = pcPrecision(price);
  return { type: "price", precision, minMove: Math.pow(10, -precision) };
}

function pcCompact(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return String(Math.round(v));
}
