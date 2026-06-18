"""Technical indicators + signal scoring — pure Python, no numpy/pandas.

Every function takes a list of closing prices (oldest first) and returns either
a single latest value or a short series. Kept dependency-free so the whole app
runs on a stock Python install.
"""
from __future__ import annotations


def sma(values: list[float], period: int) -> float | None:
    """Simple moving average of the last `period` values."""
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[float]:
    """Full exponential moving average series (seeded with an SMA)."""
    if len(values) < period or period <= 0:
        return []
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for price in values[period:]:
        out.append(price * k + out[-1] * (1 - k))
    return out


def ema(values: list[float], period: int) -> float | None:
    series = ema_series(values, period)
    return series[-1] if series else None


def rsi(values: list[float], period: int = 14) -> float | None:
    """Wilder's RSI for the latest bar."""
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram) for the latest bar."""
    if len(values) < slow + signal:
        return None, None, None
    fast_e = ema_series(values, fast)
    slow_e = ema_series(values, slow)
    n = min(len(fast_e), len(slow_e))
    macd_line = [fast_e[-n + i] - slow_e[-n + i] for i in range(n)]
    if len(macd_line) < signal:
        return None, None, None
    signal_e = ema_series(macd_line, signal)
    if not signal_e:
        return None, None, None
    line = round(macd_line[-1], 4)
    sig = round(signal_e[-1], 4)
    return line, sig, round(line - sig, 4)


def _stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / n) ** 0.5


def bollinger_pct_b(values: list[float], period: int = 20, mult: float = 2.0) -> float | None:
    """%B = where price sits in the Bollinger band. <0 = below lower (stretched
    down), >1 = above upper (stretched up)."""
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    sd = _stdev(window)
    if sd == 0:
        return 0.5
    lower, upper = mid - mult * sd, mid + mult * sd
    return round((values[-1] - lower) / (upper - lower), 3)


def stochastic_k(values: list[float], period: int = 14) -> float | None:
    """Close-based %K. <20 oversold, >80 overbought."""
    if len(values) < period:
        return None
    window = values[-period:]
    lo, hi = min(window), max(window)
    if hi == lo:
        return 50.0
    return round((values[-1] - lo) / (hi - lo) * 100, 1)


def htf_trend(values: list[float], factor: int = 5, period: int = 20) -> int:
    """Higher-timeframe trend confirmation: resample to a slower timeframe
    (e.g. daily->weekly with factor 5) and check price vs its moving average.
    Returns +1 (up), -1 (down), 0 (unknown)."""
    if factor < 2 or len(values) < factor * (period + 1):
        return 0
    resampled = values[::factor]
    ma = sma(resampled, period)
    if ma is None:
        return 0
    return 1 if values[-1] > ma else -1


# Signal score → label mapping. Score now spans roughly -6..+6 (7 factors).
_LABELS = [
    (3, "STRONG BUY", "strong-buy"),
    (1, "BUY", "buy"),
    (0, "NEUTRAL", "neutral"),
    (-2, "SELL", "sell"),
    (-99, "STRONG SELL", "strong-sell"),
]


def score_signals(closes: list[float], htf_factor: int = 5) -> dict:
    """Multi-factor confluence signal: RSI, MACD, short trend (SMA50),
    major trend (50/200 cross), Bollinger %B, Stochastic, and a
    higher-timeframe trend check. Every factor that fires is listed in
    `reasons` so the signal is transparent, not a black box.

    `htf_factor` resamples for the higher-timeframe check (5 = daily->weekly,
    24 = hourly->daily).
    """
    price = closes[-1] if closes else None
    r = rsi(closes, 14)
    macd_line, macd_sig, hist = macd(closes)
    sma50 = sma(closes, 50) if len(closes) >= 50 else sma(closes, max(2, len(closes) // 2))
    sma200 = sma(closes, 200)
    pct_b = bollinger_pct_b(closes)
    stoch = stochastic_k(closes)
    htf = htf_trend(closes, htf_factor)

    score = 0
    reasons = []

    # Momentum / mean-reversion
    if r is not None:
        if r < 30:
            score += 1; reasons.append(f"RSI {r} oversold")
        elif r > 70:
            score -= 1; reasons.append(f"RSI {r} overbought")
        else:
            reasons.append(f"RSI {r}")

    if hist is not None:
        if hist > 0:
            score += 1; reasons.append("MACD bullish")
        elif hist < 0:
            score -= 1; reasons.append("MACD bearish")

    if stoch is not None:
        if stoch < 20:
            score += 1; reasons.append(f"Stoch {stoch} oversold")
        elif stoch > 80:
            score -= 1; reasons.append(f"Stoch {stoch} overbought")

    if pct_b is not None:
        if pct_b < 0:
            score += 1; reasons.append("below lower Bollinger")
        elif pct_b > 1:
            score -= 1; reasons.append("above upper Bollinger")

    # Trend
    if price is not None and sma50 is not None:
        if price > sma50:
            score += 1; reasons.append("above SMA50")
        else:
            score -= 1; reasons.append("below SMA50")

    if sma50 is not None and sma200 is not None:
        if sma50 > sma200:
            score += 1; reasons.append("golden cross (50>200)")
        else:
            score -= 1; reasons.append("death cross (50<200)")

    if htf > 0:
        score += 1; reasons.append("higher-TF uptrend")
    elif htf < 0:
        score -= 1; reasons.append("higher-TF downtrend")

    label, css = "NEUTRAL", "neutral"
    for threshold, lbl, key in _LABELS:
        if score >= threshold:
            label, css = lbl, key
            break

    return {
        "score": score,
        "label": label,
        "css": css,
        "rsi": r,
        "macd_hist": hist,
        "stoch": stoch,
        "pct_b": pct_b,
        "sma": round(sma50, 4) if sma50 else None,
        "sma200": round(sma200, 4) if sma200 else None,
        "htf": htf,
        "reasons": reasons,
    }


# ----------------------------------------------------------------- MA stack + VWAP
def ma_stack(closes: list[float], periods=(5, 14, 21)) -> dict | None:
    """Short-term moving-average stack for trend/entry reads. Returns the 5/14/21
    MAs plus a stack verdict: 'bull' (price>MA5>MA14>MA21), 'bear' (the inverse),
    else 'mixed'. Stacked + price leading = a clean trend; tangled = chop."""
    if not closes:
        return None
    price = closes[-1]
    m5 = sma(closes, 5) if len(closes) >= 5 else None
    m14 = sma(closes, 14) if len(closes) >= 14 else None
    m21 = sma(closes, 21) if len(closes) >= 21 else None
    stack = "mixed"
    if None not in (m5, m14, m21):
        if price > m5 > m14 > m21:
            stack = "bull"
        elif price < m5 < m14 < m21:
            stack = "bear"
    return {
        "ma5": round(m5, 2) if m5 is not None else None,
        "ma14": round(m14, 2) if m14 is not None else None,
        "ma21": round(m21, 2) if m21 is not None else None,
        "stack": stack,
        "above_ma5": (price > m5) if m5 is not None else None,
    }


def session_vwap(highs, lows, closes, volumes) -> float | None:
    """Volume-weighted average price over the provided (intraday) bars.
    Typical price = (H+L+C)/3, weighted by volume. This is the real session
    VWAP traders watch — it needs intraday bars, not daily ones. None if no vol."""
    num = den = 0.0
    for h, l, c, v in zip(highs, lows, closes, volumes):
        if None in (h, l, c, v) or v <= 0:
            continue
        num += ((h + l + c) / 3) * v
        den += v
    return round(num / den, 2) if den > 0 else None


# ----------------------------------------------------------------- TTM Squeeze
# John Carter's squeeze: when Bollinger Bands contract INSIDE the Keltner
# Channels, volatility is coiling and a breakout is pending. A momentum
# histogram (linear regression of price vs its range midline) hints the lean.
# The squeeze itself is DIRECTION-AGNOSTIC — "on" means energy building, not up.

def _linreg_value(ys: list[float]) -> float:
    """Value of the least-squares fit line at the most recent point."""
    n = len(ys)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs) or 1e-9
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den
    return (my - slope * mx) + slope * (n - 1)


def _true_ranges(highs, lows, closes) -> list[float]:
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            pc = closes[i - 1]
            trs.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return trs


def _squeeze_on_at(highs, lows, closes, end, length, bb_mult, kc_mult) -> bool:
    win = closes[end - length:end]
    basis = sum(win) / length
    dev = bb_mult * _stdev(win)
    rng = sum(_true_ranges(highs[:end], lows[:end], closes[:end])[-length:]) / length
    return (basis - dev) > (basis - kc_mult * rng) and (basis + dev) < (basis + kc_mult * rng)


def resample_ohlc(highs, lows, closes, factor: int = 2):
    """Aggregate finer OHLC bars into coarser ones (weekly->bi-weekly = factor 2),
    anchored to the newest bar so the latest coarse bar includes fresh data."""
    H, L, C = [], [], []
    i = len(closes)
    while i > 0:
        lo = max(0, i - factor)
        H.insert(0, max(highs[lo:i]))
        L.insert(0, min(lows[lo:i]))
        C.insert(0, closes[i - 1])
        i -= factor
    return H, L, C


def ttm_squeeze(highs, lows, closes, length: int = 20,
                bb_mult: float = 2.0, kc_mult: float = 1.5) -> dict | None:
    """Return {state, bars, mom, accel} or None if there isn't enough history.

    state : 'on' (coiling), 'fired' (released last bar), or 'off' (expanded)
    bars  : how many consecutive bars the squeeze has been on
    mom   : 'bull' | 'bear'   accel: 'rising' | 'falling' | 'fading'
    """
    n = len(closes)
    if n < 2 * length + 2:
        return None
    on_now = _squeeze_on_at(highs, lows, closes, n, length, bb_mult, kc_mult)
    on_prev = _squeeze_on_at(highs, lows, closes, n - 1, length, bb_mult, kc_mult)
    bars_on, k = 0, n
    while k > length and _squeeze_on_at(highs, lows, closes, k, length, bb_mult, kc_mult):
        bars_on += 1
        k -= 1
    moms = []
    for i in range(length, n + 1):
        cwin = closes[i - length:i]
        hh = max(highs[i - length:i])
        ll = min(lows[i - length:i])
        moms.append(closes[i - 1] - ((hh + ll) / 2 + sum(cwin) / length) / 2)
    val = _linreg_value(moms[-length:])
    prev = _linreg_value(moms[-length - 1:-1])
    if val >= 0:
        mom, accel = "bull", ("rising" if val > prev else "fading")
    else:
        mom, accel = "bear", ("falling" if val < prev else "fading")
    state = "on" if on_now else ("fired" if on_prev else "off")
    return {"state": state, "bars": bars_on, "mom": mom, "accel": accel}
