from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class SessionOpenScalpSignalResult:
    signal: Optional[SweepSignal]
    note: str
    opening_range_high: float = 0.0
    opening_range_low: float = 0.0
    compression_ratio: float = 0.0


@dataclass(frozen=True)
class MicroBurstSignalResult:
    signal: Optional[SweepSignal]
    note: str


def _price(bar: object, field: str) -> float:
    if isinstance(bar, dict):
        return float(bar[field])
    return float(bar[field])


def candle_range(candle: object) -> float:
    return max(_price(candle, "high") - _price(candle, "low"), 1e-10)


def candle_body_ratio(candle: object) -> float:
    return abs(_price(candle, "close") - _price(candle, "open")) / candle_range(candle)


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


def _parse_hhmm_to_minutes(value: str) -> int:
    hour_raw, minute_raw = value.split(":", 1)
    hour = int(hour_raw)
    minute = int(minute_raw)
    return hour * 60 + minute


def evaluate_compression_window(
    rates: Sequence[object],
    *,
    lookback_bars: int,
    max_compression_ratio: float,
) -> RangeFilterResult:
    window = list(rates[-max(3, lookback_bars) :])
    if len(window) < 3:
        return RangeFilterResult(False, "compression_context_insufficient")

    ranges = [candle_range(item) for item in window]
    avg_range = sum(ranges) / len(ranges)
    total_range = max(_price(item, "high") for item in window) - min(_price(item, "low") for item in window)
    compression_ratio = total_range / max(avg_range, 1e-10)
    blocked = compression_ratio <= max_compression_ratio
    return RangeFilterResult(
        blocked=blocked,
        note="compression_ok" if blocked else "compression_not_tight",
        compression_ratio=compression_ratio,
        overlap_ratio=0.0,
    )


def detect_session_open_scalp_signal(
    rates: Sequence[object],
    *,
    session_start_utc: str,
    open_range_minutes: int,
    watch_minutes: int,
    buffer_price: float,
    body_ratio_min: float,
    preopen_lookback_bars: int,
    preopen_max_compression_ratio: float,
) -> SessionOpenScalpSignalResult:
    if len(rates) < max(5, preopen_lookback_bars + 3):
        return SessionOpenScalpSignalResult(None, "scalp_context_insufficient")

    last_closed = rates[-2]
    last_dt = datetime.fromtimestamp(int(last_closed["time"]), tz=timezone.utc)
    session_minutes = _parse_hhmm_to_minutes(session_start_utc)
    session_start = last_dt.replace(
        hour=session_minutes // 60,
        minute=session_minutes % 60,
        second=0,
        microsecond=0,
    )
    if last_dt < session_start:
        return SessionOpenScalpSignalResult(None, "scalp_before_session")

    open_range_end = session_start.timestamp() + int(open_range_minutes) * 60
    watch_end = session_start.timestamp() + int(watch_minutes) * 60
    last_closed_ts = int(last_closed["time"])
    if last_closed_ts < int(open_range_end):
        return SessionOpenScalpSignalResult(None, "scalp_opening_range_incomplete")
    if last_closed_ts >= int(watch_end):
        return SessionOpenScalpSignalResult(None, "scalp_outside_watch_window")

    opening_range = [
        bar
        for bar in rates[:-1]
        if int(session_start.timestamp()) <= int(bar["time"]) < int(open_range_end)
    ]
    if len(opening_range) < max(2, int(open_range_minutes // 2)):
        return SessionOpenScalpSignalResult(None, "scalp_opening_range_missing")

    preopen = [
        bar
        for bar in rates[:-1]
        if int(bar["time"]) < int(session_start.timestamp())
    ]
    compression = evaluate_compression_window(
        preopen,
        lookback_bars=preopen_lookback_bars,
        max_compression_ratio=preopen_max_compression_ratio,
    )
    if not compression.blocked:
        return SessionOpenScalpSignalResult(None, "scalp_preopen_not_compressed", compression_ratio=compression.compression_ratio)

    or_high = max(_price(bar, "high") for bar in opening_range)
    or_low = min(_price(bar, "low") for bar in opening_range)
    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high = _price(last_closed, "high")
    low = _price(last_closed, "low")
    body_ratio = candle_body_ratio(last_closed)

    if low < or_low - buffer_price and close_price > or_low and close_price > open_price and body_ratio >= body_ratio_min:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="BUY", level=float(or_low), candle_time=int(last_closed["time"])),
            "scalp_buy_reclaim",
            opening_range_high=or_high,
            opening_range_low=or_low,
            compression_ratio=compression.compression_ratio,
        )

    if high > or_high + buffer_price and close_price < or_high and close_price < open_price and body_ratio >= body_ratio_min:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="SELL", level=float(or_high), candle_time=int(last_closed["time"])),
            "scalp_sell_reject",
            opening_range_high=or_high,
            opening_range_low=or_low,
            compression_ratio=compression.compression_ratio,
        )

    return SessionOpenScalpSignalResult(
        None,
        "scalp_wait_liquidity_reclaim",
        opening_range_high=or_high,
        opening_range_low=or_low,
        compression_ratio=compression.compression_ratio,
    )


def detect_h4_bias_micro_burst_signal(
    rates: Sequence[object],
    *,
    pullback_bars: int,
    body_ratio_min: float,
    buffer_price: float,
) -> MicroBurstSignalResult:
    needed = max(3, int(pullback_bars) + 2)
    if len(rates) < needed:
        return MicroBurstSignalResult(None, "micro_burst_context_insufficient")

    last_closed = rates[-2]
    prior = list(rates[-(int(pullback_bars) + 2) : -2])
    if len(prior) < int(pullback_bars):
        return MicroBurstSignalResult(None, "micro_burst_context_insufficient")

    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    body_ok = candle_body_ratio(last_closed) >= body_ratio_min
    prior_high = max(_price(item, "high") for item in prior)
    prior_low = min(_price(item, "low") for item in prior)
    bearish_prior = sum(1 for item in prior if _price(item, "close") < _price(item, "open"))
    bullish_prior = sum(1 for item in prior if _price(item, "close") > _price(item, "open"))

    if (
        close_price > open_price
        and body_ok
        and bearish_prior >= max(1, len(prior) // 2)
        and close_price > prior_high + buffer_price
    ):
        return MicroBurstSignalResult(
            SweepSignal(side="BUY", level=float(prior_high), candle_time=int(last_closed["time"])),
            "micro_burst_buy_break",
        )

    if (
        close_price < open_price
        and body_ok
        and bullish_prior >= max(1, len(prior) // 2)
        and close_price < prior_low - buffer_price
    ):
        return MicroBurstSignalResult(
            SweepSignal(side="SELL", level=float(prior_low), candle_time=int(last_closed["time"])),
            "micro_burst_sell_break",
        )

    return MicroBurstSignalResult(None, "micro_burst_wait_break")


def detect_trend_micro_burst_v2_signal(
    rates: Sequence[object],
    *,
    pullback_bars: int,
    body_ratio_min: float,
    range_multiple: float,
    buffer_price: float,
) -> MicroBurstSignalResult:
    needed = max(4, int(pullback_bars) + 3)
    if len(rates) < needed:
        return MicroBurstSignalResult(None, "trend_micro_burst_context_insufficient")

    signal_idx = len(rates) - 2
    pullback_start = signal_idx - int(pullback_bars)
    if pullback_start - 1 < 0:
        return MicroBurstSignalResult(None, "trend_micro_burst_context_insufficient")

    impulse_anchor = rates[pullback_start - 1]
    pullback = list(rates[pullback_start:signal_idx])
    last_closed = rates[signal_idx]
    if len(pullback) < int(pullback_bars):
        return MicroBurstSignalResult(None, "trend_micro_burst_context_insufficient")

    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high_price = _price(last_closed, "high")
    low_price = _price(last_closed, "low")
    body_ok = candle_body_ratio(last_closed) >= body_ratio_min
    avg_pullback_range = sum(candle_range(item) for item in pullback) / max(len(pullback), 1)
    range_ok = candle_range(last_closed) >= max(avg_pullback_range * range_multiple, 1e-10)

    pullback_high = max(_price(item, "high") for item in pullback)
    pullback_low = min(_price(item, "low") for item in pullback)
    anchor_open = _price(impulse_anchor, "open")
    anchor_close = _price(impulse_anchor, "close")
    anchor_high = _price(impulse_anchor, "high")
    anchor_low = _price(impulse_anchor, "low")
    bearish_pullback = sum(1 for item in pullback if _price(item, "close") < _price(item, "open"))
    bullish_pullback = sum(1 for item in pullback if _price(item, "close") > _price(item, "open"))

    buy_anchor_ok = anchor_close > anchor_open
    buy_pullback_ok = bearish_pullback >= max(1, len(pullback) // 2) and pullback_low >= anchor_open - buffer_price
    buy_break_ok = close_price > pullback_high + buffer_price and high_price > anchor_high + buffer_price

    if buy_anchor_ok and buy_pullback_ok and body_ok and range_ok and close_price > open_price and buy_break_ok:
        return MicroBurstSignalResult(
            SweepSignal(side="BUY", level=float(pullback_high), candle_time=int(last_closed["time"])),
            "trend_micro_burst_v2_buy_break",
        )

    sell_anchor_ok = anchor_close < anchor_open
    sell_pullback_ok = bullish_pullback >= max(1, len(pullback) // 2) and pullback_high <= anchor_open + buffer_price
    sell_break_ok = close_price < pullback_low - buffer_price and low_price < anchor_low - buffer_price

    if sell_anchor_ok and sell_pullback_ok and body_ok and range_ok and close_price < open_price and sell_break_ok:
        return MicroBurstSignalResult(
            SweepSignal(side="SELL", level=float(pullback_low), candle_time=int(last_closed["time"])),
            "trend_micro_burst_v2_sell_break",
        )

    return MicroBurstSignalResult(None, "trend_micro_burst_v2_wait_break")


