"""Two predeclared H1/H4 research signals; callers supply only closed candles."""
from __future__ import annotations

import math
from typing import Sequence

from src.strategy.filters import ema
from src.strategy.liquidity import SweepSignal

HTF_MODES = {"htf_trend_pullback", "htf_range_retest"}
RANGE_BARS = 20
MIN_BODY_RATIO = .5


def _closed_context(rows: Sequence[object], count: int) -> list[dict] | None:
    if len(rows) < count:
        return None
    result = [{key: float(row[key]) for key in ("open", "high", "low", "close", "time")}
              for row in rows[-count:]]
    if any(not all(math.isfinite(value) for value in row.values())
           or not 0 < row["low"] <= min(row["open"], row["close"])
           <= max(row["open"], row["close"]) <= row["high"] for row in result):
        return None
    if any(b["time"] <= a["time"] for a, b in zip(result, result[1:])):
        return None
    return result


def detect_htf_signal(mode: str, closed_entry: Sequence[object], closed_bias: Sequence[object], *,
                      buffer_price: float, fast_period: int = 20, slow_period: int = 50) -> SweepSignal | None:
    """H4 trend plus H1 pullback/reclaim or a closed breakout followed by a retest.

    Both use fixed 3*slow EMA initialization. Neither creates protection overrides:
    the existing risk sizing, initial stop and exit protections remain in charge.
    """
    if mode not in HTF_MODES:
        raise ValueError("Unsupported H1/H4 research mode")
    if not 1 < fast_period < slow_period or not math.isfinite(buffer_price) or buffer_price < 0:
        raise ValueError("Invalid H1/H4 signal parameters")
    count = max(3*slow_period, RANGE_BARS+2)
    entry, bias = _closed_context(closed_entry, count), _closed_context(closed_bias, count)
    if entry is None or bias is None:
        return None
    # H4 bars must actually be closed by the H1 decision, even if a caller errs.
    if bias[-1]["time"]+14400 > entry[-1]["time"]+3600:
        return None
    fast = ema([bar["close"] for bar in bias], fast_period)
    slow = ema([bar["close"] for bar in bias], slow_period)
    if bias[-1]["close"] > fast[-1] > slow[-1] and slow[-1] > slow[-4]:
        side = "BUY"
    elif bias[-1]["close"] < fast[-1] < slow[-1] and slow[-1] < slow[-4]:
        side = "SELL"
    else:
        return None
    previous, current = entry[-2:]
    spread = current["high"]-current["low"]
    if spread <= 0 or abs(current["close"]-current["open"])/spread < MIN_BODY_RATIO:
        return None
    if (side == "BUY" and current["close"] <= current["open"]) or (
            side == "SELL" and current["close"] >= current["open"]):
        return None
    if mode == "htf_trend_pullback":
        entry_fast = ema([bar["close"] for bar in entry], fast_period)
        entry_slow = ema([bar["close"] for bar in entry], slow_period)
        level = entry_fast[-2]
        if side == "BUY":
            valid = (entry_fast[-1] > entry_slow[-1] and previous["low"] <= level
                     and previous["close"] <= level and current["close"] > entry_fast[-1]
                     and current["close"] > previous["high"]+buffer_price)
        else:
            valid = (entry_fast[-1] < entry_slow[-1] and previous["high"] >= level
                     and previous["close"] >= level and current["close"] < entry_fast[-1]
                     and current["close"] < previous["low"]-buffer_price)
    else:
        # The range excludes BOTH the breakout and its confirmation candle.
        channel = entry[-RANGE_BARS-2:-2]
        if side == "BUY":
            level = max(bar["high"] for bar in channel)
            valid = (previous["close"] > level+buffer_price
                     and current["low"] <= level+buffer_price and current["close"] > level+buffer_price)
        else:
            level = min(bar["low"] for bar in channel)
            valid = (previous["close"] < level-buffer_price
                     and current["high"] >= level-buffer_price and current["close"] < level-buffer_price)
    return SweepSignal(side=side, level=float(level), candle_time=int(current["time"])) if valid else None
