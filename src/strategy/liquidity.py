from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence


@dataclass(frozen=True)
class SweepSignal:
    side: Literal["BUY", "SELL"]
    level: float
    candle_time: int


@dataclass(frozen=True)
class SweepValidationResult:
    valid: bool
    note: str
    avg_range: float = 0.0
    sweep_range: float = 0.0
    penetration_price: float = 0.0


@dataclass(frozen=True)
class RangeFilterResult:
    blocked: bool
    note: str
    compression_ratio: float = 0.0
    overlap_ratio: float = 0.0


def _price(bar: object, field: str) -> float:
    if isinstance(bar, dict):
        return float(bar[field])
    return float(bar[field])


def candle_range(candle: object) -> float:
    return max(_price(candle, "high") - _price(candle, "low"), 1e-10)


def locate_candle_index_by_time(rates: Sequence[object], candle_time: int) -> Optional[int]:
    for idx, bar in enumerate(rates):
        if int(bar["time"]) == int(candle_time):
            return idx
    return None


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


def evaluate_sweep_significance(
    rates: Sequence[object],
    signal: SweepSignal,
    *,
    lookback_bars: int,
    min_range_multiple: float,
    min_penetration_price: float,
) -> SweepValidationResult:
    sweep_index = locate_candle_index_by_time(rates, signal.candle_time)
    if sweep_index is None:
        return SweepValidationResult(False, "sweep_bar_missing")

    prior = list(rates[max(0, sweep_index - max(2, lookback_bars)) : sweep_index])
    if len(prior) < max(2, min(lookback_bars, 4)):
        return SweepValidationResult(False, "insufficient_sweep_context")

    sweep_candle = rates[sweep_index]
    avg_range = sum(candle_range(item) for item in prior) / len(prior)
    sweep_range = candle_range(sweep_candle)

    if signal.side == "BUY":
        penetration_price = max(0.0, float(signal.level) - _price(sweep_candle, "low"))
    else:
        penetration_price = max(0.0, _price(sweep_candle, "high") - float(signal.level))

    if penetration_price < max(min_penetration_price, 1e-10):
        return SweepValidationResult(
            False,
            "sweep_penetration_too_small",
            avg_range=avg_range,
            sweep_range=sweep_range,
            penetration_price=penetration_price,
        )

    if sweep_range < max(avg_range * min_range_multiple, 1e-10):
        return SweepValidationResult(
            False,
            "sweep_range_too_small",
            avg_range=avg_range,
            sweep_range=sweep_range,
            penetration_price=penetration_price,
        )

    return SweepValidationResult(
        True,
        "sweep_significant",
        avg_range=avg_range,
        sweep_range=sweep_range,
        penetration_price=penetration_price,
    )


def evaluate_range_filter(
    rates: Sequence[object],
    *,
    lookback_bars: int,
    max_compression_ratio: float,
    min_overlap_ratio: float,
) -> RangeFilterResult:
    window = list(rates[-max(2, lookback_bars) :])
    if len(window) < 3:
        return RangeFilterResult(False, "range_context_insufficient")

    ranges = [candle_range(item) for item in window]
    avg_range = sum(ranges) / len(ranges)
    total_range = max(_price(item, "high") for item in window) - min(_price(item, "low") for item in window)
    compression_ratio = total_range / max(avg_range, 1e-10)

    overlaps = 0
    for left, right in zip(window[:-1], window[1:]):
        overlap = max(
            0.0,
            min(_price(left, "high"), _price(right, "high")) - max(_price(left, "low"), _price(right, "low")),
        )
        overlap_ratio = overlap / max(min(candle_range(left), candle_range(right)), 1e-10)
        if overlap_ratio >= 0.50:
            overlaps += 1

    realized_overlap_ratio = overlaps / max(len(window) - 1, 1)
    blocked = compression_ratio <= max_compression_ratio and realized_overlap_ratio >= min_overlap_ratio
    note = "range_chop_blocked" if blocked else "range_ok"
    return RangeFilterResult(
        blocked,
        note,
        compression_ratio=compression_ratio,
        overlap_ratio=realized_overlap_ratio,
    )


