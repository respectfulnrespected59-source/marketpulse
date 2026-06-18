"""MarketPulse — daily options-lean report.

Runs the live engine (signal + weekly/bi-weekly TTM squeeze + 5/14/21 MA stack +
session VWAP) on the dashboard's stock universe and writes an educational
calls-vs-puts read to:
  reports/<YYYY-MM-DD>.md   (archive)
  <Desktop>/MarketPulse_Daily.md   (latest, easy to find)

Scheduled weekday mornings via Windows Task Scheduler. NOT financial advice.
"""
from __future__ import annotations

import os
from datetime import datetime

import app  # reuses fetch_stocks -> signal + squeeze + guides

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "reports")
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop", "MarketPulse_Daily.md")


def _lean(row: dict) -> tuple[str, str]:
    """Return (lean, note) — the educational options posture for one ticker."""
    sig = row.get("signal") or {}
    label = sig.get("label", "NEUTRAL")
    rsi = sig.get("rsi") or 0
    sq = row.get("squeeze") or {}
    wk, bw = sq.get("weekly"), sq.get("biweekly")
    moms = [x["mom"] for x in (wk, bw) if x]
    conflict = len(set(moms)) > 1
    squeeze_on = (wk and wk["state"] == "on") or (bw and bw["state"] == "on")

    if squeeze_on and (label == "NEUTRAL" or conflict):
        return ("EITHER-WAY", "coiled squeeze + unresolved direction — long strangle "
                              "plays the breakout either way (pay double premium)")
    if label in ("STRONG BUY", "BUY"):
        if rsi > 70:
            return ("CALLS (caution)", "trend up but overbought — wait for a pullback "
                                       "or use a tight call debit spread")
        return ("CALLS", "call debit spread to ride the trend")
    if label in ("SELL", "STRONG SELL"):
        return ("PUTS", "put debit spread; keep it tight if the longer-term trend is up")
    return ("NO EDGE", "signal is neutral — sit it out")


def _fmt_sq(d):
    if not d:
        return "n/a"
    arrow = ("▲" if d["accel"] == "rising" else "△") if d["mom"] == "bull" else (
        "▼" if d["accel"] == "falling" else "▽")
    state = f"ON·{d['bars']}" if d["state"] == "on" else d["state"].upper()
    return f"{state} {d['mom']}{arrow}"


def build_report(rows: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# MarketPulse — Daily Read · {now}", "",
           "_Educational signal-to-structure mapping. Not financial advice. "
           "Check earnings/IV before any options play._", ""]
    for r in sorted(rows, key=lambda x: x.get("symbol", "")):
        if r.get("error"):
            out.append(f"## {r['symbol']} — data unavailable\n")
            continue
        sig = r["signal"]
        g = r.get("guides") or {}
        sq = r.get("squeeze") or {}
        lean, note = _lean(r)
        out += [
            f"## {r['symbol']} — {sig['label']}  ·  {lean}",
            f"- Price ${r['price']} ({r['change']:+}%) · RSI {sig.get('rsi')}",
            f"- Signal: {' · '.join(sig.get('reasons', []))}",
            f"- TTM squeeze — weekly: {_fmt_sq(sq.get('weekly'))} · "
            f"bi-weekly: {_fmt_sq(sq.get('biweekly'))}",
            f"- MA 5/14/21: {g.get('ma5')}/{g.get('ma14')}/{g.get('ma21')} "
            f"({g.get('stack')}) · VWAP {g.get('vwap')} (price {g.get('vs_vwap')})",
            f"- **Lean: {lean}** — {note}",
            "",
        ]
    out.append("---\n_Slow and alive beats fast and liquidated. Defined-risk, size small._")
    return "\n".join(out)


def main() -> None:
    rows = app.fetch_stocks(app.DEFAULT_STOCKS)
    report = build_report(rows)
    os.makedirs(REPORTS, exist_ok=True)
    dated = os.path.join(REPORTS, datetime.now().strftime("%Y-%m-%d") + ".md")
    for path in (dated, DESKTOP):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(report)
        except OSError as exc:
            print(f"could not write {path}: {exc}")
    print(f"wrote {dated}")
    print(f"wrote {DESKTOP}")


if __name__ == "__main__":
    main()
