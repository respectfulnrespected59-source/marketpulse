"""MarketPulse -> Obsidian: a daily options journal that cannot flatter itself.

Writes one dated note per run into the QMM-Vault, with Dataview-queryable
frontmatter, so months of live options data can be asked questions later:
which signals actually paid, how often the engine sat out, what the probe
verdicts looked like on the days you did nothing.

THE ONE RULE THIS FILE EXISTS TO ENFORCE
----------------------------------------
Record the boring days. A journal that only lands on days something happened
is worse than no journal, because the surviving notes read as a complete
record of a strategy that was really only sampled when it looked interesting.
So: every watchlist name appears every run — "sat out" and "unavailable" are
results and get written down like any other.

Two honest limits, stated in the note itself rather than hidden:

  * The CBOE chain is ~15 minutes delayed. A price here is not a fill.
  * The options paper book lives in the browser's localStorage, which a
    scheduled script cannot read. If no exported snapshot is present the note
    says "no open-position snapshot" — which is a different claim from "no
    open positions", and the difference matters.

Run:  python vault_journal.py
Env:  QMM_VAULT      vault root      (default C:\\Users\\respe\\Documents\\QMM-Vault)
      MP_API         API base        (default the live Render host)
      MP_POSITIONS   positions JSON  (default ./paper_positions.json)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# Derived from the home directory rather than hardcoded: this repo is public,
# and an absolute path would publish the author's username and folder layout
# for no benefit. Same location on the machine that runs it.
VAULT = os.environ.get("QMM_VAULT") or os.path.join(
    os.path.expanduser("~"), "Documents", "QMM-Vault")
JOURNAL_DIR = os.path.join(VAULT, "Trading Journal")
API = os.environ.get("MP_API", "https://marketpulse-22bi.onrender.com").rstrip("/")
POSITIONS_FILE = os.environ.get("MP_POSITIONS", os.path.join(HERE, "paper_positions.json"))

# The watchlist runs rich; the scan universe is where a small pot can actually
# afford a probe. Both go in the journal — see the module docstring.
WATCHLIST = ["TSLA", "SNDK", "NVDA", "MU", "WDC", "MRVL"]
SCAN = ["F", "SOFI", "PLTR", "INTC", "T", "BAC", "CSCO", "PFE",
        "SNAP", "HOOD", "NIO", "AAL", "WBD", "CMCSA", "UBER"]

TIMEOUT = 30
DISCLAIMER = ("_Educational record — **not advice**. Signals are RSI + MACD + trend. "
              "Options chain is CBOE **delayed ~15 minutes**, so a price here is a "
              "reading, not a fill._")


# --------------------------------------------------------------- helpers

def _s(v, dash="—"):
    """Render a value, or a dash. Never invents a number for a missing one."""
    return dash if v is None else str(v)


def _label(row: dict) -> str:
    lean = (row or {}).get("lean") or {}
    return str(lean.get("label") or "—")


def _sym(row: dict) -> str:
    return str((row or {}).get("symbol") or "?")


def fmt_squeeze(d) -> str:
    """One TTM squeeze, in the same grammar daily_plays.py and the board use.

    ON·N = coiled for N bars (the setup loading), FIRED = it just released
    (the trigger), OFF = nothing winding up. The arrow is momentum direction,
    filled when accelerating and hollow when not.

    Deliberately identical to daily_plays._fmt_sq so the journal and the daily
    report never describe the same reading two different ways.
    """
    if not isinstance(d, dict) or not d:
        return "n/a"
    mom = d.get("mom")
    accel = d.get("accel")
    if mom == "bull":
        arrow = "▲" if accel == "rising" else "△"
    elif mom == "bear":
        arrow = "▼" if accel == "falling" else "▽"
    else:
        arrow = ""
    state = d.get("state") or "?"
    state = f"ON·{d.get('bars', '?')}" if state == "on" else str(state).upper()
    return f"{state} {mom or ''}{arrow}".strip()


def squeeze_cell(row: dict) -> str:
    """Weekly + bi-weekly in one cell, flagged when coiled or in conflict."""
    sq = (row or {}).get("squeeze")
    if not isinstance(sq, dict) or not sq:
        return "n/a"
    cell = f"W {fmt_squeeze(sq.get('weekly'))} · 2W {fmt_squeeze(sq.get('biweekly'))}"
    if sq.get("coiled"):
        # The setup worth watching — a breakout is loading, direction unproven.
        cell += " · **COILED**"
    if sq.get("conflict"):
        cell += " · ⚠ timeframes disagree"
    return cell


def probe_verdict(plan) -> tuple[str, str]:
    """(verdict, cost) from options.probe_plan — its real shape, not a guess.

    `qualifies` is tri-state on purpose and each state is a different day:
      True  -> the cheapest readable probe fits the pot
      False -> it exists but costs more than the budget: WALK
      None  -> no directional lean at all, so there is nothing to probe

    Rendering any of these as a dash throws away the most decision-relevant
    thing on the row, which is exactly what the first version of this file did.
    """
    if not isinstance(plan, dict):
        return "—", "—"
    probe = plan.get("probe") or {}
    cost = probe.get("cost")
    cost_txt = f"${cost}" if cost is not None else "—"
    q = plan.get("qualifies")
    if q is None:
        return "no lean", cost_txt
    if q:
        return "fits", cost_txt
    need = plan.get("min_pot")
    return (f"**WALK** — needs ~${need} pot" if need else "**WALK** — too rich"), cost_txt


# ---------------------------------------------------------- frontmatter

def frontmatter(date: str, watch: list, scan: list, positions) -> str:
    """YAML block Dataview can query across every note in the folder."""
    counts: dict[str, int] = {}
    coiled = 0
    for row in list(watch or []) + list(scan or []):
        if not isinstance(row, dict) or row.get("error"):
            continue
        key = _label(row).lower().replace(" ", "_")
        if key and key != "—":
            counts[key] = counts.get(key, 0) + 1
        # Coiled names are the setups worth revisiting — countable so you can
        # ask Dataview "which coiled days actually broke out?" months later.
        if (row.get("squeeze") or {}).get("coiled"):
            coiled += 1

    lines = ["---", f"date: {date}", "type: trading-journal",
             f"watchlist_count: {len(watch or [])}",
             f"scan_count: {len(scan or [])}"]
    # "unknown" is deliberate: an unreadable book is not an empty book.
    lines.append("open_positions: " +
                 ("unknown" if positions is None else str(len(positions))))
    lines.append(f"coiled: {coiled}")
    for key in sorted(counts):
        lines.append(f"{key}: {counts[key]}")
    lines.append("tags: [marketpulse, options, journal]")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- sections

def watch_section(rows: list) -> str:
    if not rows:
        return ("## Watchlist\n\n_No watchlist data this run — the fetch returned "
                "nothing. Treat this as a gap, not a quiet day._\n")

    out = ["## Watchlist", "",
           "| Symbol | Signal | TTM squeeze | Spot | DTE | Suggested spread | Debit "
           "| Breakeven | Cheapest probe | Probe verdict |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = _sym(row)
        if row.get("error"):
            out.append(f"| **{sym}** | unavailable | — | — | — | — | — | — | — "
                       f"| {row['error']} |")
            continue
        sp = row.get("spread") or {}
        verdict, probe_cost = probe_verdict(row.get("probe_plan"))
        if sp:
            legs = (f"{_s((sp.get('long') or {}).get('strike'))}/"
                    f"{_s((sp.get('short') or {}).get('strike'))} "
                    f"{'P' if sp.get('direction') == 'put' else 'C'}")
            debit = f"${_s(sp.get('per_contract'))}"
            be = _s(sp.get("breakeven"))
        else:
            # No directional spread is a real outcome, not a missing row.
            legs, debit, be = "— sat out —", "—", "—"
        out.append(
            f"| **{sym}** | {_label(row)} | {squeeze_cell(row)} | {_s(row.get('spot'))} "
            f"| {_s(row.get('dte'))} | {legs} | {debit} | {be} | {probe_cost} "
            f"| {verdict} |")
    out.append("")
    return "\n".join(out)


def scan_section(rows: list) -> str:
    usable = [r for r in (rows or []) if isinstance(r, dict)]
    if not usable:
        return ("## Scan universe (cheap-probe sweep)\n\n"
                "_Nothing qualified in the sweep this run._\n")
    out = ["## Scan universe (cheap-probe sweep)", "",
           "| Symbol | Signal | Spot | Cheapest probe | Verdict |", "|---|---|---|---|---|"]
    for row in usable:
        sym = _sym(row)
        if row.get("error"):
            out.append(f"| {sym} | unavailable | — | — | {row['error']} |")
            continue
        verdict, probe_cost = probe_verdict(row.get("probe_plan"))
        out.append(f"| {sym} | {_label(row)} | {_s(row.get('spot'))} "
                   f"| {probe_cost} | {verdict} |")
    out.append("")
    return "\n".join(out)


def positions_section(positions) -> str:
    if positions is None:
        return ("## Open paper positions\n\n"
                "_**No open-position snapshot available.** The options book lives in the "
                "browser's localStorage, which this scheduled job cannot read. Export it "
                "to `paper_positions.json` to get a daily P&L trail here. This is a blind "
                "spot, not an empty book._\n")
    if not positions:
        return "## Open paper positions\n\n_No open positions on this date._\n"

    out = ["## Open paper positions", "",
           "| Position | Contracts | Mark | Open P&L | DTE | Status |", "|---|---|---|---|---|---|"]
    for p in positions:
        if not isinstance(p, dict):
            continue
        net = p.get("net_usd")
        # An unquoted position must never render as 0.00 — that hides a loss.
        pnl = "unquoted" if net is None else f"${net:,.2f}"
        out.append(f"| {_sym(p)} | {_s(p.get('contracts'))} | {_s(p.get('mark'))} "
                   f"| {pnl} | {_s(p.get('dte'))} | {_s(p.get('status'))} |")
    out.append("")
    return "\n".join(out)


def render_note(date: str, watch: list, scan: list, positions) -> str:
    return "\n".join([
        frontmatter(date, watch, scan, positions),
        f"# Trading Journal — {date}",
        "",
        DISCLAIMER,
        "",
        watch_section(watch),
        positions_section(positions),
        scan_section(scan),
        "---",
        "",
        "Related: [[MarketPulse]] · [[Options Journal Index]]",
        "",
    ])


def note_name(date: str) -> str:
    """Dated filename — a rerun updates the day, never appends a second note."""
    return f"{date}.md"


def heartbeat_text(date: str, ok: bool, detail: str) -> str:
    """The alarm. A check that cannot go red is not a check.

    Written every run, pass or fail, so "the journal stopped" is visible as a
    stale date instead of as an absence nobody notices.
    """
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state = "ok" if ok else "FAILED"
    return (f"# MarketPulse journal heartbeat\n\n"
            f"- last run: **{stamp}**\n"
            f"- for date: **{date}**\n"
            f"- status: **{state}**\n"
            f"- detail: {detail}\n\n"
            f"_If `last run` is older than the last trading day, the job is dead — "
            f"check Task Scheduler for `MarketPulse Daily Plays`._\n")


# ------------------------------------------------------------------ I/O

def fetch(path: str, params: dict) -> dict:
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "MarketPulse-Journal/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:  # noqa: S310
        return json.loads(fh.read().decode("utf-8"))


def collect(symbols: list[str]) -> list[dict]:
    """One chain read per symbol. A failure is recorded, never dropped."""
    out = []
    for sym in symbols:
        try:
            data = fetch("/api/options", {"symbol": sym, "pot": 300})
            data.setdefault("symbol", sym)
            out.append(data)
        except Exception as exc:  # noqa: BLE001
            out.append({"symbol": sym, "error": f"{type(exc).__name__}"})
            print(f"[journal] {sym}: {exc}", file=sys.stderr)
    return out


def fetch_marks(positions: list) -> list:
    """Mark the book — in-process first, HTTP only as a fallback.

    This script sits in the repo beside app.py, so it can call the marker
    directly and read CBOE itself. That matters for a scheduled job: at 08:30
    there is no local server running, and the deployed host only gains
    /api/options/mark after a deploy. Depending on either would mean the
    positions section silently reads "unquoted" every morning — present in the
    note, but useless.

    daily_plays.py already imports app for the same reason.
    """
    try:
        import app  # noqa: PLC0415  — optional, and heavy to import at module load
        return app.options_mark(positions).get("marks") or []
    except Exception as exc:  # noqa: BLE001
        print(f"[journal] local mark unavailable ({exc}); trying the API",
              file=sys.stderr)

    body = json.dumps({"positions": positions}).encode("utf-8")
    req = urllib.request.Request(f"{API}/api/options/mark", data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "MarketPulse-Journal/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:  # noqa: S310
        return (json.loads(fh.read().decode("utf-8")) or {}).get("marks") or []


def load_positions():
    """The exported book, or None meaning 'could not see it'."""
    if not os.path.exists(POSITIONS_FILE):
        return None
    try:
        with open(POSITIONS_FILE, encoding="utf-8") as fh:
            book = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"[journal] positions unreadable: {exc}", file=sys.stderr)
        return None
    positions = book.get("open") if isinstance(book, dict) else book
    if not isinstance(positions, list):
        return None
    try:
        return fetch_marks(positions)
    except Exception as exc:  # noqa: BLE001
        # Better an unmarked position than a silently dropped one.
        print(f"[journal] mark failed: {exc}", file=sys.stderr)
        return positions


def main() -> int:
    date = datetime.now().strftime("%Y-%m-%d")
    ok, detail, note = True, "", None
    try:
        watch = collect(WATCHLIST)
        scan = collect(SCAN)
        positions = load_positions()
        failed = sum(1 for r in watch + scan if r.get("error"))
        detail = f"{len(watch)} watch · {len(scan)} scan · {failed} failed"
        # Every name failing means the API is down; a note full of "unavailable"
        # would look like data. Fail loudly instead.
        ok = failed < len(watch) + len(scan)
        note = render_note(date, watch, scan, positions)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[journal] fatal: {exc}", file=sys.stderr)

    try:
        os.makedirs(JOURNAL_DIR, exist_ok=True)
        if note is not None:
            path = os.path.join(JOURNAL_DIR, note_name(date))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(note)
            print(f"[journal] wrote {path}")
        with open(os.path.join(JOURNAL_DIR, "_heartbeat.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(heartbeat_text(date, ok, detail))
    except OSError as exc:
        print(f"[journal] could not write vault: {exc}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
