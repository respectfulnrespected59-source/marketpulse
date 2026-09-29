"""Engine v1 at its native swing horizons on micro index futures: a pre-registered study (2026-09-29).

PRE-REGISTRATION (committed and fingerprinted BEFORE any data was fetched).

Why this study exists: both scalper studies failed (prereg 34dd0da crypto,
97ae9bd FX + micro futures). Where cost was tiny (MES/MNQ) there was no gross
5-minute edge. The engine was never built for 5 minutes; this asks the
question at the horizons MarketPulse actually shows users: hourly and daily.
Micro futures keep the cost small against a 1h/1D move (~0.02 R, measured in
the 09-28 diagnosis).

Nothing is tuned. The rule is the product's own v1 rule, unchanged:
  L   flat + STRONG BUY on a closed bar  -> long 1 contract at the next open;
      long + SELL / STRONG SELL           -> exit at the next open.
  LS  L plus its mirror (futures can be sold short):
      flat + STRONG SELL                  -> short 1 contract at the next open;
      short + BUY / STRONG BUY            -> cover at the next open.
      No same-bar flip: a new entry needs a flat book at the signal close.
  A position still open at the data end is closed at the last close.

Labels are indicators.score_signals exactly as the app computes them:
  1h  htf_factor=24 (app._signal_from_closes), on a trailing window of 1,400
      hourly closes (about the app's 3-month 1h chart), from bar 504 on
      (the first bar where the daily higher-timeframe check can fire).
  1D  htf_factor=5, full history (backtest._compute_labels), from bar 250.
Each label at bar i sees closes[..i] only.

Data: Yahoo ES=F / NQ=F (the same index price as MES / MNQ, with a longer
history than the micros, which only exist since 2019). 1h = interval 60m,
range 730d; 1D = interval 1d, range 10y. An unfinished last bar is dropped.
Fetched once and cached with a UTC stamp (the cache IS the dataset).
Known limit: Yahoo's continuous futures are NOT back-adjusted, so a quarterly
roll shows as a price jump. It hits buy-and-hold and the rules alike, and is
reported, not corrected.

Costs, per round trip on one micro contract ($2.00 commission + fees + 1 tick
slippage per side): MES $5/pt, 0.25 tick = $4.50 = 0.90 pt; MNQ $2/pt =
$3.00 = 1.50 pt. Results are in dollars per one micro contract.

OOS = trades ENTERED in the newest 40% of the common scored span.

Four candidates (1h-L, 1h-LS, 1D-L, 1D-LS). A candidate EARNS a paper period
only if ALL hold out-of-sample:
  G1  net $ > 0 on BOTH MES and MNQ
  G2  pooled profit factor >= 1.30
  G3  pooled trades >= 20
  G4  pooled max drawdown ($) <= pooled net $ (recovery factor >= 1)
  G5  the in-sample window is also net positive (pooled $)
  G6  $ earned per bar in the market > $ per bar of simply holding one
      contract long through the OOS window (the signal must beat being long)
If more than one passes, the highest OOS profit factor goes to paper. If none
passes, no paper and no live, and these rules are not re-tuned on this data.

Run:  python tools/futures_swing_study.py            (cached data)
      python tools/futures_swing_study.py --refresh
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import indicators  # noqa: E402

PREREG = {
    "universe": {
        "MES": {"series": "ES=F", "usd_per_pt": 5.0, "rt_cost_pts": 0.90},
        "MNQ": {"series": "NQ=F", "usd_per_pt": 2.0, "rt_cost_pts": 1.50},
    },
    "timeframes": {
        "1h": {"interval": "60m", "range": "730d", "bar_s": 3600, "htf_factor": 24, "window": 1400, "warmup": 504},
        "1D": {"interval": "1d", "range": "10y", "bar_s": 86400, "htf_factor": 5, "window": None, "warmup": 250},
    },
    "rules": {
        "L": "flat+STRONG BUY -> long next open; long+SELL/STRONG SELL -> exit next open",
        "LS": "L + mirror: flat+STRONG SELL -> short next open; short+BUY/STRONG BUY -> cover next open; no same-bar flip",
    },
    "source": "Yahoo chart API ES=F/NQ=F, 1h=60m/730d, 1D=1d/10y, unfinished bar dropped, cached once",
    "oos_share": 0.40,
    "thresholds": {"profit_factor": 1.30, "min_trades": 20},
    "gates": {
        "G1": "net $ > 0 on BOTH MES and MNQ (OOS)",
        "G2": "pooled profit factor >= 1.30 (OOS)",
        "G3": "pooled trades >= 20 (OOS)",
        "G4": "pooled max drawdown $ <= pooled net $ (OOS)",
        "G5": "in-sample pooled net $ > 0",
        "G6": "$ per bar in market > $ per bar of holding one contract long (OOS, pooled)",
    },
}

LONG_ENTRY, SHORT_ENTRY = "STRONG BUY", "STRONG SELL"
LONG_EXITS, SHORT_EXITS = ("SELL", "STRONG SELL"), ("BUY", "STRONG BUY")

DATA = os.path.join(ROOT, "reports", "futures_swing_study", "data")
OUT = os.path.join(ROOT, "reports", "futures_swing_study")


def prereg_fingerprint() -> str:
    return hashlib.sha256(json.dumps(PREREG, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- data
def clean_bars(raw: dict, now_s: float, bar_s: int) -> list[list[float]]:
    """Yahoo chart result -> [t, low, high, open, close, volume], dropping gaps and the unfinished bar."""
    q = raw["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(raw.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or t + bar_s > now_s:
            continue
        out.append([float(t), float(l), float(h), float(o), float(c), float(q["volume"][i] or 0)])
    return out


def fetch(sym: str, tf: str, refresh: bool = False) -> dict:
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"{sym}_{tf}.json")
    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    series = PREREG["universe"][sym]["series"]
    spec = PREREG["timeframes"][tf]
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{series}"
           f"?range={spec['range']}&interval={spec['interval']}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.load(resp)["chart"]["result"][0]
    now = dt.datetime.now(dt.timezone.utc)
    bars = clean_bars(raw, now.timestamp(), spec["bar_s"])
    if len(bars) < spec["warmup"] + 200:
        raise RuntimeError(f"{sym} {tf}: only {len(bars)} bars from Yahoo {series}")
    d = {"symbol": sym, "series": series, "tf": tf, "fetched_utc": now.isoformat(timespec="seconds"), "bars": bars}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return d


# ---------------------------------------------------------------- the engine
def labels_for(closes: list[float], spec: dict) -> list[str | None]:
    """The app's label at every bar from `warmup` on, each computed on closes[..i] only."""
    out: list[str | None] = [None] * len(closes)
    for i in range(spec["warmup"], len(closes)):
        lo = 0 if spec["window"] is None else max(0, i + 1 - spec["window"])
        out[i] = indicators.score_signals(closes[lo:i + 1], htf_factor=spec["htf_factor"])["label"]
    return out


# ---------------------------------------------------------------- the simulator
def _wants(pos: int, label: str | None, rule: str) -> int | None:
    """What the closed bar asks for: 0 = go flat, +1/-1 = open, None = nothing."""
    if pos == 1:
        return 0 if label in LONG_EXITS else None
    if pos == -1:
        return 0 if label in SHORT_EXITS else None
    if label == LONG_ENTRY:
        return 1
    if rule == "LS" and label == SHORT_ENTRY:
        return -1
    return None


def simulate(bars: list[list[float]], labels: list[str | None], rule: str,
             usd_per_pt: float, rt_cost_pts: float) -> list[dict]:
    """One contract at a time; signal on close i, fill at open i+1."""
    trades: list[dict] = []
    pos, entry, e, pending = 0, 0.0, 0, None
    n = len(bars)

    def close_at(px: float, j_exit: int, reason: str, bars_held: int) -> None:
        pts = pos * (px - entry) - rt_cost_pts
        trades.append({"t_entry": bars[e][0], "dir": pos, "entry": entry, "exit": px, "pnl_pts": pts,
                       "usd": pts * usd_per_pt, "bars": bars_held, "reason": reason, "i_exit": j_exit})

    for i in range(n):
        o = bars[i][3]
        if pending == 0:
            close_at(o, i, "signal", i - e)
            pos = 0
        elif pending in (1, -1):
            pos, entry, e = pending, o, i
        pending = _wants(pos, labels[i], rule) if i + 1 < n else None
    if pos:
        close_at(bars[-1][4], n - 1, "end", n - e)
    return trades


# ---------------------------------------------------------------- scoring
def stats(trades: list[dict]) -> dict:
    us = [x["usd"] for x in trades]
    wins = [u for u in us if u > 0]
    losses = [-u for u in us if u <= 0]
    eq = peak = dd = 0.0
    for u in us:
        eq += u
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(us), "net_usd": round(sum(us), 2),
            "win_rate": round(len(wins) / len(us), 3) if us else None,
            "profit_factor": round(sum(wins) / sum(losses), 3) if losses and sum(losses) > 0 else None,
            "max_dd_usd": round(dd, 2), "bars_in_market": sum(x["bars"] for x in trades),
            "longs": sum(1 for x in trades if x["dir"] == 1), "shorts": sum(1 for x in trades if x["dir"] == -1)}


def hold(bars: list[list[float]], usd_per_pt: float, rt_cost_pts: float) -> dict:
    """One contract long from the first open to the last close of the window."""
    if not bars:
        return {"usd": 0.0, "bars": 0}
    return {"usd": round((bars[-1][4] - bars[0][3] - rt_cost_pts) * usd_per_pt, 2), "bars": len(bars)}


def verdict(per: dict, pooled_is: dict, pooled_oos: dict, hold_oos: dict) -> dict:
    th = PREREG["thresholds"]
    pf = pooled_oos["profit_factor"] or 0.0
    rule_pb = pooled_oos["net_usd"] / pooled_oos["bars_in_market"] if pooled_oos["bars_in_market"] else None
    hold_pb = hold_oos["usd"] / hold_oos["bars"] if hold_oos["bars"] else 0.0
    g = {"G1": {"net_usd": {s: v["oos"]["net_usd"] for s, v in per.items()},
                "pass": all(v["oos"]["net_usd"] > 0 for v in per.values())},
         "G2": {"profit_factor": pooled_oos["profit_factor"], "pass": pf >= th["profit_factor"]},
         "G3": {"trades": pooled_oos["trades"], "pass": pooled_oos["trades"] >= th["min_trades"]},
         "G4": {"max_dd_usd": pooled_oos["max_dd_usd"], "net_usd": pooled_oos["net_usd"],
                "pass": pooled_oos["net_usd"] > 0 and pooled_oos["max_dd_usd"] <= pooled_oos["net_usd"]},
         "G5": {"is_net_usd": pooled_is["net_usd"], "pass": pooled_is["net_usd"] > 0},
         "G6": {"usd_per_bar_rule": None if rule_pb is None else round(rule_pb, 3),
                "usd_per_bar_hold": round(hold_pb, 3), "pass": rule_pb is not None and rule_pb > hold_pb}}
    g["ALL_PASS"] = all(g[k]["pass"] for k in PREREG["gates"])
    return g


def run_tf(tf: str, data: dict) -> dict:
    spec = PREREG["timeframes"][tf]
    lo = max(d["bars"][spec["warmup"]][0] for d in data.values())
    hi = min(d["bars"][-1][0] for d in data.values())
    cut = lo + (hi - lo) * (1 - PREREG["oos_share"])
    labels = {s: labels_for([b[4] for b in d["bars"]], spec) for s, d in data.items()}
    res = {"span_utc": [lo, hi, cut], "rules": {}}
    for rule in PREREG["rules"]:
        per, all_is, all_oos = {}, [], []
        h_usd = h_bars = 0.0
        for s, d in data.items():
            u = PREREG["universe"][s]
            keep = [k for k, b in enumerate(d["bars"]) if b[0] <= hi]
            bars = [d["bars"][k] for k in keep]
            labs = [labels[s][k] if d["bars"][k][0] >= lo else None for k in keep]
            tr = simulate(bars, labs, rule, u["usd_per_pt"], u["rt_cost_pts"])
            is_t = [x for x in tr if x["t_entry"] < cut]
            oos_t = [x for x in tr if x["t_entry"] >= cut]
            h = hold([b for b in bars if b[0] >= cut], u["usd_per_pt"], u["rt_cost_pts"])
            per[s] = {"is": stats(is_t), "oos": stats(oos_t), "hold_oos": h,
                      "exits": {k: sum(1 for x in tr if x["reason"] == k) for k in ("signal", "end")}}
            all_is += is_t
            all_oos += oos_t
            h_usd += h["usd"]
            h_bars += h["bars"]
        all_is.sort(key=lambda x: x["t_entry"])
        all_oos.sort(key=lambda x: x["t_entry"])
        pi, po = stats(all_is), stats(all_oos)
        hold_oos = {"usd": round(h_usd, 2), "bars": int(h_bars)}
        res["rules"][rule] = {"per": per, "pooled_is": pi, "pooled_oos": po, "hold_oos": hold_oos,
                              "verdict": verdict(per, pi, po, hold_oos)}
    return res


def run(refresh: bool) -> dict:
    fp = prereg_fingerprint()
    print(f"PREREG sha256 {fp}")
    res = {"prereg": PREREG, "fingerprint": fp, "timeframes": {}}
    for tf in PREREG["timeframes"]:
        data = {s: fetch(s, tf, refresh) for s in PREREG["universe"]}
        for s, d in data.items():
            print(f"  {tf} {s}: {len(d['bars'])} bars from {d['series']} (fetched {d['fetched_utc']})")
        res["timeframes"][tf] = run_tf(tf, data)
    return res


def _day(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")


def write_report(res: dict) -> str:
    os.makedirs(OUT, exist_ok=True)
    day = dt.date.today().isoformat()
    with open(os.path.join(OUT, f"{day}.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)
    lines = [f"# Micro-futures swing study {day}", "", f"PREREG sha256 `{res['fingerprint']}`", ""]
    for tf, tr in res["timeframes"].items():
        lo, hi, cut = tr["span_utc"]
        lines.append(f"## {tf}: IS {_day(lo)} .. {_day(cut)}, OOS {_day(cut)} .. {_day(hi)}")
        for rule, rr in tr["rules"].items():
            v = rr["verdict"]
            lines.append(f"### {tf}-{rule}: {'PASS' if v['ALL_PASS'] else 'FAIL'}")
            for k in PREREG["gates"]:
                detail = json.dumps({x: y for x, y in v[k].items() if x != "pass"})
                lines.append(f"- {k} {PREREG['gates'][k]}: {'PASS' if v[k]['pass'] else 'FAIL'} {detail}")
            lines.append(f"- pooled OOS {json.dumps(rr['pooled_oos'])}")
            lines.append(f"- pooled IS  {json.dumps(rr['pooled_is'])}")
            lines.append(f"- hold OOS   {json.dumps(rr['hold_oos'])}")
            for s, c in rr["per"].items():
                lines.append(f"  - {s}: OOS {json.dumps(c['oos'])} | IS net ${c['is']['net_usd']} | "
                             f"hold ${c['hold_oos']['usd']} | exits {json.dumps(c['exits'])}")
            lines.append("")
    path = os.path.join(OUT, f"{day}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    res = run(ap.parse_args().refresh)
    with open(write_report(res), encoding="utf-8") as fh:
        print(fh.read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
