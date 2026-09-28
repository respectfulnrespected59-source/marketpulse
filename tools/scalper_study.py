"""Crypto scalper: a pre-registered study (2026-09-28).

PRE-REGISTRATION (committed and fingerprinted BEFORE any data was fetched).
The SHA-256 of PREREG prints first on every run, so the rules provably did not
move after the results were seen. Nothing below is tuned against this data.

Question: can a LONG-ONLY intraday rule on the agent's five coins beat Alpaca's
real costs on 5-minute bars? (Alpaca crypto is spot only: no shorting, so
"either direction" is not available on this venue.)

Two rules, fixed parameters, one position per coin per rule:
  BRK  breakout: the 5m close clears the prior 12 bars' high on volume
       >= 1.5x the prior 20-bar average. Exit: +1.2 ATR target, -1.0 ATR stop,
       or 12 bars (1 hour), whichever comes first.
  DIP  dip-buy: RSI(2) on 5m closes < 10. Exit: the first close back above
       EMA(5) (sold at the next open), -1.5 ATR stop, or 12 bars.
  Both only enter while MarketPulse's own engine, run on COMPLETED hourly
  closes exactly as the app runs crypto (score_signals(closes, htf_factor=24)),
  scores >= +1.

Fills: signal on a CLOSED 5m bar, entry at the next bar's open. Stops and
targets are checked against each bar's low/high; when both could have hit in
one bar the STOP is assumed first. A gap through a level fills at the open.
Costs (primary, pass/fail): Alpaca tier-1 TAKER 0.25% per side, charged on the
asset received, plus 0.05% slippage per side. Maker 0.15% / no slippage is
reported as a sensitivity only. Sizing: a flat $25 stake (the live cap).

A rule EARNS a paper week only if ALL hold on the out-of-sample window (the
newest 40%), taker costs:
  G1  net return > 0 on >= 3 of 5 coins
  G2  pooled profit factor >= 1.20
  G3  pooled trades >= 60
  G4  pooled max drawdown <= $25 (one stake) at $25 per trade
  G5  the in-sample window (older 60%) is also net positive, pooled
If both rules pass, the higher out-of-sample profit factor goes to paper.
If neither passes, neither is paper-traded; the report says so plainly.

Paper week (Alpaca paper, Tue-Fri) go/no-go, also fixed now: net P&L > 0 after
real fees on >= 20 trades, zero guardrail errors, and mean fill slippage vs the
signal price <= 0.10%.

Run:  python tools/scalper_study.py            (cached data if present)
      python tools/scalper_study.py --refresh  (re-download)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import indicators  # noqa: E402

PREREG = {
    "universe": ["BTC-USD", "ETH-USD", "SOL-USD", "LTC-USD", "LINK-USD"],
    "source": "Coinbase Exchange public candles, granularity 300 (5m)",
    "window_utc": ["2026-07-30T00:00:00Z", "2026-09-28T00:00:00Z"],
    "oos_share": 0.40,
    "warmup_hours": 250,
    "trend_filter": "score_signals(hourly closes, htf_factor=24).score >= 1, completed hours only",
    "rules": {
        "BRK": {"lookback_high": 12, "vol_mult": 1.5, "vol_avg": 20, "tp_atr": 1.2, "sl_atr": 1.0, "max_bars": 12},
        "DIP": {"rsi_len": 2, "rsi_below": 10, "exit_ema": 5, "sl_atr": 1.5, "max_bars": 12},
    },
    "atr_len": 14,
    "costs": {"primary": {"fee": 0.0025, "slip": 0.0005}, "sensitivity_maker": {"fee": 0.0015, "slip": 0.0}},
    "stake_usd": 25.0,
    "gates": {
        "G1": "net > 0 on >= 3 of 5 coins (OOS)",
        "G2": "pooled profit factor >= 1.20 (OOS)",
        "G3": "pooled trades >= 60 (OOS)",
        "G4": "pooled max drawdown <= $25 at $25/trade (OOS)",
        "G5": "in-sample pooled net > 0",
    },
    "paper_week_go": "net P&L > 0 on >= 20 paper trades, 0 guardrail errors, mean slippage <= 0.10%",
}

GRAN = 300
DATA = os.path.join(ROOT, "reports", "scalper_study", "data")
OUT = os.path.join(ROOT, "reports", "scalper_study")


def prereg_fingerprint() -> str:
    return hashlib.sha256(json.dumps(PREREG, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- data
def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(product: str, refresh: bool = False) -> list[list[float]]:
    """[[time, low, high, open, close, volume], ...] ascending, deduped, window-clipped."""
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"{product}.json")
    if os.path.exists(path) and not refresh:
        return json.load(open(path))
    start = dt.datetime.fromisoformat(PREREG["window_utc"][0].replace("Z", "+00:00"))
    end = dt.datetime.fromisoformat(PREREG["window_utc"][1].replace("Z", "+00:00"))
    step = dt.timedelta(seconds=GRAN * 300)
    rows: dict[int, list[float]] = {}
    t = start
    while t < end:
        t2 = min(t + step, end)
        url = (f"https://api.exchange.coinbase.com/products/{product}/candles"
               f"?granularity={GRAN}&start={_iso(t)}&end={_iso(t2)}")
        req = urllib.request.Request(url, headers={"User-Agent": "marketpulse-scalper-study"})
        for attempt in range(4):
            try:
                for r in json.load(urllib.request.urlopen(req, timeout=20)):
                    rows[int(r[0])] = [float(x) for x in r]
                break
            except Exception:  # noqa: BLE001 - transient network/rate limit: back off, retry
                time.sleep(1.5 * (attempt + 1))
        time.sleep(0.2)
        t = t2
    lo, hi = start.timestamp(), end.timestamp()
    out = [rows[k] for k in sorted(rows) if lo <= k < hi]
    json.dump(out, open(path, "w"))
    return out


# ---------------------------------------------------------------- indicators (closed bars only)
def atr(h: list[float], l: list[float], c: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    trs = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    if len(c) < n:
        return out
    a = sum(trs[:n]) / n
    out[n - 1] = a
    for i in range(n, len(c)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def rsi(c: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    gains = [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    losses = [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(c)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def ema(c: list[float], n: int) -> list[float]:
    k, out, e = 2 / (n + 1), [], c[0]
    for x in c:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def hourly_scores(bars: list[list[float]]) -> list[int | None]:
    """For each 5m bar, the engine score of the latest hour COMPLETED by that bar's close."""
    hour_close: dict[int, float] = {}
    for b in bars:
        hour_close[int(b[0]) // 3600] = b[4]          # last 5m close inside the hour
    hours = sorted(hour_close)
    closes = [hour_close[h] for h in hours]
    score_at: dict[int, int] = {}
    for k in range(PREREG["warmup_hours"], len(hours)):
        score_at[hours[k]] = indicators.score_signals(closes[:k + 1], htf_factor=24)["score"]
    out: list[int | None] = []
    for b in bars:
        bar_close = int(b[0]) + GRAN
        done = bar_close // 3600 - 1                    # the last hour fully closed at bar close
        out.append(score_at.get(done))
    return out


# ---------------------------------------------------------------- the simulator
def simulate(bars: list[list[float]], rule: str, fee: float, slip: float, trend: list[int | None] | None = None) -> list[dict]:
    p = PREREG["rules"][rule]
    t = [b[0] for b in bars]
    lo = [b[1] for b in bars]
    hi = [b[2] for b in bars]
    op = [b[3] for b in bars]
    cl = [b[4] for b in bars]
    vo = [b[5] for b in bars]
    a = atr(hi, lo, cl, PREREG["atr_len"])
    trend = trend if trend is not None else hourly_scores(bars)
    r2 = rsi(cl, p["rsi_len"]) if rule == "DIP" else None
    e5 = ema(cl, p["exit_ema"]) if rule == "DIP" else None
    trades, i, n = [], 25, len(bars)
    while i < n - 1:
        ok_trend = trend[i] is not None and trend[i] >= 1
        sig = False
        if ok_trend and a[i]:
            if rule == "BRK":
                prior_hi = max(hi[i - p["lookback_high"]:i])
                vavg = sum(vo[i - p["vol_avg"]:i]) / p["vol_avg"]
                sig = cl[i] > prior_hi and vavg > 0 and vo[i] >= p["vol_mult"] * vavg
            else:
                sig = r2[i] is not None and r2[i] < p["rsi_below"]
        if not sig:
            i += 1
            continue
        e = i + 1
        entry = op[e] * (1 + slip)
        sl = op[e] - p["sl_atr"] * a[i]
        tp = op[e] + p["tp_atr"] * a[i] if rule == "BRK" else None
        exit_px, reason, j = None, "", e
        while j < n:
            if lo[j] <= sl:
                exit_px, reason = (min(op[j], sl) if j > e else sl), "stop"
                break
            if tp is not None and hi[j] >= tp:
                exit_px, reason = (max(op[j], tp) if j > e else tp), "target"
                break
            if rule == "DIP" and cl[j] > e5[j] and j + 1 < n:
                exit_px, reason, j = op[j + 1], "ema", j + 1
                break
            if j - e + 1 >= p["max_bars"] and j + 1 < n:
                exit_px, reason, j = op[j + 1], "time", j + 1
                break
            j += 1
        if exit_px is None:                              # window ended inside the trade
            break
        exit_eff = exit_px * (1 - slip)
        ret = (1 - fee) * (1 - fee) * exit_eff / entry - 1
        trades.append({"t_entry": t[e], "t_exit": t[min(j, n - 1)], "entry": entry, "exit": exit_eff,
                       "ret": ret, "reason": reason, "bars": j - e + 1})
        i = j + 1
    return trades


# ---------------------------------------------------------------- scoring
def stats(trades: list[dict], stake: float) -> dict:
    pnl = [tr["ret"] * stake for tr in trades]
    wins = [x for x in pnl if x > 0]
    losses = [-x for x in pnl if x <= 0]
    eq = peak = dd = 0.0
    for x in pnl:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(trades), "net_usd": round(sum(pnl), 2), "win_rate": round(len(wins) / len(pnl), 3) if pnl else None,
            "profit_factor": round(sum(wins) / sum(losses), 3) if losses and sum(losses) > 0 else (None if not wins else float("inf")),
            "max_dd_usd": round(dd, 2), "avg_bars": round(sum(tr["bars"] for tr in trades) / len(trades), 1) if trades else None}


def split_time(bars: list[list[float]]) -> float:
    lo = dt.datetime.fromisoformat(PREREG["window_utc"][0].replace("Z", "+00:00")).timestamp()
    hi = dt.datetime.fromisoformat(PREREG["window_utc"][1].replace("Z", "+00:00")).timestamp()
    return lo + (hi - lo) * (1 - PREREG["oos_share"])


def verdict(per_coin: dict, pooled_is: dict, pooled_oos: dict) -> dict:
    coins_pos = sum(1 for c in per_coin.values() if c["oos"]["net_usd"] > 0)
    pf = pooled_oos["profit_factor"] or 0.0
    g = {"G1": {"coins_net_positive": coins_pos, "pass": coins_pos >= 3},
         "G2": {"profit_factor": pooled_oos["profit_factor"], "pass": pf >= 1.20},
         "G3": {"trades": pooled_oos["trades"], "pass": pooled_oos["trades"] >= 60},
         "G4": {"max_dd_usd": pooled_oos["max_dd_usd"], "pass": pooled_oos["max_dd_usd"] <= PREREG["stake_usd"]},
         "G5": {"is_net_usd": pooled_is["net_usd"], "pass": pooled_is["net_usd"] > 0}}
    g["ALL_PASS"] = all(v["pass"] for k, v in g.items() if k.startswith("G"))
    return g


def run(refresh: bool) -> dict:
    fp = prereg_fingerprint()
    print(f"PREREG sha256 {fp}")
    data = {s: fetch(s, refresh) for s in PREREG["universe"]}
    for s, b in data.items():
        print(f"  {s}: {len(b)} bars")
    result = {"prereg": PREREG, "fingerprint": fp, "rules": {}}
    for rule in PREREG["rules"]:
        rr = {}
        for label, cost in PREREG["costs"].items():
            per_coin, all_is, all_oos = {}, [], []
            for s, bars in data.items():
                cut = split_time(bars)
                trend = hourly_scores(bars)
                tr = simulate(bars, rule, cost["fee"], cost["slip"], trend)
                is_t = [x for x in tr if x["t_entry"] < cut]
                oos_t = [x for x in tr if x["t_entry"] >= cut]
                per_coin[s] = {"is": stats(is_t, PREREG["stake_usd"]), "oos": stats(oos_t, PREREG["stake_usd"]),
                               "exits": {k: sum(1 for x in tr if x["reason"] == k) for k in ("target", "stop", "ema", "time")}}
                all_is += is_t
                all_oos += oos_t
            all_oos.sort(key=lambda x: x["t_entry"])
            all_is.sort(key=lambda x: x["t_entry"])
            pooled_is, pooled_oos = stats(all_is, PREREG["stake_usd"]), stats(all_oos, PREREG["stake_usd"])
            rr[label] = {"per_coin": per_coin, "pooled_is": pooled_is, "pooled_oos": pooled_oos,
                         "verdict": verdict(per_coin, pooled_is, pooled_oos) if label == "primary" else None}
        result["rules"][rule] = rr
    return result


def write_report(res: dict) -> str:
    os.makedirs(OUT, exist_ok=True)
    day = dt.date.today().isoformat()
    json.dump(res, open(os.path.join(OUT, f"{day}.json"), "w"), indent=1, default=str)
    lines = [f"# Crypto scalper study {day}", "", f"PREREG sha256 `{res['fingerprint']}`", ""]
    for rule, rr in res["rules"].items():
        v = rr["primary"]["verdict"]
        lines.append(f"## {rule}: {'PASS' if v['ALL_PASS'] else 'FAIL'}")
        for k in ("G1", "G2", "G3", "G4", "G5"):
            lines.append(f"- {k} {PREREG['gates'][k]}: {'PASS' if v[k]['pass'] else 'FAIL'} {json.dumps({x: y for x, y in v[k].items() if x != 'pass'})}")
        for label in ("primary", "sensitivity_maker"):
            po, pi = rr[label]["pooled_oos"], rr[label]["pooled_is"]
            lines.append(f"- {label}: OOS {json.dumps(po)} | IS {json.dumps(pi)}")
        for s, c in rr["primary"]["per_coin"].items():
            lines.append(f"  - {s}: OOS {json.dumps(c['oos'])} exits {json.dumps(c['exits'])}")
        lines.append("")
    path = os.path.join(OUT, f"{day}.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    res = run(ap.parse_args().refresh)
    print(open(write_report(res), encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
