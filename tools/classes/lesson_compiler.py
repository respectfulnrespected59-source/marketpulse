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
  frame {from, to}           show bars from..to
  seek  {bar}                replay cursor to a bar
  play  {to}                 reveal bars up to `to` while the step plays
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
                   "dca_tab"})
VOICE_VERSION = "kokoro-v1"           # default voice key; build.py passes the real one

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
                (re.compile(r"S&P 500"), "S and P five hundred"))

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
def _dca(spec: dict, tape: dict) -> SimpleNamespace:
    every, start = spec.get("every"), _bar(tape, spec.get("start", 0), " in a dca plan")
    if not isinstance(every, int) or isinstance(every, bool) or every < 1:
        raise LessonError("a dca plan needs every >= 1")
    buys = [{"bar": i, "ts": tape["ts"][i], "price": _close(tape, i)}
            for i in range(start, len(tape["ts"]), every)]
    prices = [b["price"] for b in buys]
    # Same dollars each time: average cost = total dollars / total coins (harmonic mean).
    return SimpleNamespace(buys=buys, n=len(buys), avg=len(prices) / sum(1 / p for p in prices),
                           mean=sum(prices) / len(prices))


def _breakeven(spec: dict, _tape: dict) -> SimpleNamespace:
    right, strike, premium = spec.get("right"), spec.get("strike"), spec.get("premium")
    if right not in ("put", "call") or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                               for v in (strike, premium)):
        raise LessonError("breakeven needs right put|call, strike and premium")
    value = strike - premium if right == "put" else strike + premium
    return SimpleNamespace(value=round(value, 4), strike=strike, premium=premium, right=right)


def _dca_at(spec: dict, tape: dict) -> SimpleNamespace:
    """The plan as it stood on `bar`: buys so far, their average cost, and how far
    price sat from it (negative = below your line)."""
    bar = _bar(tape, spec.get("bar"), " in dca_at")
    plan = _dca({"every": spec.get("every"), "start": spec.get("start", 0)}, tape)
    buys = [b["price"] for b in plan.buys if b["bar"] <= bar]
    if not buys:
        raise LessonError(f"dca_at: no buys yet at bar {bar}")
    avg = len(buys) / sum(1 / p for p in buys)
    price = _close(tape, bar)
    gap = (price / avg - 1) * 100
    return SimpleNamespace(n=len(buys), avg=avg, price=price, gap_pct=gap, gap_abs=abs(gap),
                           date=_date(tape["ts"][bar]))


WIZARD_CADENCES = ("weekly", "biweekly", "monthly")


def _wizard(spec: dict, tape: dict) -> SimpleNamespace:
    """What the app's DCA Wizard would show for this tape: plain DCA, signal-tilt
    DCA and lump sum, through dca.py itself (same cost model), so a lesson never
    quotes a number the student can't reproduce in the app."""
    import sys
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    import dca
    monthly, cadence = spec.get("monthly"), spec.get("cadence", "monthly")
    if not isinstance(monthly, (int, float)) or isinstance(monthly, bool) or monthly <= 0:
        raise LessonError("wizard needs a positive monthly amount")
    if cadence not in WIZARD_CADENCES:
        raise LessonError(f"wizard cadence must be one of {WIZARD_CADENCES}")
    kind = "crypto" if tape.get("kind") == "crypto" else "stock"
    dates = [str(t) for t in tape["ts"]]
    closes = [float(row[3]) for row in tape["ohlc"]]
    per = dca.per_period_amount(monthly, cadence)
    plain = dca.simulate_dca(dates, closes, kind, per, cadence, "plain")
    tilt = dca.simulate_dca(dates, closes, kind, per, cadence, "tilt")
    lump = dca.simulate_lump(dates, closes, kind, plain["invested"])
    return SimpleNamespace(
        per_period=per, periods=plain["periods"], invested=plain["invested"],
        plain_avg=plain["avg_cost"], plain_ret=plain["return_pct"], plain_value=plain["final_value"],
        tilt_avg=tilt["avg_cost"], tilt_ret=tilt["return_pct"], tilt_value=tilt["final_value"],
        tilt_invested=tilt["invested"], lump_price=lump["avg_cost"], lump_ret=lump["return_pct"],
        lump_value=lump["final_value"], tilt_helped=tilt["return_pct"] > plain["return_pct"],
        lump_won=lump["return_pct"] > plain["return_pct"])


VAR_FNS = {"dca": _dca, "breakeven": _breakeven, "dca_at": _dca_at, "wizard": _wizard}


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


def _var(vars_: dict, ref: object) -> float:
    try:
        head, attr = str(ref).split(".", 1)
        if attr.startswith("_"):
            raise AttributeError(attr)
        value = getattr(vars_[head], attr)
    except (KeyError, ValueError, AttributeError):
        raise LessonError(f"unknown var {ref}") from None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise LessonError(f"var {ref} is not a number")
    return float(value)


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
    i = _bar(tape, p["bar"], f" ({where})")
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
        """Move to where this step's seeks and plays leave the cursor."""
        for op in ops:
            if op.get("op") == "seek":
                self.end = _bar(self.tape, op.get("bar"), " (seek)")
            elif op.get("op") == "play":
                to = _bar(self.tape, op.get("to"), " (play)")
                if to < self.end:
                    raise LessonError(f"play goes backwards (bar {to} < cursor {self.end}); use seek")
                self.end = to

    def visible(self, bar: int, what: str) -> None:
        if bar > self.end:
            raise LessonError(f"{what} on bar {bar} is not revealed yet (cursor ends at bar {self.end})")

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
    if kind == "frame":
        a, b = _bar(tape, op.get("from"), " (frame)"), _bar(tape, op.get("to"), " (frame)")
        if a >= b:
            raise LessonError("a frame must run forwards (from < to)")
        ctx.frame = (a, b)
        return [{"op": "frame", "from_ts": tape["ts"][a], "to_ts": tape["ts"][b]}]
    if kind == "seek":
        return [{"op": "seek", "ts": tape["ts"][_bar(tape, op.get("bar"), " (seek)")]}]
    if kind == "play":
        return [{"op": "play", "to_ts": tape["ts"][_bar(tape, op.get("to"), " (play)")]}]
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


def _catalog(built: list, class_meta: dict) -> dict:
    return {"classes": [
        {"id": cid, "title": meta.get("title", cid) if isinstance(meta, dict) else cid,
         "tagline": meta.get("tagline", "") if isinstance(meta, dict) else "",
         "lessons": [{"id": lsn["id"], "title": lsn["title"], "free": lsn["free"], "file": f"{lsn['id']}.json",
                      "audio": [s["audio"] for s in lsn["steps"]]} for lsn in built if lsn["class"] == cid]}
        for cid, meta in class_meta.items()]}


def build_all(sources: list, tapes: dict, class_meta: dict, out, bake: Bake,
              voice_key: str = VOICE_VERSION) -> list:
    """Compile EVERY lesson (nothing is written if any fails), bake new narration,
    then write lesson files, the catalogue LAST, and prune unused audio."""
    built = compile_all(sources, tapes, class_meta)
    out = Path(out)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    keep = _bake_all(built, out, bake, voice_key)
    for lesson in built:
        _write_atomic(out / f"{lesson['id']}.json", json.dumps(lesson))
    _write_atomic(out / "catalog.json", json.dumps(_catalog(built, class_meta), indent=1))
    for f in (out / "audio").glob("*.mp3"):     # old narration takes, so the repo doesn't grow forever
        if f.name not in keep:
            f.unlink()
    return built
