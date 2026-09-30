"""Compile an authored lesson + its frozen tape into exact chart steps.

A lesson is narration that describes a chart. The compiler makes it
impossible for the two to disagree:
  - bars are authored by index ("bar": -1 = the last bar) and compiled to the
    tape's exact timestamps and prices;
  - every number spoken is computed from the tape ({plan.avg:,.0f});
  - nothing is drawn on a bar the viewer can't see yet (bars after the replay
    cursor are hidden, so the drawing would silently not appear);
  - nothing is drawn off the chart;
  - no text promises money (the honesty lint: narration, titles, labels).

Pure: no Kokoro, no network. build_all() takes the voice as a function so it
is testable; tools/classes/build.py passes the real one.

Authored ops (in a step's "do" list):
  frame {from, to}           show bars from..to: what is on screen. The cursor and
                             every mark or line drawn must sit inside it.
  seek  {bar}                replay cursor to a bar
  play  {to}                 reveal bars up to `to` while the step plays
                             (any bar may be a computed one by name: "u.worst_bar")
  mark  {bar, at|price|var, dir}
  line  {a: {bar, at|price|var}, b: {...}}
  level {price|var, title}   horizontal line
  buys  {var}                every buy of a DCA plan revealed so far and not yet drawn
  clear                      remove the lesson's drawings
  spot  {tool, label}        spotlight a real app control while this step plays
                             (teaches the app itself; tool must be in TOOLS)

Ordering contract (the player must match it): within a step, seeks and plays
set the cursor first; drawings are validated against — and shown at — the
step's FINAL cursor. The chart starts on the tape's last bar.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import string
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

LESSON_ID_RE = re.compile(r"[a-z]{2,8}-\d{2}")
WHO = ("T", "Q")                      # Tess teaches, Quantus asks
PRICE_AT = {"open": 0, "high": 1, "low": 2, "close": 3}
LEVEL_MARGIN = 0.10                   # a drawing may sit this far outside the framed bars' range
MAX_TEXT = 120                        # titles and labels (class_catalog caps titles the same)
# App controls a lesson may spotlight. Names, not selectors: the player owns the
# mapping to the page (static/lesson-player.js LESSON_TOOL_SELECTORS).
TOOLS = frozenset({"search", "timeframes", "indicators", "prepost", "mark", "trend", "undo", "clear",
                   "fit", "fullscreen", "replay", "play", "step", "speed", "dial", "live", "calls",
                   "dca_tab", "coach_tab", "paper_tab"})
VOICE_VERSION = "kokoro-v1"           # default voice key; build.py passes the real one
STEP_GAP_MS = 450                     # the player's breath between steps (lesson-player.js LESSON_GAP_MS)
# A class we charge for is a full class: every lesson in it, the free one that
# sells it included, runs at least this long or the build stops.
MIN_PAID_CLASS_LESSON_S = 480

HONESTY = (
    (re.compile(r"\bguarantee", re.I), "a guarantee"),
    (re.compile(r"\bwill\s+(definitely\s+)?(go up|rise|climb|moon|profit|pay off)\b", re.I), "a price prediction"),
    (re.compile(r"\bdefinitely\s+(go up|rise|profit|pay off|win)\b", re.I), "a price prediction"),
    (re.compile(r"\byou('ll|\s+will)\s+(make|earn)\b", re.I), "a promise of income"),
    (re.compile(r"\b\d+(\.\d+)?\s*%\s*(a|per|every)\s+(day|week|month|year)\b", re.I), "a promised rate"),
    (re.compile(r"\b(risk[- ]free|no risk)\b", re.I), "no-risk"),
    (re.compile(r"\b(can'?t|cannot|never)\s+lose\b", re.I), "can't lose"),
    (re.compile(r"\bget\s+rich\b", re.I), "get rich"),
    (re.compile(r"\bdouble\s+your\s+money\b", re.I), "double your money"),
    (re.compile(r"\bsure\s+thing\b", re.I), "a sure thing"),
)
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})
# What the voice should SAY differently from what the caption shows.
SPEECH_FIXES = ((re.compile(r"\bbreakeven\b", re.I), "break even"),
                (re.compile(r"\bDCA\b"), "D C A"),
                (re.compile(r"S&P 500"), "S and P five hundred"),
                (re.compile(r"\bSPY\b"), "S P Y"),
                (re.compile(r"\bEMA\b"), "E M A"),
                (re.compile(r"\bTTM\b"), "T T M"))

Bake = Callable[[str, str], "tuple[bytes, int]"]   # (speech text, who) -> (mp3 bytes, duration ms)


class LessonError(ValueError):
    """A lesson that would teach something the chart doesn't show."""


# ------------------------------------------------------------------ the tape
def check_tape(tape: object) -> None:
    if not isinstance(tape, dict) or not isinstance(tape.get("ts"), list) or not isinstance(tape.get("ohlc"), list):
        raise LessonError("a tape needs ts and ohlc lists")
    ts, ohlc = tape["ts"], tape["ohlc"]
    if len(ts) < 2 or len(ts) != len(ohlc):
        raise LessonError(f"a tape needs 2+ bars with one ohlc per ts ({len(ts)} ts, {len(ohlc)} ohlc)")
    if any(not isinstance(t, int) for t in ts) or any(b <= a for a, b in zip(ts, ts[1:])):
        raise LessonError("tape timestamps must be increasing integers")
    for row in ohlc:
        if not (isinstance(row, list) and len(row) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in row)):
            raise LessonError(f"bad tape bar {row!r}")


def _bar(tape: dict, i: object, where: str = "") -> int:
    n = len(tape["ts"])
    if not isinstance(i, int) or isinstance(i, bool) or not -n <= i < n:
        raise LessonError(f"bar {i} is outside the tape (0..{n - 1}){where}")
    return i % n


def _close(tape: dict, i: int) -> float:
    return float(tape["ohlc"][i][3])


# ------------------------------------------------------------------ computed values
SIDE_EPS = 1e-9        # percent: closer to the line than this is ON the line


def _window(spec: dict, tape: dict, what: str) -> tuple[int, int]:
    """The bars a plan covers, start..end inclusive (default: the whole tape), so
    one long tape can hold several stories."""
    start = _bar(tape, spec.get("start", 0), f" in {what}")
    end = _bar(tape, spec.get("end", -1), f" in {what}")
    if end < start:
        raise LessonError(f"{what}: end (bar {end}) is before start (bar {start})")
    return start, end


def _side(gap_pct: float) -> str:
    """Where price sits against an average-cost line. The narration says
    {plan.side}, never a typed "above", so the word can't contradict the chart.
    A buy day sits ON the line: 1/(1/p) is not always exactly p, so float dust
    must not read as "below" (the same tolerance _underwater uses)."""
    return "below" if gap_pct < -SIDE_EPS else "above"


def _dca(spec: dict, tape: dict) -> SimpleNamespace:
    every = spec.get("every")
    if not isinstance(every, int) or isinstance(every, bool) or every < 1:
        raise LessonError("a dca plan needs every >= 1")
    start, end = _window(spec, tape, "a dca plan")
    buys = [{"bar": i, "ts": tape["ts"][i], "price": _close(tape, i)}
            for i in range(start, end + 1, every)]
    prices = [b["price"] for b in buys]
    # Same dollars each time: average cost = total dollars / total coins (harmonic mean).
    avg, last = len(prices) / sum(1 / p for p in prices), _close(tape, end)
    gap = (last / avg - 1) * 100
    cheap, dear = min(buys, key=lambda b: b["price"]), max(buys, key=lambda b: b["price"])
    return SimpleNamespace(buys=buys, n=len(buys), avg=avg, mean=sum(prices) / len(prices),
                           first_price=_close(tape, start), last_price=last,
                           first_date=_date(tape["ts"][start]), last_date=_date(tape["ts"][end]),
                           gap_pct=gap, gap_abs=abs(gap), side=_side(gap),
                           cheapest_bar=cheap["bar"], cheapest_price=cheap["price"],
                           cheapest_date=_date(cheap["ts"]), priciest_bar=dear["bar"],
                           priciest_price=dear["price"], priciest_date=_date(dear["ts"]),
                           coin_ratio=dear["price"] / cheap["price"])


def _breakeven(spec: dict, _tape: dict) -> SimpleNamespace:
    right, strike, premium = spec.get("right"), spec.get("strike"), spec.get("premium")
    if right not in ("put", "call") or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                               for v in (strike, premium)):
        raise LessonError("breakeven needs right put|call, strike and premium")
    value = strike - premium if right == "put" else strike + premium
    return SimpleNamespace(value=round(value, 4), strike=strike, premium=premium, right=right)


def _dca_at(spec: dict, tape: dict) -> SimpleNamespace:
    """The plan as it stood on `bar`: buys so far, their average cost, and how far
    price sat from it. gap_pct is SIGNED (negative = below your line); gap_abs and
    side say the same thing in words. (underwater.worst_gap is a positive depth.)
    need_pct / lump_need_pct exist only while that buyer is below their price."""
    bar = _bar(tape, spec.get("bar"), " in dca_at")
    plan = _dca({"every": spec.get("every"), "start": spec.get("start", 0)}, tape)
    buys = [b["price"] for b in plan.buys if b["bar"] <= bar]
    if not buys:
        raise LessonError(f"dca_at: no buys yet at bar {bar}")
    avg = len(buys) / sum(1 / p for p in buys)
    price = _close(tape, bar)
    gap = (price / avg - 1) * 100
    entry = plan.first_price                  # what the all-at-once buyer paid on the plan's first day
    lump_gap = (price / entry - 1) * 100
    # How far price must climb from here to get each buyer back to even: only
    # while they are below it (a climb of "0 percent" is not a fact worth narrating).
    need = {name: (cost / price - 1) * 100
            for name, cost, g in (("need_pct", avg, gap), ("lump_need_pct", entry, lump_gap)) if g < -SIDE_EPS}
    return SimpleNamespace(n=len(buys), avg=avg, price=price, gap_pct=gap, gap_abs=abs(gap),
                           side=_side(gap), date=_date(tape["ts"][bar]), lump_price=entry,
                           lump_gap_abs=abs(lump_gap), lump_side=_side(lump_gap), **need)


WIZARD_CADENCES = ("weekly", "biweekly", "monthly")


def _tilt_lean(buys: list, tape: dict) -> dict:
    """Which scheduled buys the tilt boosted and which it trimmed, and at what
    prices: the mechanism behind its result, not just the result.

    tilt_min_* is the most-trimmed buy and tilt_max_* the most-boosted. The tilt
    is capped, so several buys can share the extreme size: *_count says how many,
    and of those the example is the LOWEST-priced trimmed buy and the
    HIGHEST-priced boosted one (say so when narrating it). With nothing trimmed
    (or boosted) there is no such buy, and no tilt_min_* (tilt_max_*)."""
    at = {str(t): i for i, t in enumerate(tape["ts"])}
    more, less = [b for b in buys if b["tilt"] > 1], [b for b in buys if b["tilt"] < 1]
    out = {"tilt_more": len(more), "tilt_less": len(less), "tilt_even": len(buys) - len(more) - len(less)}
    for name, group in (("more", more), ("less", less)):
        if group:
            out[f"tilt_{name}_price"] = sum(b["price"] for b in group) / len(group)
    for name, group, pick in (("min", less, min), ("max", more, max)):
        if not group:
            continue
        b = pick(group, key=lambda b: (b["tilt"], b["price"]))
        out.update({f"tilt_{name}_mult": b["tilt"], f"tilt_{name}_price": b["price"],
                    f"tilt_{name}_amount": b["amount"], f"tilt_{name}_bar": at[b["date"]],
                    f"tilt_{name}_date": _date(int(b["date"])),
                    f"tilt_{name}_count": sum(x["tilt"] == b["tilt"] for x in group)})
    return out


def _wizard(spec: dict, tape: dict) -> SimpleNamespace:
    """What the app's DCA Wizard would show for this tape: plain DCA, signal-tilt
    DCA and lump sum, through dca.py itself (same cost model), so a lesson never
    quotes a number the student can't reproduce in the app."""
    import sys
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    import backtest
    import dca
    monthly, cadence = spec.get("monthly"), spec.get("cadence", "monthly")
    if (not isinstance(monthly, (int, float)) or isinstance(monthly, bool)
            or not math.isfinite(monthly) or monthly <= 0):
        raise LessonError("wizard needs a positive monthly amount")
    if cadence not in WIZARD_CADENCES:
        raise LessonError(f"wizard cadence must be one of {WIZARD_CADENCES}")
    start, end = _window(spec, tape, "a wizard plan")
    kind = "crypto" if tape.get("kind") == "crypto" else "stock"
    dates = [str(t) for t in tape["ts"][start:end + 1]]
    closes = [float(row[3]) for row in tape["ohlc"][start:end + 1]]
    per = dca.per_period_amount(monthly, cadence)
    if per <= 0:
        raise LessonError(f"wizard: {monthly} a month is less than a cent per {cadence} buy")
    plain = dca.simulate_dca(dates, closes, kind, per, cadence, "plain")
    tilt = dca.simulate_dca(dates, closes, kind, per, cadence, "tilt")
    lump = dca.simulate_lump(dates, closes, kind, plain["invested"])
    rets = {"plain": plain["return_pct"], "tilt": tilt["return_pct"], "lump": lump["return_pct"]}
    # A tie has no winner and no lead: the words are absent, so narrating them stops the build.
    said = {}
    if rets["lump"] != rets["plain"]:
        said.update(winner="all at once" if rets["lump"] > rets["plain"] else "the schedule",
                    lead=abs(rets["lump"] - rets["plain"]))
    if rets["tilt"] != rets["plain"]:
        said.update(tilt_lead=abs(rets["tilt"] - rets["plain"]),
                    tilt_word="ahead of" if rets["tilt"] > rets["plain"] else "behind")
    return SimpleNamespace(
        per_period=per, periods=plain["periods"], invested=plain["invested"],
        plain_avg=plain["avg_cost"], plain_ret=plain["return_pct"], plain_value=plain["final_value"],
        tilt_avg=tilt["avg_cost"], tilt_ret=tilt["return_pct"], tilt_value=tilt["final_value"],
        tilt_invested=tilt["invested"], lump_price=lump["avg_cost"], lump_ret=lump["return_pct"],
        lump_value=lump["final_value"], tilt_helped=rets["tilt"] > rets["plain"],
        lump_won=rets["lump"] > rets["plain"], dca_won=rets["plain"] > rets["lump"],
        # Spoken as "{w.lump_dir} {w.lump_abs:.1f} percent": the direction word comes from the number.
        **{f"{k}_abs": abs(v) for k, v in rets.items()},
        **{f"{k}_dir": "up" if v >= 0 else "down" for k, v in rets.items()},
        cost_pct=sum(backtest.cost_model(kind)) * 100,      # commission + spread, per buy
        **_tilt_lean(tilt["contributions"], tape), **said)


def _whole(value: object, least: int = 1) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= least


def _bar_var(spec: dict, tape: dict) -> SimpleNamespace:
    """One candle, and what a hundred dollars buys at its close."""
    i = _bar(tape, spec.get("bar"), " in a bar var")
    o, h, l, c = (float(v) for v in tape["ohlc"][i])
    return SimpleNamespace(bar=i, open=o, high=h, low=l, close=c, date=_date(tape["ts"][i]), per_100=100 / c)


def _underwater(spec: dict, tape: dict) -> SimpleNamespace:
    """How a plan felt along the way: the days price closed below its running
    average, the worst of them, and the day it came back for good, next to the
    all-at-once buyer who paid the first bar's close. A plan that never dipped
    has no worst_*; one still below at the end has no back_*: a day that never
    happened has no value, so narrating it fails the build.

    worst_gap and lump_worst are positive DEPTHS (percent below). Every *_days
    counts from the plan's FIRST bar ("from your first buy to that day"), not
    from the first dip: days_below is the time actually spent under the line."""
    plan, (start, end) = _dca(spec, tape), _window(spec, tape, "an underwater study")
    buys, entry = {b["bar"]: b["price"] for b in plan.buys}, _close(tape, start)
    n, per_dollar, worst, below, lump_below = 0, 0.0, None, [], []
    for i in range(start, end + 1):
        if i in buys:
            n, per_dollar = n + 1, per_dollar + 1 / buys[i]
        avg, price = n / per_dollar, _close(tape, i)
        gap = (1 - price / avg) * 100
        if gap > 1e-9:                       # a buy day sits ON the line, give or take float dust
            below.append(i)
            if worst is None or gap > worst["worst_gap"]:
                worst = {"worst_bar": i, "worst_gap": gap, "worst_avg": avg, "worst_price": price,
                         "worst_n": n, "worst_date": _date(tape["ts"][i])}
        if price < entry:
            lump_below.append(i)
    out = {"days": end - start + 1, "days_below": len(below), "lump_days_below": len(lump_below),
           "lump_price": entry, **(worst or {})}
    if lump_below:
        out["lump_worst"] = (1 - min(_close(tape, i) for i in lump_below) / entry) * 100
    for prefix, days in (("", below), ("lump_", lump_below)):
        under = set(days)
        first = next((i for i in range(days[0] + 1, end + 1) if i not in under), None) if days else None
        # first_back: the first close back at the line (it may dip again); back: back to stay.
        for name, bar in (("first_back", first), ("back", days[-1] + 1 if days and days[-1] < end else None)):
            if bar is not None:
                out.update({f"{prefix}{name}_bar": bar, f"{prefix}{name}_date": _date(tape["ts"][bar]),
                            f"{prefix}{name}_days": bar - start})
    runs: list[list[int]] = []               # unbroken stretches below the line, as [first bar, last bar]
    for i in below:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    if runs:
        a, b = max(runs, key=lambda r: r[1] - r[0])
        out.update({"longest_days": b - a + 1, "longest_from_bar": a, "longest_to_bar": b,
                    "longest_from_date": _date(tape["ts"][a]), "longest_to_date": _date(tape["ts"][b])})
        if b < end:
            out.update({"longest_after_bar": b + 1, "longest_after_date": _date(tape["ts"][b + 1])})
    return SimpleNamespace(**out)


def _rolling(spec: dict, tape: dict) -> SimpleNamespace:
    """The Wizard run on every window of the WHOLE tape, `step` bars apart, each
    running `span` bars past its first (span 365 on a daily tape = one year):
    how often each plan came out ahead, so a lesson never generalises from one
    lucky year. It always covers the whole tape, so a start or end is refused
    rather than quietly ignored."""
    span, step, n = spec.get("span"), spec.get("step"), len(tape["ts"])
    if not (_whole(span) and _whole(step) and span < n):
        raise LessonError("rolling needs a whole span and step of 1+, and a span shorter than the tape")
    if "start" in spec or "end" in spec:
        raise LessonError("rolling always covers the whole tape: it takes no start or end")
    runs = [_wizard({**spec, "start": s, "end": s + span}, tape) for s in range(0, n - span, step)]
    lump_won, dca_won = sum(w.lump_won for w in runs), sum(w.dca_won for w in runs)
    ends = {"plain_worst": min(w.plain_ret for w in runs), "plain_best": max(w.plain_ret for w in runs),
            "lump_worst": min(w.lump_ret for w in runs), "lump_best": max(w.lump_ret for w in runs)}
    return SimpleNamespace(
        windows=len(runs), lump_won=lump_won, dca_won=dca_won, ties=len(runs) - lump_won - dca_won,
        tilt_helped=sum(w.tilt_helped for w in runs), lump_share=lump_won / len(runs) * 100, **ends,
        **{f"{k}_say": _pct_say(v) for k, v in ends.items()})


def _pct_say(value: float) -> str:
    """A percentage spoken whole: a voice can drop a minus sign, it can't drop the
    word "loss". Rounded FIRST, so the word always agrees with the number said."""
    whole = round(value)
    return "no change" if whole == 0 else f"a {'gain' if whole > 0 else 'loss'} of {abs(whole)} percent"


def _shift(spec: dict, tape: dict) -> SimpleNamespace:
    """The same plan started on each of `days` neighbouring bars: how much the
    choice of buying day moves the average, next to how far price itself ranged."""
    start, end = _window(spec, tape, "a shift study")
    days = spec.get("days")
    if not _whole(days) or start + days - 1 > end:
        raise LessonError("shift needs days >= 1 that fit inside the window")
    avgs = [_dca({**spec, "start": start + k, "end": end}, tape).avg for k in range(days)]
    closes = [_close(tape, i) for i in range(start, end + 1)]
    return SimpleNamespace(days=days, lo_avg=min(avgs), hi_avg=max(avgs),
                           spread_pct=(max(avgs) / min(avgs) - 1) * 100,
                           price_lo=min(closes), price_hi=max(closes),
                           price_spread_pct=(max(closes) / min(closes) - 1) * 100)


VAR_FNS = {"dca": _dca, "breakeven": _breakeven, "dca_at": _dca_at, "wizard": _wizard,
           "bar": _bar_var, "underwater": _underwater, "rolling": _rolling, "shift": _shift}


def _date(ts: int) -> str:
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    return f"{d:%B} {d.day}, {d.year}"


def compute_vars(specs: dict, tape: dict) -> dict:
    out = {"tape": SimpleNamespace(symbol=tape.get("symbol", ""), bars=len(tape["ts"]),
                                   first_close=_close(tape, 0), last_close=_close(tape, -1),
                                   first_date=_date(tape["ts"][0]), last_date=_date(tape["ts"][-1]))}
    for name, spec in (specs or {}).items():
        fn = VAR_FNS.get(spec.get("fn") if isinstance(spec, dict) else None)
        if fn is None:
            raise LessonError(f"var {name}: unknown fn")
        out[name] = fn(spec, tape)
    return out


def _lookup(vars_: dict, ref: object) -> object:
    try:
        head, attr = str(ref).split(".", 1)
        if attr.startswith("_"):
            raise AttributeError(attr)
        return getattr(vars_[head], attr)
    except (KeyError, ValueError, AttributeError):
        raise LessonError(f"unknown var {ref}") from None


def _var(vars_: dict, ref: object) -> float:
    value = _lookup(vars_, ref)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise LessonError(f"var {ref} is not a number")
    return float(value)


def _bar_ref(vars_: dict, bar: object) -> object:
    """An op's bar: a number, or the name of a computed bar ("u.worst_bar") so a
    drawing sits on exactly the candle the narration names. Only a var NAMED as a
    bar will do: u.days is a whole number too, and a typo must not seek "bar 5"."""
    if not isinstance(bar, str):
        return bar
    value = _lookup(vars_, bar)
    named_bar = bar.rsplit(".", 1)[-1] == "bar" or bar.endswith("_bar")
    if not named_bar or not isinstance(value, int) or isinstance(value, bool):
        raise LessonError(f"var {bar} is not a bar number")
    return value


# ------------------------------------------------------------------ text
class _SafeFormatter(string.Formatter):
    """str.format without the escape hatches: no _private / dunder fields, no indexing."""

    def get_field(self, field_name, args, kwargs):
        if "[" in field_name or any(part.startswith("_") for part in field_name.split(".")):
            raise LessonError(f"placeholder {{{field_name}}} is not allowed")
        return super().get_field(field_name, args, kwargs)


def lint(text: str, where: str) -> str:
    plain = text.translate(APOSTROPHES)
    for pattern, what in HONESTY:
        if pattern.search(plain):
            raise LessonError(f"honesty lint: {what} in {where} {text!r}")
    return text


def _label(value: object, where: str) -> str:
    text = str(value if value is not None else "")
    if len(text) > MAX_TEXT:
        raise LessonError(f"{where} is longer than {MAX_TEXT} characters")
    return lint(text, where)


def _say(text: object, vars_: dict) -> str:
    if not isinstance(text, str) or not text.strip():
        raise LessonError("every step needs something to say")
    try:
        said = _SafeFormatter().vformat(text, (), vars_)
    except (KeyError, AttributeError, IndexError, ValueError, TypeError) as exc:
        raise LessonError(f"narration placeholder has no value: {exc}") from None
    return lint(said, "narration")


def speech(text: str) -> str:
    for pattern, spoken in SPEECH_FIXES:
        text = pattern.sub(spoken, text)
    return text


# ------------------------------------------------------------------ ops
def _point(p: object, tape: dict, vars_: dict, where: str) -> dict:
    if not isinstance(p, dict) or "bar" not in p:
        raise LessonError(f"{where} needs a bar")
    i = _bar(tape, _bar_ref(vars_, p["bar"]), f" ({where})")
    if "price" in p:
        if not isinstance(p["price"], (int, float)) or isinstance(p["price"], bool):
            raise LessonError(f"{where}: price must be a number")
        price = float(p["price"])
    elif "var" in p:
        price = _var(vars_, p["var"])
    else:
        at = p.get("at", "close")
        if at not in PRICE_AT:
            raise LessonError(f"{where}: at must be one of {sorted(PRICE_AT)}")
        price = float(tape["ohlc"][i][PRICE_AT[at]])
    return {"bar": i, "ts": tape["ts"][i], "price": price}


class _Ctx:
    """Validation state carried across a lesson's steps."""

    def __init__(self, tape: dict, vars_: dict):
        self.tape, self.vars = tape, vars_
        self.frame = (0, len(tape["ts"]) - 1)
        self.end = len(tape["ts"]) - 1     # the chart starts on the last bar
        self.drawn_buys: set = set()       # (var, bar) already marked since the last clear

    def step_cursor(self, ops: list) -> None:
        """Move to where this step's seeks and plays leave the cursor, and to the
        frame it ends on. The frame is the bars on screen (the player shows from
        its first bar to its last), so the cursor must end inside it."""
        for op in ops:
            if op.get("op") == "seek":
                self.end = _bar(self.tape, _bar_ref(self.vars, op.get("bar")), " (seek)")
            elif op.get("op") == "play":
                to = _bar(self.tape, _bar_ref(self.vars, op.get("to")), " (play)")
                if to < self.end:
                    raise LessonError(f"play goes backwards (bar {to} < cursor {self.end}); use seek")
                self.end = to
            elif op.get("op") == "frame":
                a, b = (_bar(self.tape, _bar_ref(self.vars, op.get(k)), " (frame)") for k in ("from", "to"))
                if a >= b:
                    raise LessonError("a frame must run forwards (from < to)")
                self.frame = (a, b)
        if not self.frame[0] <= self.end <= self.frame[1]:
            raise LessonError(f"the cursor (bar {self.end}) is outside the frame "
                              f"(bars {self.frame[0]}..{self.frame[1]}): it would play off screen")

    def visible(self, bar: int, what: str) -> None:
        if bar > self.end:
            raise LessonError(f"{what} on bar {bar} is not revealed yet (cursor ends at bar {self.end})")
        if not self.frame[0] <= bar <= self.frame[1]:
            raise LessonError(f"{what} on bar {bar} is outside the frame "
                              f"(bars {self.frame[0]}..{self.frame[1]}): it would sit off screen")

    def on_chart(self, price: float, what: str) -> None:
        bars = range(self.frame[0], self.frame[1] + 1)
        lo = min(float(self.tape["ohlc"][i][2]) for i in bars)
        hi = max(float(self.tape["ohlc"][i][1]) for i in bars)
        if not lo * (1 - LEVEL_MARGIN) <= price <= hi * (1 + LEVEL_MARGIN):
            raise LessonError(f"{what} at {price} is off the chart (framed bars span {lo}..{hi})")


def _drawn_point(ctx: _Ctx, p: dict, what: str) -> dict:
    ctx.visible(p["bar"], what)
    ctx.on_chart(p["price"], what)
    return {"ts": p["ts"], "price": p["price"]}


def _op_drawing(op: dict, ctx: _Ctx) -> list:
    kind, tape = op.get("op"), ctx.tape
    if kind == "mark":
        p = _drawn_point(ctx, _point(op, tape, ctx.vars, "mark"), "a mark")
        return [{"op": "mark", **p, "dir": _label(op.get("dir", "mark"), "a mark label")}]
    if kind == "line":
        a = _drawn_point(ctx, _point(op.get("a"), tape, ctx.vars, "line a"), "a line")
        b = _drawn_point(ctx, _point(op.get("b"), tape, ctx.vars, "line b"), "a line")
        return [{"op": "line", "a": a, "b": b}]
    if kind == "level":
        price = _var(ctx.vars, op["var"]) if "var" in op else op.get("price")
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            raise LessonError("a level needs a price or var")
        ctx.on_chart(float(price), "a level")
        return [{"op": "level", "price": round(float(price), 4), "title": _label(op.get("title"), "a level title")}]
    if kind == "buys":
        name = op.get("var")
        plan = ctx.vars.get(name)
        if not isinstance(plan, SimpleNamespace) or not hasattr(plan, "buys"):
            raise LessonError(f"buys needs a dca var, got {name!r}")
        fresh = [b for b in plan.buys if b["bar"] <= ctx.end and (name, b["bar"]) not in ctx.drawn_buys]
        ctx.drawn_buys.update((name, b["bar"]) for b in fresh)
        return [{"op": "mark", "ts": b["ts"], "price": b["price"], "dir": "buy"} for b in fresh]
    raise LessonError(f"unknown op {kind!r}")


def _op(op: dict, ctx: _Ctx) -> list:
    kind, tape = op.get("op"), ctx.tape

    def bar(key: str) -> int:
        return _bar(tape, _bar_ref(ctx.vars, op.get(key)), f" ({kind})")

    if kind == "frame":                   # validated, and ctx.frame set, by step_cursor
        return [{"op": "frame", "from_ts": tape["ts"][bar("from")], "to_ts": tape["ts"][bar("to")]}]
    if kind == "seek":
        return [{"op": "seek", "ts": tape["ts"][bar("bar")]}]
    if kind == "play":
        return [{"op": "play", "to_ts": tape["ts"][bar("to")]}]
    if kind == "clear":
        ctx.drawn_buys.clear()
        return [{"op": "clear"}]
    if kind == "spot":
        if op.get("tool") not in TOOLS:
            raise LessonError(f"spot: unknown tool {op.get('tool')!r} (one of {sorted(TOOLS)})")
        return [{"op": "spot", "tool": op["tool"], "label": _label(op.get("label", ""), "a spotlight label")}]
    return _op_drawing(op, ctx)


# ------------------------------------------------------------------ lesson
def _check_header(src: object) -> None:
    if not isinstance(src, dict):
        raise LessonError("a lesson must be an object")
    if not (isinstance(src.get("id"), str) and LESSON_ID_RE.fullmatch(src["id"])):
        raise LessonError(f"bad lesson id {src.get('id')!r}")
    if not (isinstance(src.get("class"), str) and src["id"].startswith(src["class"] + "-")):
        raise LessonError("a lesson id must start with its class id")
    if not isinstance(src.get("title"), str) or not src["title"].strip():
        raise LessonError("a lesson needs a title")
    if not isinstance(src.get("free"), bool):
        raise LessonError("free must be true or false")
    if not isinstance(src.get("steps"), list) or not src["steps"]:
        raise LessonError("a lesson needs steps")


def compile_lesson(src: dict, tape: dict) -> dict:
    _check_header(src)
    check_tape(tape)
    vars_ = compute_vars(src.get("vars") or {}, tape)
    ctx, steps = _Ctx(tape, vars_), []
    for n, step in enumerate(src["steps"]):
        if not isinstance(step, dict) or step.get("who") not in WHO:
            raise LessonError(f"step {n}: who must be T or Q")
        ops = step.get("do") or []
        if not isinstance(ops, list) or not all(isinstance(o, dict) for o in ops):
            raise LessonError(f"step {n}: do must be a list of ops")
        try:
            ctx.step_cursor(ops)
            compiled = [c for op in ops for c in _op(op, ctx)]
            say = _say(step.get("say"), vars_)
        except LessonError as exc:
            raise LessonError(f"step {n}: {exc}") from None
        steps.append({"who": step["who"], "say": say, "do": compiled})
    keep = ("symbol", "kind", "tf", "ts", "ohlc", "volume", "gmtoffset", "regular")
    return {"id": src["id"], "class": src["class"], "title": _label(src["title"], "the lesson title"),
            "free": src["free"], "practice": src.get("practice") or {},
            "tape": {k: tape[k] for k in keep if k in tape}, "steps": steps}


def state_at(lesson: dict, i: int) -> dict:
    """The chart after steps 0..i, folded from scratch so skip/back are exact.
    Starts on the tape's last bar (as the compiler does); i < 0 is the start.
    Mirrors lessonStateAt in static/lesson-engine.js."""
    st = {"cursor_ts": lesson["tape"]["ts"][-1], "frame": None, "marks": [], "lines": [], "levels": []}
    for step in lesson["steps"][: max(i + 1, 0)]:
        for op in step["do"]:
            k = op["op"]
            if k in ("seek", "play"):
                st["cursor_ts"] = op["ts"] if k == "seek" else op["to_ts"]
            elif k == "frame":
                st["frame"] = {"from_ts": op["from_ts"], "to_ts": op["to_ts"]}
            elif k == "mark":
                st["marks"].append({"ts": op["ts"], "price": op["price"], "dir": op["dir"]})
            elif k == "line":
                st["lines"].append({"a": op["a"], "b": op["b"]})
            elif k == "level":
                st["levels"].append({"price": op["price"], "title": op["title"]})
            elif k == "clear":
                st["marks"], st["lines"], st["levels"] = [], [], []
    return st


# ------------------------------------------------------------------ build
def audio_name(who: str, text: str, voice_key: str = VOICE_VERSION) -> str:
    return hashlib.sha256(f"{voice_key}|{who}|{text}".encode()).hexdigest()[:16] + ".mp3"


def compile_all(sources: list, tapes: dict, class_meta: dict) -> list:
    """Phase 1 of a build: compile and cross-check EVERYTHING before touching disk."""
    if not sources:
        raise LessonError("no lessons to build (refusing: an empty build would delete every narration file)")
    built, seen = [], set()
    for src in sorted(sources, key=lambda s: str(s.get("id", "")) if isinstance(s, dict) else ""):
        tape_id = src.get("tape") if isinstance(src, dict) else None
        if not isinstance(tape_id, str) or tape_id not in tapes:
            raise LessonError(f"{src.get('id') if isinstance(src, dict) else src}: tape {tape_id!r} not found")
        lesson = compile_lesson(src, tapes[tape_id])
        if lesson["id"] in seen:
            raise LessonError(f"duplicate lesson id {lesson['id']}")
        if lesson["class"] not in class_meta:
            raise LessonError(f"{lesson['id']}: class {lesson['class']!r} is not in classes.json")
        seen.add(lesson["id"])
        built.append(lesson)
    return built


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _bake_all(built: list, out: Path, bake: Bake, voice_key: str) -> set:
    dur_file = out / "audio_durations.json"
    durations = json.loads(dur_file.read_text(encoding="utf-8")) if dur_file.is_file() else {}
    for lesson in built:
        for step in lesson["steps"]:
            spoken = speech(step["say"])
            name = audio_name(step["who"], spoken, voice_key)
            path = out / "audio" / name
            if not (path.is_file() and name in durations):
                data, ms = bake(spoken, step["who"])
                path.write_bytes(data)
                durations[name] = int(ms)
                _write_atomic(dur_file, json.dumps(durations, indent=1, sort_keys=True))  # a crash keeps paid-for takes
            step["audio"], step["durMs"] = name, durations[name]
    keep = {s["audio"] for lesson in built for s in lesson["steps"]}
    _write_atomic(dur_file, json.dumps({k: v for k, v in durations.items() if k in keep}, indent=1, sort_keys=True))
    return keep


def lesson_seconds(lesson: dict) -> float:
    """How long a built lesson plays: its narration plus the player's breath between steps."""
    steps = lesson["steps"]
    return (sum(s["durMs"] for s in steps) + STEP_GAP_MS * (len(steps) - 1)) / 1000


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _check_lengths(built: list, floor_s: float) -> None:
    sold = {lsn["class"] for lsn in built if not lsn["free"]}
    short = [lsn for lsn in built if lsn["class"] in sold and lesson_seconds(lsn) < floor_s]
    if short:
        raise LessonError(", ".join(f"{lsn['id']} runs {_clock(lesson_seconds(lsn))}" for lsn in short)
                          + f": every lesson in a class with paid lessons must run at least {_clock(floor_s)}")


def _catalog(built: list, class_meta: dict) -> dict:
    return {"classes": [
        {"id": cid, "title": meta.get("title", cid) if isinstance(meta, dict) else cid,
         "tagline": meta.get("tagline", "") if isinstance(meta, dict) else "",
         "lessons": [{"id": lsn["id"], "title": lsn["title"], "free": lsn["free"], "file": f"{lsn['id']}.json",
                      "seconds": round(lesson_seconds(lsn)),
                      "audio": [s["audio"] for s in lsn["steps"]]} for lsn in built if lsn["class"] == cid]}
        for cid, meta in class_meta.items()]}


def build_all(sources: list, tapes: dict, class_meta: dict, out, bake: Bake,
              voice_key: str = VOICE_VERSION) -> list:
    """Compile EVERY lesson (nothing is written if any fails), bake new narration,
    refuse a class for sale whose lessons are too short, then write lesson files,
    the catalogue LAST, and prune unused audio."""
    built = compile_all(sources, tapes, class_meta)
    out = Path(out)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    keep = _bake_all(built, out, bake, voice_key)
    _check_lengths(built, MIN_PAID_CLASS_LESSON_S)     # after the bake: only then is the length known
    for lesson in built:
        _write_atomic(out / f"{lesson['id']}.json", json.dumps(lesson))
    _write_atomic(out / "catalog.json", json.dumps(_catalog(built, class_meta), indent=1))
    for f in (out / "audio").glob("*.mp3"):     # old narration takes, so the repo doesn't grow forever
        if f.name not in keep:
            f.unlink()
    return built
