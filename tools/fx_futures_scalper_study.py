"""FX + micro-futures scalper: a pre-registered study (2026-09-28).

PRE-REGISTRATION (committed and fingerprinted BEFORE any data was fetched).

Why this study exists: the crypto study (tools/scalper_study.py, prereg
34dd0da) failed on STRUCTURE, not on the rules: Alpaca's 0.60% round trip is
2.5-5x a typical 5-minute crypto move. Forex majors and micro index futures
cost a small fraction of a 5-minute move, so the same question is asked where
the cost/move ratio is survivable.

Nothing is tuned: the SAME two rules and parameters as the crypto study, run
on a NEW universe, with one change forced by the data and one by the venue:
  * no volume condition (free FX bars carry no volume), and
  * both directions (FX and futures can be sold short). A short is the mirror
    of the long: prior-12 LOW break / RSI(2) > 90, engine hourly score <= -1.

  BRK  long: 5m close > prior 12 bars' high, engine hourly score >= +1.
       short: 5m close < prior 12 bars' low, engine hourly score <= -1.
       Exit: 1.2 ATR target, 1.0 ATR stop, or 12 bars.
  DIP  long: RSI(2) < 10, score >= +1. short: RSI(2) > 90, score <= -1.
       Exit: first close back across EMA(5) (next open), 1.5 ATR stop, 12 bars.
  The engine score is MarketPulse's own score_signals on COMPLETED hourly
  closes (htf_factor=24), the same filter as the crypto study.

Sessions (FX and futures close; crypto never did): no entry whose fill bar
starts more than 10 minutes after the signal bar, and a held position goes
flat at the close of the last bar before such a gap (the schedule is known,
so this is not lookahead).

Fills: signal on a closed 5m bar, entry at the next open; stop before target
inside one bar; a gap through a level fills at the open. Costs are charged per
round trip in price units:
  FX (OANDA-style retail spread + 0.2 pip slippage per side):
    EURUSD 1.2 pips, GBPUSD 1.6, USDJPY 1.2, AUDUSD 1.3, USDCAD 1.8.
  Micro futures ($2.00 commission+fees round trip + 1 tick slippage per side):
    MES ($5/pt, 0.25 tick) = $4.50 = 0.90 pt; MNQ ($2/pt) = $3.00 = 1.50 pt.
Results are in R: one R = the trade's stop distance, so pips and points pool.

Data: Yahoo 5m bars, range=60d, fetched once and cached with a UTC stamp (the
cache IS the dataset). MES=F / MNQ=F; if Yahoo has no 5m micro series, ES=F /
NQ=F (same index price) with the micro costs above. OOS = the newest 40% of
the common time span.

A rule EARNS a paper week only if ALL hold out-of-sample:
  G1  net R > 0 on >= 4 of 7 instruments
  G2  pooled profit factor >= 1.20
  G3  pooled trades >= 100
  G4  pooled max drawdown <= 15 R
  G5  the in-sample window is also net positive (pooled R)
If both pass, the higher OOS profit factor goes to paper. If neither, no paper.
Paper week go/no-go (OANDA practice / futures sim): pooled net R > 0 on >= 20
trades and mean fill slippage no worse than modelled.

Run:  python tools/fx_futures_scalper_study.py            (cached data)
      python tools/fx_futures_scalper_study.py --refresh
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("scalper_study", os.path.join(ROOT, "tools", "scalper_study.py"))
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)          # shared, tested helpers: atr, rsi, ema, hourly_scores

PREREG = {
    "universe": {
        "EURUSD=X": {"kind": "fx", "pip": 0.0001, "rt_cost": 1.2 + 0.4},
        "GBPUSD=X": {"kind": "fx", "pip": 0.0001, "rt_cost": 1.6 + 0.4},
        "USDJPY=X": {"kind": "fx", "pip": 0.01, "rt_cost": 1.2 + 0.4},
        "AUDUSD=X": {"kind": "fx", "pip": 0.0001, "rt_cost": 1.3 + 0.4},
        "USDCAD=X": {"kind": "fx", "pip": 0.0001, "rt_cost": 1.8 + 0.4},
        "MES=F": {"kind": "fut", "pip": 1.0, "rt_cost": 0.90, "fallback": "ES=F"},
        "MNQ=F": {"kind": "fut", "pip": 1.0, "rt_cost": 1.50, "fallback": "NQ=F"},
    },
    "source": "Yahoo chart API, interval=5m, range=60d, cached once",
    "oos_share": 0.40,
    "session_gap_s": 600,
    "rules": {
        "BRK": {"lookback": 12, "tp_atr": 1.2, "sl_atr": 1.0, "max_bars": 12},
        "DIP": {"rsi_len": 2, "rsi_lo": 10, "rsi_hi": 90, "exit_ema": 5, "sl_atr": 1.5, "max_bars": 12},
    },
    "atr_len": 14,
    "trend": "long if hourly score >= 1, short if <= -1 (completed hours)",
    "gates": {
        "G1": "net R > 0 on >= 4 of 7 instruments (OOS)",
        "G2": "pooled profit factor >= 1.20 (OOS)",
        "G3": "pooled trades >= 100 (OOS)",
        "G4": "pooled max drawdown <= 15 R (OOS)",
        "G5": "in-sample pooled net R > 0",
    },
}

DATA = os.path.join(ROOT, "reports", "fx_futures_study", "data")
OUT = os.path.join(ROOT, "reports", "fx_futures_study")


def prereg_fingerprint() -> str:
    return hashlib.sha256(json.dumps(PREREG, sort_keys=True).encode()).hexdigest()


def _yahoo(sym: str) -> list[list[float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=60d&interval=5m"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        r = json.load(resp)["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        out.append([float(t), float(l), float(h), float(o), float(c), float(q["volume"][i] or 0)])
    return out


def fetch(sym: str, refresh: bool = False) -> dict:
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"{sym}.json")
    if os.path.exists(path) and not refresh:
        with open(path) as fh:
            return json.load(fh)
    spec = PREREG["universe"][sym]
    bars, used = _yahoo(sym), sym
    if len(bars) < 2000 and spec.get("fallback"):
        bars, used = _yahoo(spec["fallback"]), spec["fallback"]
    if len(bars) < 2000:
        raise RuntimeError(f"{sym}: only {len(bars)} 5m bars from Yahoo; the study needs ~60 days")
    d = {"symbol": sym, "series": used, "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
         "bars": bars}
    with open(path, "w") as fh:
        json.dump(d, fh)
    return d


def _signal(rule: str, p: dict, s: int | None, i: int, hi: list, lo: list, cl: list, r2: list | None) -> int:
    """+1 long, -1 short, 0 nothing, on the CLOSED bar i."""
    if s is None:
        return 0
    if rule == "BRK":
        if s >= 1 and cl[i] > max(hi[i - p["lookback"]:i]):
            return 1
        if s <= -1 and cl[i] < min(lo[i - p["lookback"]:i]):
            return -1
        return 0
    if r2[i] is None:
        return 0
    if s >= 1 and r2[i] < p["rsi_lo"]:
        return 1
    if s <= -1 and r2[i] > p["rsi_hi"]:
        return -1
    return 0


def _exit(rule: str, p: dict, d: int, e: int, sl: float, tp: float | None, bars: list[list[float]],
          e5: list | None) -> tuple[float, str, int] | None:
    """Walk forward from the fill bar e. Returns (exit price, reason, exit bar) or None at data end."""
    gap_s = PREREG["session_gap_s"]
    n = len(bars)
    for j in range(e, n):
        _, l, h, o, c, _ = bars[j]
        if (l <= sl) if d == 1 else (h >= sl):
            gapped = (o < sl) if d == 1 else (o > sl)
            return (o if j > e and gapped else sl), "stop", j
        if tp is not None and ((h >= tp) if d == 1 else (l <= tp)):
            gapped = (o > tp) if d == 1 else (o < tp)
            return (o if j > e and gapped else tp), "target", j
        if j + 1 >= n:
            return None
        if bars[j + 1][0] - bars[j][0] > gap_s:
            return c, "session", j
        if rule == "DIP" and ((d == 1 and c > e5[j]) or (d == -1 and c < e5[j])):
            return bars[j + 1][3], "ema", j + 1
        if j - e + 1 >= p["max_bars"]:
            return bars[j + 1][3], "time", j + 1
    return None


def simulate(bars: list[list[float]], rule: str, rt_cost: float, pip: float,
             trend: list[int | None] | None = None) -> list[dict]:
    """Both directions. P&L in price units net of the round-trip cost, and in R."""
    p = PREREG["rules"][rule]
    lo = [b[1] for b in bars]
    hi = [b[2] for b in bars]
    cl = [b[4] for b in bars]
    a = ss.atr(hi, lo, cl, PREREG["atr_len"])
    trend = trend if trend is not None else ss.hourly_scores(bars)
    r2 = ss.rsi(cl, p["rsi_len"]) if rule == "DIP" else None
    e5 = ss.ema(cl, p["exit_ema"]) if rule == "DIP" else None
    cost = rt_cost * pip
    trades, i, n = [], 25, len(bars)
    while i < n - 1:
        d = _signal(rule, p, trend[i], i, hi, lo, cl, r2) if a[i] else 0
        e = i + 1
        if d == 0 or bars[e][0] - bars[i][0] > PREREG["session_gap_s"]:
            i += 1
            continue
        entry = bars[e][3]
        risk = p["sl_atr"] * a[i]
        sl = entry - d * risk
        tp = entry + d * p["tp_atr"] * a[i] if rule == "BRK" else None
        out = _exit(rule, p, d, e, sl, tp, bars, e5)
        if out is None:
            break
        exit_px, reason, j = out
        pnl = d * (exit_px - entry) - cost
        trades.append({"t_entry": bars[e][0], "dir": d, "entry": entry, "exit": exit_px, "pnl_px": pnl,
                       "pnl_pips": pnl / pip, "r": pnl / risk, "reason": reason, "bars": j - e + 1})
        i = j + 1
    return trades


def stats(trades: list[dict]) -> dict:
    rs = [x["r"] for x in trades]
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r <= 0]
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(rs), "net_r": round(sum(rs), 2), "win_rate": round(len(wins) / len(rs), 3) if rs else None,
            "profit_factor": round(sum(wins) / sum(losses), 3) if losses and sum(losses) > 0 else None,
            "max_dd_r": round(dd, 2), "net_pips_or_pts": round(sum(x["pnl_pips"] for x in trades), 1),
            "longs": sum(1 for x in trades if x["dir"] == 1), "shorts": sum(1 for x in trades if x["dir"] == -1)}


def verdict(per: dict, pooled_is: dict, pooled_oos: dict) -> dict:
    pos = sum(1 for v in per.values() if v["oos"]["net_r"] > 0)
    pf = pooled_oos["profit_factor"] or 0.0
    g = {"G1": {"instruments_positive": pos, "pass": pos >= 4},
         "G2": {"profit_factor": pooled_oos["profit_factor"], "pass": pf >= 1.20},
         "G3": {"trades": pooled_oos["trades"], "pass": pooled_oos["trades"] >= 100},
         "G4": {"max_dd_r": pooled_oos["max_dd_r"], "pass": pooled_oos["max_dd_r"] <= 15},
         "G5": {"is_net_r": pooled_is["net_r"], "pass": pooled_is["net_r"] > 0}}
    g["ALL_PASS"] = all(g[k]["pass"] for k in ("G1", "G2", "G3", "G4", "G5"))
    return g


def run(refresh: bool) -> dict:
    fp = prereg_fingerprint()
    print(f"PREREG sha256 {fp}")
    data = {s: fetch(s, refresh) for s in PREREG["universe"]}
    lo = max(d["bars"][0][0] for d in data.values())
    hi = min(d["bars"][-1][0] for d in data.values())
    cut = lo + (hi - lo) * (1 - PREREG["oos_share"])
    for s, d in data.items():
        print(f"  {s}: {len(d['bars'])} bars from {d['series']} (fetched {d['fetched_utc']})")
    res = {"prereg": PREREG, "fingerprint": fp, "span_utc": [lo, hi, cut], "rules": {}}
    for rule in PREREG["rules"]:
        per, all_is, all_oos = {}, [], []
        for s, d in data.items():
            bars = [b for b in d["bars"] if lo <= b[0] <= hi]
            spec = PREREG["universe"][s]
            tr = simulate(bars, rule, spec["rt_cost"], spec["pip"])
            is_t = [x for x in tr if x["t_entry"] < cut]
            oos_t = [x for x in tr if x["t_entry"] >= cut]
            per[s] = {"is": stats(is_t), "oos": stats(oos_t),
                      "exits": {k: sum(1 for x in tr if x["reason"] == k)
                                for k in ("target", "stop", "ema", "time", "session")}}
            all_is += is_t
            all_oos += oos_t
        all_is.sort(key=lambda x: x["t_entry"])
        all_oos.sort(key=lambda x: x["t_entry"])
        pi, po = stats(all_is), stats(all_oos)
        res["rules"][rule] = {"per": per, "pooled_is": pi, "pooled_oos": po, "verdict": verdict(per, pi, po)}
    return res


def write_report(res: dict) -> str:
    os.makedirs(OUT, exist_ok=True)
    day = dt.date.today().isoformat()
    with open(os.path.join(OUT, f"{day}.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    lines = [f"# FX + micro-futures scalper study {day}", "", f"PREREG sha256 `{res['fingerprint']}`", ""]
    for rule, rr in res["rules"].items():
        v = rr["verdict"]
        lines.append(f"## {rule}: {'PASS' if v['ALL_PASS'] else 'FAIL'}")
        for k in ("G1", "G2", "G3", "G4", "G5"):
            detail = json.dumps({x: y for x, y in v[k].items() if x != "pass"})
            lines.append(f"- {k} {PREREG['gates'][k]}: {'PASS' if v[k]['pass'] else 'FAIL'} {detail}")
        lines.append(f"- pooled OOS {json.dumps(rr['pooled_oos'])}")
        lines.append(f"- pooled IS  {json.dumps(rr['pooled_is'])}")
        for s, c in rr["per"].items():
            lines.append(f"  - {s}: OOS {json.dumps(c['oos'])} | IS net_r {c['is']['net_r']} | exits {json.dumps(c['exits'])}")
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
