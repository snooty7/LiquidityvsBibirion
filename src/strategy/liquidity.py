from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional, Sequence

from src.strategy.filters import ema


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
    penetration_ratio: float = 0.0
    range_ratio: float = 0.0
    quality_score: float = 0.0


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


@dataclass(frozen=True)
class M1PatternSignalResult:
    signal: Optional[SweepSignal]
    note: str
    reference_high: float = 0.0
    reference_low: float = 0.0


@dataclass(frozen=True)
class TrendRetestReclaimSignalResult:
    signal: Optional[SweepSignal]
    note: str
    stop_price: float = 0.0
    target_price: float = 0.0
    tp_r_multiple: float = 0.0
    risk_pct_override: float = 0.0
    bias_note: str = ""
    breakout_level: float = 0.0
    sweep_level: float = 0.0
    retest_zone_low: float = 0.0
    retest_zone_high: float = 0.0
    atr_trigger: float = 0.0
    adx_bias: float = 0.0
    adx_setup: float = 0.0
    volume_ratio: float = 0.0


def _price(bar: object, field: str) -> float:
    if isinstance(bar, dict):
        return float(bar[field])
    return float(bar[field])


def _number(bar: object, field: str, default: float = 0.0) -> float:
    try:
        if isinstance(bar, dict):
            value = bar.get(field, default)
        else:
            value = bar[field]
    except Exception:
        value = default
    return float(value or default)


def candle_range(candle: object) -> float:
    return max(_price(candle, "high") - _price(candle, "low"), 1e-10)


def candle_body_ratio(candle: object) -> float:
    return abs(_price(candle, "close") - _price(candle, "open")) / candle_range(candle)


def _volume(bar: object) -> float:
    real_volume = _number(bar, "real_volume", 0.0)
    if real_volume > 0:
        return real_volume
    return _number(bar, "tick_volume", 0.0)


def _atr_series(rates: Sequence[object], period: int) -> list[float]:
    rows = list(rates)
    if not rows:
        return []
    if period <= 1:
        return [candle_range(item) for item in rows]

    true_ranges: list[float] = []
    prev_close = _price(rows[0], "close")
    for item in rows:
        high = _price(item, "high")
        low = _price(item, "low")
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = _price(item, "close")

    result: list[float] = []
    running = 0.0
    for idx, tr in enumerate(true_ranges):
        if idx == 0:
            running = tr
        elif idx < period:
            running = ((running * idx) + tr) / float(idx + 1)
        else:
            running = ((running * (period - 1)) + tr) / float(period)
        result.append(float(running))
    return result


def _adx_value(rates: Sequence[object], period: int) -> float:
    rows = list(rates)
    if len(rows) < max(5, period + 2):
        return 0.0

    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    true_ranges: list[float] = [candle_range(rows[0])]

    for current, previous in zip(rows[1:], rows[:-1]):
        up_move = _price(current, "high") - _price(previous, "high")
        down_move = _price(previous, "low") - _price(current, "low")
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        prev_close = _price(previous, "close")
        true_ranges.append(
            max(
                _price(current, "high") - _price(current, "low"),
                abs(_price(current, "high") - prev_close),
                abs(_price(current, "low") - prev_close),
            )
        )

    smoothed_tr = true_ranges[0]
    smoothed_plus = plus_dm[0]
    smoothed_minus = minus_dm[0]
    dx_values: list[float] = []
    for idx in range(1, len(rows)):
        if idx <= period:
            smoothed_tr += true_ranges[idx]
            smoothed_plus += plus_dm[idx]
            smoothed_minus += minus_dm[idx]
        else:
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[idx]
            smoothed_plus = smoothed_plus - (smoothed_plus / period) + plus_dm[idx]
            smoothed_minus = smoothed_minus - (smoothed_minus / period) + minus_dm[idx]

        if idx < period:
            continue
        plus_di = 100.0 * smoothed_plus / max(smoothed_tr, 1e-10)
        minus_di = 100.0 * smoothed_minus / max(smoothed_tr, 1e-10)
        dx = 100.0 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-10)
        dx_values.append(float(dx))

    if not dx_values:
        return 0.0

    adx = dx_values[0]
    for value in dx_values[1:]:
        adx = ((adx * (period - 1)) + value) / float(period)
    return float(adx)


def _average_overlap_ratio(rates: Sequence[object]) -> float:
    rows = list(rates)
    if len(rows) < 2:
        return 0.0

    realized: list[float] = []
    for left, right in zip(rows[:-1], rows[1:]):
        overlap = max(
            0.0,
            min(_price(left, "high"), _price(right, "high")) - max(_price(left, "low"), _price(right, "low")),
        )
        denominator = max(min(candle_range(left), candle_range(right)), 1e-10)
        realized.append(overlap / denominator)
    return float(sum(realized) / max(len(realized), 1))


def _collect_swings(rates: Sequence[object], pivot_len: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    rows = list(rates)
    if len(rows) < pivot_len * 2 + 1:
        return highs, lows

    for index in range(pivot_len, len(rows) - pivot_len):
        current_high = _price(rows[index], "high")
        current_low = _price(rows[index], "low")
        high_window = [_price(rows[idx], "high") for idx in range(index - pivot_len, index + pivot_len + 1)]
        low_window = [_price(rows[idx], "low") for idx in range(index - pivot_len, index + pivot_len + 1)]
        if current_high >= max(high_window):
            highs.append((index, current_high))
        if current_low <= min(low_window):
            lows.append((index, current_low))
    return highs, lows


def _structure_state(
    rates: Sequence[object],
    pivot_len: int,
) -> tuple[bool, bool, str, list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = _collect_swings(rates, pivot_len)
    if len(highs) < 2 or len(lows) < 2:
        return False, False, "structure_insufficient", highs, lows

    last_highs = highs[-2:]
    last_lows = lows[-2:]
    bullish = last_highs[-1][1] > last_highs[-2][1] and last_lows[-1][1] > last_lows[-2][1]
    bearish = last_highs[-1][1] < last_highs[-2][1] and last_lows[-1][1] < last_lows[-2][1]
    if bullish:
        note = "structure_hh_hl"
    elif bearish:
        note = "structure_ll_lh"
    else:
        note = "structure_mixed"
    return bullish, bearish, note, highs, lows


def _nearest_level(levels: Sequence[tuple[int, float]], *, above: Optional[float] = None, below: Optional[float] = None) -> float:
    candidates: list[float] = []
    for _, price in levels:
        if above is not None and price > above:
            candidates.append(float(price))
        if below is not None and price < below:
            candidates.append(float(price))
    if above is not None:
        return min(candidates) if candidates else 0.0
    if below is not None:
        return max(candidates) if candidates else 0.0
    return 0.0


def _scan_breakout_setup(
    setup_rates: Sequence[object],
    *,
    side: str,
    ema_mid_period: int,
    atr_period: int,
    adx_period: int,
    adx_threshold: float,
    volume_sma_period: int,
    breakout_volume_multiple: float,
    structure_pivot_len: int,
    setup_max_age_bars: int,
    overlap_lookback_bars: int,
    max_overlap_ratio: float,
) -> Optional[dict[str, float]]:
    rows = list(setup_rates)
    if len(rows) < max(volume_sma_period + 5, structure_pivot_len * 4 + 5):
        return None

    closes = [_price(item, "close") for item in rows]
    ema_mid = ema(closes, ema_mid_period)
    atr_values = _atr_series(rows, atr_period)
    oldest_idx = max(structure_pivot_len * 2 + 2, len(rows) - int(setup_max_age_bars))

    for index in range(len(rows) - 1, oldest_idx - 1, -1):
        bar = rows[index]
        prior = rows[:index]
        if len(prior) < max(volume_sma_period, structure_pivot_len * 2 + 1):
            continue

        highs, lows = _collect_swings(prior, structure_pivot_len)
        if side == "BUY":
            if not highs:
                continue
            breakout_level = float(highs[-1][1])
            breakout_ok = _price(bar, "close") > breakout_level
        else:
            if not lows:
                continue
            breakout_level = float(lows[-1][1])
            breakout_ok = _price(bar, "close") < breakout_level
        if not breakout_ok:
            continue

        volume_window = [_volume(item) for item in prior[-volume_sma_period:]]
        volume_sma = sum(volume_window) / max(len(volume_window), 1)
        volume_ratio = _volume(bar) / max(volume_sma, 1e-10)
        if volume_ratio < breakout_volume_multiple:
            continue

        adx_window = rows[max(0, index - max(adx_period * 3, overlap_lookback_bars + 2)) : index + 1]
        adx_value = _adx_value(adx_window, adx_period)
        overlap_window = rows[max(0, index - overlap_lookback_bars + 1) : index + 1]
        overlap_ratio = _average_overlap_ratio(overlap_window)
        if adx_value < adx_threshold and overlap_ratio > max_overlap_ratio:
            continue

        return {
            "breakout_level": breakout_level,
            "breakout_time": float(bar["time"]),
            "ema_mid": float(ema_mid[index]),
            "atr": float(atr_values[index]) if atr_values else 0.0,
            "adx": float(adx_value),
            "volume_ratio": float(volume_ratio),
        }
    return None


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
    required_range = max(avg_range * min_range_multiple, 1e-10)
    required_penetration = max(min_penetration_price, 1e-10)

    if signal.side == "BUY":
        penetration_price = max(0.0, float(signal.level) - _price(sweep_candle, "low"))
    else:
        penetration_price = max(0.0, _price(sweep_candle, "high") - float(signal.level))

    penetration_ratio = penetration_price / required_penetration
    range_ratio = sweep_range / required_range
    quality_score = min(penetration_ratio, range_ratio)

    if penetration_price < required_penetration:
        return SweepValidationResult(
            False,
            "sweep_penetration_too_small",
            avg_range=avg_range,
            sweep_range=sweep_range,
            penetration_price=penetration_price,
            penetration_ratio=penetration_ratio,
            range_ratio=range_ratio,
            quality_score=quality_score,
        )

    if sweep_range < required_range:
        return SweepValidationResult(
            False,
            "sweep_range_too_small",
            avg_range=avg_range,
            sweep_range=sweep_range,
            penetration_price=penetration_price,
            penetration_ratio=penetration_ratio,
            range_ratio=range_ratio,
            quality_score=quality_score,
        )

    return SweepValidationResult(
        True,
        "sweep_significant",
        avg_range=avg_range,
        sweep_range=sweep_range,
        penetration_price=penetration_price,
        penetration_ratio=penetration_ratio,
        range_ratio=range_ratio,
        quality_score=quality_score,
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


def detect_trend_day_acceleration_signal(
    rates: Sequence[object],
    *,
    pullback_bars: int,
    body_ratio_min: float,
    range_multiple: float,
    buffer_price: float,
) -> MicroBurstSignalResult:
    needed = max(5, int(pullback_bars) + 4)
    if len(rates) < needed:
        return MicroBurstSignalResult(None, "trend_day_accel_context_insufficient")

    signal_idx = len(rates) - 2
    pullback_start = signal_idx - int(pullback_bars)
    anchor_idx = pullback_start - 2
    if anchor_idx < 0:
        return MicroBurstSignalResult(None, "trend_day_accel_context_insufficient")

    anchors = list(rates[anchor_idx:pullback_start])
    pullback = list(rates[pullback_start:signal_idx])
    last_closed = rates[signal_idx]
    if len(anchors) < 2 or len(pullback) < int(pullback_bars):
        return MicroBurstSignalResult(None, "trend_day_accel_context_insufficient")

    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high_price = _price(last_closed, "high")
    low_price = _price(last_closed, "low")
    body_ok = candle_body_ratio(last_closed) >= body_ratio_min
    avg_pullback_range = sum(candle_range(item) for item in pullback) / max(len(pullback), 1)
    range_ok = candle_range(last_closed) >= max(avg_pullback_range * range_multiple, 1e-10)

    anchor_high = max(_price(item, "high") for item in anchors)
    anchor_low = min(_price(item, "low") for item in anchors)
    anchor_bullish = sum(1 for item in anchors if _price(item, "close") > _price(item, "open"))
    anchor_bearish = sum(1 for item in anchors if _price(item, "close") < _price(item, "open"))
    pullback_high = max(_price(item, "high") for item in pullback)
    pullback_low = min(_price(item, "low") for item in pullback)
    bearish_pullback = sum(1 for item in pullback if _price(item, "close") < _price(item, "open"))
    bullish_pullback = sum(1 for item in pullback if _price(item, "close") > _price(item, "open"))

    buy_anchor_ok = anchor_bullish >= max(1, len(anchors) // 2) and _price(anchors[-1], "close") >= anchor_high - buffer_price
    buy_pullback_ok = bearish_pullback >= max(1, len(pullback) // 2) and pullback_low >= anchor_low - buffer_price
    buy_break_ok = close_price > pullback_high + buffer_price and high_price > anchor_high + buffer_price
    if buy_anchor_ok and buy_pullback_ok and body_ok and range_ok and close_price > open_price and buy_break_ok:
        return MicroBurstSignalResult(
            SweepSignal(side="BUY", level=float(pullback_high), candle_time=int(last_closed["time"])),
            "trend_day_accel_buy_break",
        )

    sell_anchor_ok = anchor_bearish >= max(1, len(anchors) // 2) and _price(anchors[-1], "close") <= anchor_low + buffer_price
    sell_pullback_ok = bullish_pullback >= max(1, len(pullback) // 2) and pullback_high <= anchor_high + buffer_price
    sell_break_ok = close_price < pullback_low - buffer_price and low_price < anchor_low - buffer_price
    if sell_anchor_ok and sell_pullback_ok and body_ok and range_ok and close_price < open_price and sell_break_ok:
        return MicroBurstSignalResult(
            SweepSignal(side="SELL", level=float(pullback_low), candle_time=int(last_closed["time"])),
            "trend_day_accel_sell_break",
        )

    return MicroBurstSignalResult(None, "trend_day_accel_wait_break")


def detect_volume_sweep_reclaim_signal(
    rates: Sequence[object],
    *,
    lookback_bars: int,
    volume_sma_period: int,
    volume_multiple: float,
    ema_period: int,
    body_ratio_min: float,
    buffer_price: float,
    stop_padding_price: float,
    tp_distance_price: float,
) -> TrendRetestReclaimSignalResult:
    rows = list(rates)
    needed = max(int(lookback_bars) + 2, int(volume_sma_period) + 2, int(ema_period) + 2)
    if len(rows) < needed:
        return TrendRetestReclaimSignalResult(None, "volume_sweep_context_insufficient")

    closed = rows[:-1]
    if len(closed) < needed - 1:
        return TrendRetestReclaimSignalResult(None, "volume_sweep_context_insufficient")

    last_closed = closed[-1]
    prior = closed[-(int(lookback_bars) + 1) : -1]
    volume_prior = closed[-(int(volume_sma_period) + 1) : -1]
    if len(prior) < int(lookback_bars) or len(volume_prior) < int(volume_sma_period):
        return TrendRetestReclaimSignalResult(None, "volume_sweep_context_insufficient")

    volume_sma = sum(_volume(item) for item in volume_prior) / max(len(volume_prior), 1)
    volume_ratio = _volume(last_closed) / max(volume_sma, 1e-10)
    if volume_ratio < float(volume_multiple):
        return TrendRetestReclaimSignalResult(
            None,
            "volume_sweep_wait_volume",
            volume_ratio=float(volume_ratio),
        )

    body_ratio = candle_body_ratio(last_closed)
    if body_ratio < float(body_ratio_min):
        return TrendRetestReclaimSignalResult(
            None,
            "volume_sweep_body_too_small",
            volume_ratio=float(volume_ratio),
        )

    closes = [_price(item, "close") for item in closed]
    ema_values = ema(closes, int(ema_period))
    ema_value = float(ema_values[-1])
    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high_price = _price(last_closed, "high")
    low_price = _price(last_closed, "low")
    prior_high = max(_price(item, "high") for item in prior)
    prior_low = min(_price(item, "low") for item in prior)

    # The tested edge was not "volume follows trend"; it was liquidity grab against EMA50.
    buy_reclaim = (
        close_price < ema_value
        and low_price < prior_low - buffer_price
        and close_price > prior_low
        and close_price > open_price
    )
    if buy_reclaim:
        stop_price = float(low_price - stop_padding_price)
        target_price = float(close_price + tp_distance_price)
        return TrendRetestReclaimSignalResult(
            SweepSignal(side="BUY", level=float(prior_low), candle_time=int(last_closed["time"])),
            "volume_sweep_reclaim_buy",
            stop_price=stop_price,
            target_price=target_price,
            tp_r_multiple=0.0,
            sweep_level=float(prior_low),
            volume_ratio=float(volume_ratio),
        )

    sell_reclaim = (
        close_price > ema_value
        and high_price > prior_high + buffer_price
        and close_price < prior_high
        and close_price < open_price
    )
    if sell_reclaim:
        stop_price = float(high_price + stop_padding_price)
        target_price = float(close_price - tp_distance_price)
        return TrendRetestReclaimSignalResult(
            SweepSignal(side="SELL", level=float(prior_high), candle_time=int(last_closed["time"])),
            "volume_sweep_reclaim_sell",
            stop_price=stop_price,
            target_price=target_price,
            tp_r_multiple=0.0,
            sweep_level=float(prior_high),
            volume_ratio=float(volume_ratio),
        )

    return TrendRetestReclaimSignalResult(
        None,
        "volume_sweep_wait_reclaim",
        volume_ratio=float(volume_ratio),
    )


def detect_two_candle_momentum_signal(
    rates: Sequence[object],
    *,
    body_ratio_min: float,
    buffer_price: float,
) -> M1PatternSignalResult:
    if len(rates) < 4:
        return M1PatternSignalResult(None, "two_candle_context_insufficient")

    first = rates[-3]
    second = rates[-2]
    first_open = _price(first, "open")
    first_close = _price(first, "close")
    first_high = _price(first, "high")
    first_low = _price(first, "low")
    second_open = _price(second, "open")
    second_close = _price(second, "close")

    first_bull = first_close > first_open and candle_body_ratio(first) >= body_ratio_min
    second_bull = second_close > second_open and candle_body_ratio(second) >= body_ratio_min
    if first_bull and second_bull and second_close > first_high + buffer_price:
        return M1PatternSignalResult(
            SweepSignal(side="BUY", level=float(first_high), candle_time=int(second["time"])),
            "two_candle_momentum_buy",
            reference_high=float(first_high),
            reference_low=float(first_low),
        )

    first_bear = first_close < first_open and candle_body_ratio(first) >= body_ratio_min
    second_bear = second_close < second_open and candle_body_ratio(second) >= body_ratio_min
    if first_bear and second_bear and second_close < first_low - buffer_price:
        return M1PatternSignalResult(
            SweepSignal(side="SELL", level=float(first_low), candle_time=int(second["time"])),
            "two_candle_momentum_sell",
            reference_high=float(first_high),
            reference_low=float(first_low),
        )

    return M1PatternSignalResult(
        None,
        "two_candle_momentum_wait",
        reference_high=float(first_high),
        reference_low=float(first_low),
    )


def detect_opening_range_breakout_signal(
    rates: Sequence[object],
    *,
    session_start_utc: str,
    open_range_minutes: int,
    watch_minutes: int,
    buffer_price: float,
    body_ratio_min: float,
) -> SessionOpenScalpSignalResult:
    if len(rates) < 5:
        return SessionOpenScalpSignalResult(None, "orb_context_insufficient")

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
        return SessionOpenScalpSignalResult(None, "orb_before_session")

    open_range_end = session_start.timestamp() + int(open_range_minutes) * 60
    watch_end = session_start.timestamp() + int(watch_minutes) * 60
    last_closed_ts = int(last_closed["time"])
    if last_closed_ts < int(open_range_end):
        return SessionOpenScalpSignalResult(None, "orb_opening_range_incomplete")
    if last_closed_ts >= int(watch_end):
        return SessionOpenScalpSignalResult(None, "orb_outside_watch_window")

    opening_range = [
        bar for bar in rates[:-1] if int(session_start.timestamp()) <= int(bar["time"]) < int(open_range_end)
    ]
    if len(opening_range) < max(2, int(open_range_minutes // 2)):
        return SessionOpenScalpSignalResult(None, "orb_opening_range_missing")

    or_high = max(_price(bar, "high") for bar in opening_range)
    or_low = min(_price(bar, "low") for bar in opening_range)
    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    body_ratio = candle_body_ratio(last_closed)

    if close_price > or_high + buffer_price and close_price > open_price and body_ratio >= body_ratio_min:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="BUY", level=float(or_high), candle_time=int(last_closed["time"])),
            "orb_buy_breakout",
            opening_range_high=float(or_high),
            opening_range_low=float(or_low),
        )

    if close_price < or_low - buffer_price and close_price < open_price and body_ratio >= body_ratio_min:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="SELL", level=float(or_low), candle_time=int(last_closed["time"])),
            "orb_sell_breakout",
            opening_range_high=float(or_high),
            opening_range_low=float(or_low),
        )

    return SessionOpenScalpSignalResult(
        None,
        "orb_wait_breakout",
        opening_range_high=float(or_high),
        opening_range_low=float(or_low),
    )


def detect_opening_range_breakout_v2_signal(
    rates: Sequence[object],
    *,
    session_start_utc: str,
    open_range_minutes: int,
    watch_minutes: int,
    buffer_price: float,
    body_ratio_min: float,
    pullback_bars: int,
    range_multiple: float,
) -> SessionOpenScalpSignalResult:
    needed = max(6, int(pullback_bars) + 5)
    if len(rates) < needed:
        return SessionOpenScalpSignalResult(None, "orb_v2_context_insufficient")

    signal_idx = len(rates) - 2
    last_closed = rates[signal_idx]
    last_dt = datetime.fromtimestamp(int(last_closed["time"]), tz=timezone.utc)
    session_minutes = _parse_hhmm_to_minutes(session_start_utc)
    session_start = last_dt.replace(
        hour=session_minutes // 60,
        minute=session_minutes % 60,
        second=0,
        microsecond=0,
    )
    if last_dt < session_start:
        return SessionOpenScalpSignalResult(None, "orb_v2_before_session")

    open_range_end = session_start.timestamp() + int(open_range_minutes) * 60
    watch_end = session_start.timestamp() + int(watch_minutes) * 60
    last_closed_ts = int(last_closed["time"])
    if last_closed_ts < int(open_range_end):
        return SessionOpenScalpSignalResult(None, "orb_v2_opening_range_incomplete")
    if last_closed_ts >= int(watch_end):
        return SessionOpenScalpSignalResult(None, "orb_v2_outside_watch_window")

    opening_range = [
        bar for bar in rates[:-1] if int(session_start.timestamp()) <= int(bar["time"]) < int(open_range_end)
    ]
    if len(opening_range) < max(2, int(open_range_minutes // 2)):
        return SessionOpenScalpSignalResult(None, "orb_v2_opening_range_missing")

    or_high = max(_price(bar, "high") for bar in opening_range)
    or_low = min(_price(bar, "low") for bar in opening_range)

    pullback_start = signal_idx - int(pullback_bars)
    breakout_idx = pullback_start - 1
    if breakout_idx < 0:
        return SessionOpenScalpSignalResult(None, "orb_v2_context_insufficient")

    breakout_anchor = rates[breakout_idx]
    pullback = list(rates[pullback_start:signal_idx])
    if len(pullback) < int(pullback_bars):
        return SessionOpenScalpSignalResult(None, "orb_v2_context_insufficient")

    breakout_close = _price(breakout_anchor, "close")
    breakout_open = _price(breakout_anchor, "open")
    breakout_high = _price(breakout_anchor, "high")
    breakout_low = _price(breakout_anchor, "low")
    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high_price = _price(last_closed, "high")
    low_price = _price(last_closed, "low")
    body_ok = candle_body_ratio(last_closed) >= body_ratio_min
    avg_pullback_range = sum(candle_range(item) for item in pullback) / max(len(pullback), 1)
    range_ok = candle_range(last_closed) >= max(avg_pullback_range * range_multiple, 1e-10)

    pullback_high = max(_price(item, "high") for item in pullback)
    pullback_low = min(_price(item, "low") for item in pullback)
    bearish_pullback = sum(1 for item in pullback if _price(item, "close") < _price(item, "open"))
    bullish_pullback = sum(1 for item in pullback if _price(item, "close") > _price(item, "open"))

    buy_anchor_ok = breakout_close > breakout_open and breakout_close > or_high + buffer_price
    buy_pullback_ok = bearish_pullback >= max(1, len(pullback) // 2) and pullback_low >= or_high - buffer_price
    buy_break_ok = close_price > pullback_high + buffer_price and high_price > breakout_high + buffer_price
    if buy_anchor_ok and buy_pullback_ok and body_ok and range_ok and close_price > open_price and buy_break_ok:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="BUY", level=float(or_high), candle_time=int(last_closed["time"])),
            "orb_v2_buy_reacceleration",
            opening_range_high=float(or_high),
            opening_range_low=float(or_low),
        )

    sell_anchor_ok = breakout_close < breakout_open and breakout_close < or_low - buffer_price
    sell_pullback_ok = bullish_pullback >= max(1, len(pullback) // 2) and pullback_high <= or_low + buffer_price
    sell_break_ok = close_price < pullback_low - buffer_price and low_price < breakout_low - buffer_price
    if sell_anchor_ok and sell_pullback_ok and body_ok and range_ok and close_price < open_price and sell_break_ok:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="SELL", level=float(or_low), candle_time=int(last_closed["time"])),
            "orb_v2_sell_reacceleration",
            opening_range_high=float(or_high),
            opening_range_low=float(or_low),
        )

    return SessionOpenScalpSignalResult(
        None,
        "orb_v2_wait_reacceleration",
        opening_range_high=float(or_high),
        opening_range_low=float(or_low),
    )


def detect_overreaction_fade_signal(
    rates: Sequence[object],
    *,
    lookback_bars: int,
    range_multiple: float,
    body_ratio_min: float,
    buffer_price: float,
) -> M1PatternSignalResult:
    if len(rates) < max(5, lookback_bars + 3):
        return M1PatternSignalResult(None, "overreaction_context_insufficient")

    last_closed = rates[-2]
    prior = list(rates[-(int(lookback_bars) + 2) : -2])
    if len(prior) < int(lookback_bars):
        return M1PatternSignalResult(None, "overreaction_context_insufficient")

    avg_range = sum(candle_range(item) for item in prior) / max(len(prior), 1)
    last_range = candle_range(last_closed)
    if last_range < max(avg_range * range_multiple, 1e-10):
        return M1PatternSignalResult(None, "overreaction_wait_range")

    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high_price = _price(last_closed, "high")
    low_price = _price(last_closed, "low")
    prior_high = max(_price(item, "high") for item in prior)
    prior_low = min(_price(item, "low") for item in prior)
    body_ratio = candle_body_ratio(last_closed)
    if body_ratio < body_ratio_min:
        return M1PatternSignalResult(
            None,
            "overreaction_wait_body",
            reference_high=float(prior_high),
            reference_low=float(prior_low),
        )

    if close_price > open_price and high_price > prior_high + buffer_price:
        return M1PatternSignalResult(
            SweepSignal(side="SELL", level=float(prior_high), candle_time=int(last_closed["time"])),
            "overreaction_fade_sell",
            reference_high=float(prior_high),
            reference_low=float(prior_low),
        )

    if close_price < open_price and low_price < prior_low - buffer_price:
        return M1PatternSignalResult(
            SweepSignal(side="BUY", level=float(prior_low), candle_time=int(last_closed["time"])),
            "overreaction_fade_buy",
            reference_high=float(prior_high),
            reference_low=float(prior_low),
        )

    return M1PatternSignalResult(
        None,
        "overreaction_wait_extreme",
        reference_high=float(prior_high),
        reference_low=float(prior_low),
    )


def detect_ny_micro_pullback_drift_signal(
    rates: Sequence[object],
    *,
    pullback_bars: int,
    drift_lookback_bars: int,
    body_ratio_min: float,
    buffer_price: float,
) -> M1PatternSignalResult:
    needed = max(8, int(drift_lookback_bars) + int(pullback_bars) + 2)
    if len(rates) < needed:
        return M1PatternSignalResult(None, "micro_pullback_drift_context_insufficient")

    signal_idx = len(rates) - 2
    last_closed = rates[signal_idx]
    drift_slice = list(rates[signal_idx - int(drift_lookback_bars) : signal_idx])
    if len(drift_slice) < int(drift_lookback_bars):
        return M1PatternSignalResult(None, "micro_pullback_drift_context_insufficient")

    drift_up = sum(1 for item in drift_slice if _price(item, "close") > _price(item, "open"))
    drift_down = sum(1 for item in drift_slice if _price(item, "close") < _price(item, "open"))
    drift_high = max(_price(item, "high") for item in drift_slice)
    drift_low = min(_price(item, "low") for item in drift_slice)

    pullback = list(rates[signal_idx - int(pullback_bars) : signal_idx])
    if len(pullback) < int(pullback_bars):
        return M1PatternSignalResult(None, "micro_pullback_drift_context_insufficient")

    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high_price = _price(last_closed, "high")
    low_price = _price(last_closed, "low")
    body_ok = candle_body_ratio(last_closed) >= body_ratio_min
    pullback_high = max(_price(item, "high") for item in pullback)
    pullback_low = min(_price(item, "low") for item in pullback)
    bearish_pullback = sum(1 for item in pullback if _price(item, "close") < _price(item, "open"))
    bullish_pullback = sum(1 for item in pullback if _price(item, "close") > _price(item, "open"))

    if (
        drift_up >= max(2, len(drift_slice) // 2)
        and bearish_pullback >= max(1, len(pullback) // 2)
        and body_ok
        and close_price > open_price
        and close_price > pullback_high + buffer_price
        and high_price >= drift_high - buffer_price
    ):
        return M1PatternSignalResult(
            SweepSignal(side="BUY", level=float(pullback_high), candle_time=int(last_closed["time"])),
            "micro_pullback_drift_buy",
            reference_high=float(drift_high),
            reference_low=float(drift_low),
        )

    if (
        drift_down >= max(2, len(drift_slice) // 2)
        and bullish_pullback >= max(1, len(pullback) // 2)
        and body_ok
        and close_price < open_price
        and close_price < pullback_low - buffer_price
        and low_price <= drift_low + buffer_price
    ):
        return M1PatternSignalResult(
            SweepSignal(side="SELL", level=float(pullback_low), candle_time=int(last_closed["time"])),
            "micro_pullback_drift_sell",
            reference_high=float(drift_high),
            reference_low=float(drift_low),
        )

    return M1PatternSignalResult(
        None,
        "micro_pullback_drift_wait",
        reference_high=float(drift_high),
        reference_low=float(drift_low),
    )


def detect_ny_reclaim_continuation_signal(
    rates: Sequence[object],
    *,
    session_start_utc: str,
    open_range_minutes: int,
    watch_minutes: int,
    buffer_price: float,
    body_ratio_min: float,
    pullback_bars: int,
    range_multiple: float,
    reclaim_tolerance_price: float,
) -> SessionOpenScalpSignalResult:
    needed = max(8, int(pullback_bars) + 6)
    if len(rates) < needed:
        return SessionOpenScalpSignalResult(None, "ny_reclaim_context_insufficient")

    signal_idx = len(rates) - 2
    last_closed = rates[signal_idx]
    last_dt = datetime.fromtimestamp(int(last_closed["time"]), tz=timezone.utc)
    session_minutes = _parse_hhmm_to_minutes(session_start_utc)
    session_start = last_dt.replace(
        hour=session_minutes // 60,
        minute=session_minutes % 60,
        second=0,
        microsecond=0,
    )
    if last_dt < session_start:
        return SessionOpenScalpSignalResult(None, "ny_reclaim_before_session")

    open_range_end = session_start.timestamp() + int(open_range_minutes) * 60
    watch_end = session_start.timestamp() + int(watch_minutes) * 60
    last_closed_ts = int(last_closed["time"])
    if last_closed_ts < int(open_range_end):
        return SessionOpenScalpSignalResult(None, "ny_reclaim_opening_range_incomplete")
    if last_closed_ts >= int(watch_end):
        return SessionOpenScalpSignalResult(None, "ny_reclaim_outside_watch_window")

    opening_range = [
        bar for bar in rates[:-1] if int(session_start.timestamp()) <= int(bar["time"]) < int(open_range_end)
    ]
    if len(opening_range) < max(2, int(open_range_minutes // 2)):
        return SessionOpenScalpSignalResult(None, "ny_reclaim_opening_range_missing")

    or_high = max(_price(bar, "high") for bar in opening_range)
    or_low = min(_price(bar, "low") for bar in opening_range)

    pullback_start = signal_idx - int(pullback_bars)
    anchor_idx = pullback_start - 1
    if anchor_idx < 0:
        return SessionOpenScalpSignalResult(None, "ny_reclaim_context_insufficient")

    breakout_anchor = rates[anchor_idx]
    pullback = list(rates[pullback_start:signal_idx])
    if len(pullback) < int(pullback_bars):
        return SessionOpenScalpSignalResult(None, "ny_reclaim_context_insufficient")

    breakout_close = _price(breakout_anchor, "close")
    breakout_open = _price(breakout_anchor, "open")
    breakout_high = _price(breakout_anchor, "high")
    breakout_low = _price(breakout_anchor, "low")
    close_price = _price(last_closed, "close")
    open_price = _price(last_closed, "open")
    high_price = _price(last_closed, "high")
    low_price = _price(last_closed, "low")
    body_ok = candle_body_ratio(last_closed) >= body_ratio_min
    avg_pullback_range = sum(candle_range(item) for item in pullback) / max(len(pullback), 1)
    range_ok = candle_range(last_closed) >= max(avg_pullback_range * range_multiple, 1e-10)

    pullback_high = max(_price(item, "high") for item in pullback)
    pullback_low = min(_price(item, "low") for item in pullback)
    bearish_pullback = sum(1 for item in pullback if _price(item, "close") < _price(item, "open"))
    bullish_pullback = sum(1 for item in pullback if _price(item, "close") > _price(item, "open"))

    buy_anchor_ok = breakout_close > breakout_open and breakout_close > or_high + buffer_price
    buy_pullback_ok = (
        bearish_pullback >= max(1, len(pullback) // 2)
        and pullback_low <= or_high + reclaim_tolerance_price
        and pullback_low >= or_high - reclaim_tolerance_price
        and pullback_high <= breakout_high + buffer_price
    )
    buy_reclaim_ok = (
        close_price > open_price
        and close_price > or_high + buffer_price
        and close_price > pullback_high + buffer_price
        and high_price >= breakout_high - buffer_price
    )
    if buy_anchor_ok and buy_pullback_ok and body_ok and range_ok and buy_reclaim_ok:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="BUY", level=float(or_high), candle_time=int(last_closed["time"])),
            "ny_reclaim_buy",
            opening_range_high=float(or_high),
            opening_range_low=float(or_low),
        )

    sell_anchor_ok = breakout_close < breakout_open and breakout_close < or_low - buffer_price
    sell_pullback_ok = (
        bullish_pullback >= max(1, len(pullback) // 2)
        and pullback_high >= or_low - reclaim_tolerance_price
        and pullback_high <= or_low + reclaim_tolerance_price
        and pullback_low >= breakout_low - buffer_price
    )
    sell_reclaim_ok = (
        close_price < open_price
        and close_price < or_low - buffer_price
        and close_price < pullback_low - buffer_price
        and low_price <= breakout_low + buffer_price
    )
    if sell_anchor_ok and sell_pullback_ok and body_ok and range_ok and sell_reclaim_ok:
        return SessionOpenScalpSignalResult(
            SweepSignal(side="SELL", level=float(or_low), candle_time=int(last_closed["time"])),
            "ny_reclaim_sell",
            opening_range_high=float(or_high),
            opening_range_low=float(or_low),
        )

    return SessionOpenScalpSignalResult(
        None,
        "ny_reclaim_wait",
        opening_range_high=float(or_high),
        opening_range_low=float(or_low),
    )


def detect_btc_mtf_trend_retest_reclaim_signal(
    trigger_rates: Sequence[object],
    setup_rates: Sequence[object],
    bias_rates: Sequence[object],
    *,
    ema_fast_period: int,
    ema_mid_period: int,
    ema_slow_period: int,
    atr_period: int,
    adx_period: int,
    adx_threshold: float,
    volume_sma_period: int,
    breakout_volume_multiple: float,
    structure_pivot_len: int,
    setup_max_age_bars: int,
    trigger_sweep_lookback_bars: int,
    retest_zone_atr_multiple: float,
    reclaim_max_atr_multiple: float,
    stop_atr_multiple: float,
    entry_max_atr_multiple: float,
    htf_target_min_r: float,
    overlap_lookback_bars: int,
    max_overlap_ratio: float,
    base_risk_pct: float,
    weekend_risk_multiplier: float,
) -> TrendRetestReclaimSignalResult:
    trigger_rows = list(trigger_rates)
    setup_rows = list(setup_rates)
    bias_rows = list(bias_rates)
    if len(trigger_rows) < max(trigger_sweep_lookback_bars + 4, atr_period + 4):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_trigger_context_insufficient")
    if len(setup_rows) < max(volume_sma_period + 5, ema_slow_period + 5):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_setup_context_insufficient")
    if len(bias_rows) < max(ema_slow_period + 5, structure_pivot_len * 4 + 5):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_bias_context_insufficient")

    trigger_closed = trigger_rows[:-1]
    setup_closed = setup_rows[:-1]
    bias_closed = bias_rows[:-1]
    if len(trigger_closed) < max(trigger_sweep_lookback_bars + 3, atr_period + 3):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_trigger_context_insufficient")
    if len(setup_closed) < max(volume_sma_period + 3, ema_slow_period + 3):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_setup_context_insufficient")
    if len(bias_closed) < max(ema_slow_period + 3, structure_pivot_len * 4 + 3):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_bias_context_insufficient")

    bias_closes = [_price(item, "close") for item in bias_closed]
    bias_ema_fast = ema(bias_closes, ema_fast_period)
    bias_ema_mid = ema(bias_closes, ema_mid_period)
    bias_ema_slow = ema(bias_closes, ema_slow_period)
    last_bias = bias_closed[-1]
    last_bias_close = _price(last_bias, "close")
    adx_bias = _adx_value(bias_closed, adx_period)
    ema_mid_slope = bias_ema_mid[-1] - bias_ema_mid[-2]
    bullish_structure, bearish_structure, structure_note, bias_highs, bias_lows = _structure_state(
        bias_closed, structure_pivot_len
    )

    bullish_bias = (
        bias_ema_fast[-1] > bias_ema_mid[-1] > bias_ema_slow[-1]
        and last_bias_close > bias_ema_mid[-1]
        and bullish_structure
        and (adx_bias > adx_threshold or ema_mid_slope > 0)
    )
    bearish_bias = (
        bias_ema_fast[-1] < bias_ema_mid[-1] < bias_ema_slow[-1]
        and last_bias_close < bias_ema_mid[-1]
        and bearish_structure
        and (adx_bias > adx_threshold or ema_mid_slope < 0)
    )
    if not bullish_bias and not bearish_bias:
        return TrendRetestReclaimSignalResult(
            None,
            "btc_mtf_bias_neutral",
            bias_note=(
                f"{structure_note} close={last_bias_close:.2f} "
                f"ema9={bias_ema_fast[-1]:.2f} ema21={bias_ema_mid[-1]:.2f} ema50={bias_ema_slow[-1]:.2f} "
                f"adx={adx_bias:.2f} slope={ema_mid_slope:.5f}"
            ),
            adx_bias=float(adx_bias),
        )

    side = "BUY" if bullish_bias else "SELL"
    setup_breakout = _scan_breakout_setup(
        setup_closed,
        side=side,
        ema_mid_period=ema_mid_period,
        atr_period=atr_period,
        adx_period=adx_period,
        adx_threshold=adx_threshold,
        volume_sma_period=volume_sma_period,
        breakout_volume_multiple=breakout_volume_multiple,
        structure_pivot_len=structure_pivot_len,
        setup_max_age_bars=setup_max_age_bars,
        overlap_lookback_bars=overlap_lookback_bars,
        max_overlap_ratio=max_overlap_ratio,
    )
    if setup_breakout is None:
        return TrendRetestReclaimSignalResult(None, "btc_mtf_wait_setup_breakout", adx_bias=float(adx_bias))

    last_trigger = trigger_closed[-1]
    if int(last_trigger["time"]) <= int(setup_breakout["breakout_time"]):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_wait_post_breakout_retest", adx_bias=float(adx_bias))

    setup_closes = [_price(item, "close") for item in setup_closed]
    setup_ema_mid = ema(setup_closes, ema_mid_period)
    setup_ema_value = float(setup_ema_mid[-1])
    zone_padding = max(float(setup_breakout["atr"]) * retest_zone_atr_multiple, 1e-10)
    retest_zone_low = min(float(setup_breakout["breakout_level"]), setup_ema_value) - zone_padding
    retest_zone_high = max(float(setup_breakout["breakout_level"]), setup_ema_value) + zone_padding
    if _price(last_trigger, "high") < retest_zone_low or _price(last_trigger, "low") > retest_zone_high:
        return TrendRetestReclaimSignalResult(
            None,
            "btc_mtf_wait_retest_zone",
            adx_bias=float(adx_bias),
            adx_setup=float(setup_breakout["adx"]),
            volume_ratio=float(setup_breakout["volume_ratio"]),
            breakout_level=float(setup_breakout["breakout_level"]),
            retest_zone_low=float(retest_zone_low),
            retest_zone_high=float(retest_zone_high),
        )

    trigger_atr_values = _atr_series(trigger_closed, atr_period)
    trigger_atr = float(trigger_atr_values[-1]) if trigger_atr_values else 0.0
    if trigger_atr <= 0:
        return TrendRetestReclaimSignalResult(None, "btc_mtf_trigger_atr_missing")

    reclaim_range = candle_range(last_trigger)
    if reclaim_range > trigger_atr * reclaim_max_atr_multiple:
        return TrendRetestReclaimSignalResult(
            None,
            "btc_mtf_reclaim_too_large",
            adx_bias=float(adx_bias),
            adx_setup=float(setup_breakout["adx"]),
            volume_ratio=float(setup_breakout["volume_ratio"]),
            breakout_level=float(setup_breakout["breakout_level"]),
            retest_zone_low=float(retest_zone_low),
            retest_zone_high=float(retest_zone_high),
            atr_trigger=float(trigger_atr),
        )

    trigger_history = trigger_closed[-(int(trigger_sweep_lookback_bars) + 1) : -1]
    if len(trigger_history) < int(trigger_sweep_lookback_bars):
        return TrendRetestReclaimSignalResult(None, "btc_mtf_trigger_context_insufficient")

    entry_price = _price(last_trigger, "close")
    weekend_risk = float(base_risk_pct)
    trigger_dt = datetime.fromtimestamp(int(last_trigger["time"]), tz=timezone.utc)
    if trigger_dt.weekday() >= 5 and weekend_risk_multiplier != 1.0:
        weekend_risk = float(base_risk_pct * weekend_risk_multiplier)

    if side == "BUY":
        sweep_level = min(_price(item, "low") for item in trigger_history)
        reclaim_ok = (
            _price(last_trigger, "low") < sweep_level
            and entry_price > sweep_level
            and entry_price > _price(last_trigger, "open")
        )
        if not reclaim_ok:
            return TrendRetestReclaimSignalResult(
                None,
                "btc_mtf_wait_buy_reclaim",
                adx_bias=float(adx_bias),
                adx_setup=float(setup_breakout["adx"]),
                volume_ratio=float(setup_breakout["volume_ratio"]),
                breakout_level=float(setup_breakout["breakout_level"]),
                sweep_level=float(sweep_level),
                retest_zone_low=float(retest_zone_low),
                retest_zone_high=float(retest_zone_high),
                atr_trigger=float(trigger_atr),
            )
        stop_price = _price(last_trigger, "low") - (trigger_atr * stop_atr_multiple)
        risk_distance = entry_price - stop_price
        nearest_htf_level = _nearest_level(bias_highs, above=entry_price)
    else:
        sweep_level = max(_price(item, "high") for item in trigger_history)
        reclaim_ok = (
            _price(last_trigger, "high") > sweep_level
            and entry_price < sweep_level
            and entry_price < _price(last_trigger, "open")
        )
        if not reclaim_ok:
            return TrendRetestReclaimSignalResult(
                None,
                "btc_mtf_wait_sell_reclaim",
                adx_bias=float(adx_bias),
                adx_setup=float(setup_breakout["adx"]),
                volume_ratio=float(setup_breakout["volume_ratio"]),
                breakout_level=float(setup_breakout["breakout_level"]),
                sweep_level=float(sweep_level),
                retest_zone_low=float(retest_zone_low),
                retest_zone_high=float(retest_zone_high),
                atr_trigger=float(trigger_atr),
            )
        stop_price = _price(last_trigger, "high") + (trigger_atr * stop_atr_multiple)
        risk_distance = stop_price - entry_price
        nearest_htf_level = _nearest_level(bias_lows, below=entry_price)

    if risk_distance <= 0:
        return TrendRetestReclaimSignalResult(None, "btc_mtf_invalid_risk_distance")
    if risk_distance > trigger_atr * entry_max_atr_multiple:
        return TrendRetestReclaimSignalResult(
            None,
            "btc_mtf_entry_too_far_from_invalidation",
            adx_bias=float(adx_bias),
            adx_setup=float(setup_breakout["adx"]),
            volume_ratio=float(setup_breakout["volume_ratio"]),
            breakout_level=float(setup_breakout["breakout_level"]),
            sweep_level=float(sweep_level),
            retest_zone_low=float(retest_zone_low),
            retest_zone_high=float(retest_zone_high),
            atr_trigger=float(trigger_atr),
        )

    if nearest_htf_level > 0:
        distance_to_htf = abs(nearest_htf_level - entry_price)
        if distance_to_htf < risk_distance * max(htf_target_min_r, 0.0):
            return TrendRetestReclaimSignalResult(
                None,
                "btc_mtf_htf_level_too_close",
                adx_bias=float(adx_bias),
                adx_setup=float(setup_breakout["adx"]),
                volume_ratio=float(setup_breakout["volume_ratio"]),
                breakout_level=float(setup_breakout["breakout_level"]),
                sweep_level=float(sweep_level),
                retest_zone_low=float(retest_zone_low),
                retest_zone_high=float(retest_zone_high),
                atr_trigger=float(trigger_atr),
            )

    return TrendRetestReclaimSignalResult(
        signal=SweepSignal(side=side, level=float(setup_breakout["breakout_level"]), candle_time=int(last_trigger["time"])),
        note=f"btc_mtf_{side.lower()}_retest_reclaim",
        stop_price=float(stop_price),
        tp_r_multiple=2.0,
        risk_pct_override=float(weekend_risk),
        bias_note=(
            f"{structure_note} adx4h={adx_bias:.2f} adx1h={float(setup_breakout['adx']):.2f} "
            f"vol_ratio={float(setup_breakout['volume_ratio']):.2f}"
        ),
        breakout_level=float(setup_breakout["breakout_level"]),
        sweep_level=float(sweep_level),
        retest_zone_low=float(retest_zone_low),
        retest_zone_high=float(retest_zone_high),
        atr_trigger=float(trigger_atr),
        adx_bias=float(adx_bias),
        adx_setup=float(setup_breakout["adx"]),
        volume_ratio=float(setup_breakout["volume_ratio"]),
    )


