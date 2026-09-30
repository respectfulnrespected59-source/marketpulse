"""The Para-Sail strategy (owner 2026-09-30): shop the low, take the icing, cap every name.

  BUY        one `fill` when the close sits within `zone` of the lowest close of the last `low_days`
             calendar days, at most once every `gap_days`
  PARA-SAIL  once the open position is worth `sail_at` more than it cost, sell `sell` of it — once per
             wave; the next buy re-arms it. `hold` = never sell (BTC is held, not para-sailed)
  CAP        never more than `cap` of your own money in (put in minus taken out)

One pure function, run by both the lesson compiler and the app, so a number a lesson says out loud is
the number the app shows for the same prices. Every trade pays the app's cost model (backtest.cost_model).
Money is scored against `peak`, the most of your own money that was ever in at once: sold cash goes back
into later buys, so money-put-in overstates what was at risk.

The parachute's two cords are not price rules and are not in here: the CAP is (above), and the NEWS cord
(withdrawals halted, bankruptcy, delisting, fraud, the team gone) is a human call. Tested 2026-09-30:
every price-triggered dump lost money — it sold SOL, Carvana and ETH at the bottom of crashes they came
back from — so no price rule sells everything.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

DAY = 86_400


class ParaSailError(ValueError):
    """Rules or prices the strategy can't honestly run on."""


def _num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def check_zone(low_days: object, zone: object) -> None:
    if not _whole(low_days):
        raise ParaSailError("low_days must be a whole number of days, 1 or more")
    if not (_num(zone) and 0 < zone < 1):
        raise ParaSailError("zone must be a fraction between 0 and 1 (0.08 = 8 %)")


@dataclass(frozen=True)
class Rules:
    low_days: int = 30          # the monthly low first (owner)
    zone: float = 0.08          # within 8 % of it
    gap_days: int = 7           # one fill a week at most
    fill: float = 100.0
    cap: float = 2_000.0        # 10 % of a $20k pile
    sail_at: float = 0.40       # the icing: up 40 % on what the position cost
    sell: float = 0.5           # take half
    hold: bool = False          # BTC: held, never para-sailed

    @classmethod
    def from_spec(cls, spec: dict) -> "Rules":
        d = cls()
        v = {f: spec.get(f, getattr(d, f)) for f in d.__dataclass_fields__}
        check_zone(v["low_days"], v["zone"])
        if not _whole(v["gap_days"]):
            raise ParaSailError("gap_days must be a whole number of days, 1 or more")
        if not (_num(v["fill"]) and v["fill"] > 0):
            raise ParaSailError("fill must be a positive amount")
        if not (_num(v["cap"]) and v["cap"] >= v["fill"]):
            raise ParaSailError("cap must be at least one fill")
        if not (_num(v["sail_at"]) and v["sail_at"] > 0):
            raise ParaSailError("sail_at must be a positive fraction (0.40 = up 40 %)")
        if not (_num(v["sell"]) and 0 < v["sell"] <= 1):
            raise ParaSailError("sell must be a fraction above 0, at most 1 (0.5 = half)")
        if not isinstance(v["hold"], bool):
            raise ParaSailError("hold must be true or false")
        return cls(low_days=v["low_days"], zone=float(v["zone"]), gap_days=v["gap_days"], fill=float(v["fill"]),
                   cap=float(v["cap"]), sail_at=float(v["sail_at"]), sell=float(v["sell"]), hold=v["hold"])


def trade_cost(kind: str) -> float:
    """Commission + slippage per side: the app's own model for this kind of asset."""
    import backtest
    return sum(backtest.cost_model("crypto" if kind == "crypto" else "stock"))


def trailing_low(ts: list[int], closes: list[float], i: int, low_days: int) -> tuple[float, int]:
    """The lowest close of the last `low_days` calendar days up to and including bar i, and its bar (the
    latest one on a tie). Calendar days, not bars: a month is a month on crypto and on stocks."""
    first = bisect.bisect_right(ts, ts[i] - low_days * DAY)
    low_bar = min(range(first, i + 1), key=lambda k: (closes[k], -k))
    return closes[low_bar], low_bar


def simulate(ts: list[int], closes: list[float], kind: str, rules: Rules,
             start: int = 0, end: int | None = None, cost: float | None = None) -> dict:
    """Run the strategy over bars start..end (inclusive). The trailing low may look before `start`: the
    chart was there before the plan was. Returns every buy and sale, the scoring, and the same buys held."""
    if not ts or len(ts) != len(closes):
        raise ParaSailError("prices need one close per timestamp, and at least one of each")
    end = len(ts) - 1 if end is None else end
    if not 0 <= start <= end < len(ts):
        raise ParaSailError(f"window {start}..{end} is outside the {len(ts)} bars")
    side = trade_cost(kind) if cost is None else cost
    buys: list[dict] = []
    sails: list[dict] = []
    units = basis = net = peak = proceeds = invested = 0.0
    armed, last_fill, cap_bar = True, None, None
    for i in range(start, end + 1):
        price, t = float(closes[i]), ts[i]
        if units > 0 and armed and not rules.hold and units * price >= basis * (1 + rules.sail_at):
            out_units = units * rules.sell
            cash = out_units * price * (1 - side)
            units, basis, net, proceeds = units - out_units, basis * (1 - rules.sell), net - cash, proceeds + cash
            armed = False
            sails.append({"bar": i, "ts": t, "price": price, "proceeds": cash})
            continue
        low, _ = trailing_low(ts, closes, i, rules.low_days)
        if price > low * (1 + rules.zone) or (last_fill is not None and t - last_fill < rules.gap_days * DAY):
            continue
        if net + rules.fill > rules.cap + 1e-9:
            cap_bar = i if cap_bar is None else cap_bar
            continue
        units += rules.fill * (1 - side) / price
        basis, net, invested = basis + rules.fill, net + rules.fill, invested + rules.fill
        peak, last_fill, armed = max(peak, net), t, True
        buys.append({"bar": i, "ts": t, "price": price})
    last = float(closes[end])
    value = units * last
    profit = value - net
    hold_value = sum(rules.fill * (1 - side) / b["price"] for b in buys) * last
    out = {"buys": buys, "sails": sails, "n": len(buys), "n_sails": len(sails), "invested": invested,
           "peak": peak, "proceeds": proceeds, "units": units, "value": value, "profit": profit,
           "roi": profit / peak * 100 if peak else 0.0, "last_price": last, "hold_value": hold_value,
           "hold_profit": hold_value - invested,
           "hold_roi": (hold_value - invested) / invested * 100 if invested else 0.0}
    if units > 0:
        out["avg"] = basis / units
    if cap_bar is not None:
        out["cap_bar"] = cap_bar
    return out
