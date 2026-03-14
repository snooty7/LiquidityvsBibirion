from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence


@dataclass(frozen=True)
class SweepSignal:
    side: Literal["BUY", "SELL"]
    level: float
    candle_time: int


def _price(bar: object, field: str) -> float:
    if isinstance(bar, dict):
        return float(bar[field])
    return float(bar[field])


def extract_pivot_levels(rates: Sequence[object], pivot_len: int, max_levels: int) -> list[float]:
    size = len(rates)
    if size < (pivot_len * 2 + 1):
        return []

    indexed_levels: list[tuple[int, float]] = []

    for index in range(pivot_len, size - pivot_len):
        high = _price(rates[index], "high")
        low = _price(rates[index], "low")

        high_window = [_price(rates[k], "high") for k in range(index - pivot_len, index + pivot_len + 1)]
        low_window = [_price(rates[k], "low") for k in range(index - pivot_len, index + pivot_len + 1)]

        if high == max(high_window):
            indexed_levels.append((index, high))
        if low == min(low_window):
            indexed_levels.append((index, low))

    indexed_levels.sort(key=lambda row: row[0], reverse=True)
    return [level for _, level in indexed_levels[:max_levels]]


def detect_sweep_signal(
    rates: Sequence[object],
    levels: Sequence[float],
    buffer_price: float,
) -> Optional[SweepSignal]:
    if len(rates) < 2:
        return None

    last_closed = rates[-2]
    high = _price(last_closed, "high")
    low = _price(last_closed, "low")
    close = _price(last_closed, "close")
    candle_time = int(last_closed["time"])

    for level in levels:
        if high > level + buffer_price and close < level:
            return SweepSignal(side="SELL", level=float(level), candle_time=candle_time)
        if low < level - buffer_price and close > level:
            return SweepSignal(side="BUY", level=float(level), candle_time=candle_time)

    return None


