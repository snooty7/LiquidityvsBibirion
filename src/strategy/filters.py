from __future__ import annotations

from typing import Optional, Sequence
from dataclasses import dataclass
import math


def _price(bar: object, field: str) -> float:
    if isinstance(bar, dict):
        return float(bar[field])
    return float(bar[field])


def ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("EMA period must be positive.")
    if len(values) == 0:
        return []

    alpha = 2.0 / (period + 1.0)
    result: list[float] = [float(values[0])]
    for idx in range(1, len(values)):
        result.append(alpha * float(values[idx]) + (1.0 - alpha) * result[idx - 1])
    return result


def evaluate_bias(rates: Sequence[object], ema_period: int) -> dict:
    closes = [_price(bar, "close") for bar in rates]
    if len(closes) < ema_period + 2:
        return {
            "ok_buy": False,
            "ok_sell": False,
            "note": "bias_insufficient_bars",
        }

    ema_series = ema(closes, ema_period)
    last_close = float(closes[-1])
    ema_now = float(ema_series[-1])
    ema_prev = float(ema_series[-2])

    ok_buy = last_close > ema_now and ema_now >= ema_prev
    ok_sell = last_close < ema_now and ema_now <= ema_prev

    return {
        "ok_buy": ok_buy,
        "ok_sell": ok_sell,
        "note": f"bias close={last_close:.5f} ema={ema_now:.5f} ema_prev={ema_prev:.5f}",
    }


def bias_context_count(lookback_bars: int, ema_period: int) -> int:
    """Number of closed bars used by both live and historical entry-bias checks."""
    return max(lookback_bars, ema_period + 2)


def long_entry_context_count(ema_period: int, atr_period: int, slope_bars: int) -> int:
    """Use a fixed EMA initialization horizon so feature values match across runtimes."""
    return max(4 * ema_period, atr_period + 1, slope_bars + 2)


def long_entry_slope_atr(closed_rates: Sequence[object], *, ema_period: int = 20,
                         atr_period: int = 14, slope_bars: int = 3) -> Optional[float]:
    """EMA rise over the specified closed bars, divided by recent mean true range."""
    if ema_period < 1 or atr_period < 2 or slope_bars < 1:
        raise ValueError("Long-entry periods must be positive, with ATR period >= 2")
    count = long_entry_context_count(ema_period, atr_period, slope_bars)
    if len(closed_rates) < count:
        return None
    rates = list(closed_rates[-count:])
    closes = [_price(row, "close") for row in rates]
    highs = [_price(row, "high") for row in rates]
    lows = [_price(row, "low") for row in rates]
    if not all(math.isfinite(v) and v > 0 for v in closes + highs + lows):
        return None
    if any(low > close or close > high for low, close, high in zip(lows, closes, highs)):
        return None
    true_ranges = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
                   for i in range(len(rates)-atr_period, len(rates))]
    atr = sum(true_ranges)/atr_period
    if atr <= 0 or not math.isfinite(atr):
        return None
    values = ema(closes, ema_period)
    return (values[-1]-values[-1-slope_bars])/atr


@dataclass(frozen=True)
class LongEntryFilterResult:
    allowed: bool
    note: str
    slope_atr: Optional[float] = None


def evaluate_long_entry_filter(side: str, closed_rates: Sequence[object], *, mode: str = "off",
                               min_slope_atr: float = 0.0, ema_period: int = 20,
                               atr_period: int = 14, slope_bars: int = 3) -> LongEntryFilterResult:
    """Apply an optional BUY-only gate; SELL eligibility is unchanged."""
    if mode not in {"off", "ema_slope_atr"}:
        raise ValueError(f"Unsupported long-entry filter mode: {mode}")
    if mode == "off" or side.upper() == "SELL":
        return LongEntryFilterResult(True, "long_filter_off" if mode == "off" else "long_filter_sell_unchanged")
    if side.upper() != "BUY":
        raise ValueError("Entry side must be BUY or SELL")
    if not math.isfinite(min_slope_atr) or min_slope_atr < 0:
        raise ValueError("Long-entry threshold must be finite and nonnegative")
    value = long_entry_slope_atr(closed_rates, ema_period=ema_period,
                                 atr_period=atr_period, slope_bars=slope_bars)
    if value is None:
        return LongEntryFilterResult(False, "long_filter_context_unavailable")
    allowed = value >= min_slope_atr
    return LongEntryFilterResult(allowed, f"long_filter slope_atr={value:.6f} min={min_slope_atr:.6f}", value)


def find_local_order_block(
    rates: Sequence[object],
    signal_index: int,
    side: str,
    pip: float,
    lookback_bars: int,
    max_age_bars: int,
    zone_mode: str,
    min_impulse_pips: float,
) -> Optional[dict]:
    start_index = max(1, signal_index - int(lookback_bars))

    for index in range(signal_index - 1, start_index - 1, -1):
        if signal_index - index > int(max_age_bars):
            break

        candle_open = _price(rates[index], "open")
        candle_close = _price(rates[index], "close")
        candle_high = _price(rates[index], "high")
        candle_low = _price(rates[index], "low")

        is_bearish = candle_close < candle_open
        is_bullish = candle_close > candle_open

        zone_low = candle_low
        zone_high = candle_high
        if zone_mode == "body":
            zone_low = min(candle_open, candle_close)
            zone_high = max(candle_open, candle_close)

        follow_slice = rates[index + 1 : signal_index + 1]
        if len(follow_slice) == 0:
            continue

        if side == "BUY" and is_bearish:
            max_high = max(_price(bar, "high") for bar in follow_slice)
            impulse_pips = (max_high - candle_high) / pip
            displacement_ok = _price(follow_slice[-1], "close") > candle_high
            if impulse_pips < min_impulse_pips or not displacement_ok:
                continue
            return {
                "index": index,
                "time": int(rates[index]["time"]),
                "low": zone_low,
                "high": zone_high,
                "kind": "BULLISH_OB",
                "impulse_pips": float(impulse_pips),
            }

        if side == "SELL" and is_bullish:
            min_low = min(_price(bar, "low") for bar in follow_slice)
            impulse_pips = (candle_low - min_low) / pip
            displacement_ok = _price(follow_slice[-1], "close") < candle_low
            if impulse_pips < min_impulse_pips or not displacement_ok:
                continue
            return {
                "index": index,
                "time": int(rates[index]["time"]),
                "low": zone_low,
                "high": zone_high,
                "kind": "BEARISH_OB",
                "impulse_pips": float(impulse_pips),
            }

    return None


def order_block_distance_pips(entry_price: float, ob_low: float, ob_high: float, pip: float) -> float:
    if ob_low <= entry_price <= ob_high:
        return 0.0
    if entry_price < ob_low:
        return float((ob_low - entry_price) / pip)
    return float((entry_price - ob_high) / pip)


def order_block_note(order_block: dict, distance_pips: float) -> str:
    return (
        f"{order_block['kind']} "
        f"zone={float(order_block['low']):.5f}-{float(order_block['high']):.5f} "
        f"ob_time={int(order_block['time'])} "
        f"ob_dist={distance_pips:.2f}p "
        f"ob_impulse={float(order_block.get('impulse_pips', 0.0)):.2f}p"
    )


def resolve_order_block_distance_limit_pips(
    base_limit_pips: float,
    order_block: Optional[dict],
    *,
    confirmation_mode: str,
    range_note: str,
    strong_override_max_distance_pips: float,
    strong_override_min_impulse_pips: float,
) -> tuple[float, str]:
    allowed_limit = float(base_limit_pips)
    if order_block is None:
        return allowed_limit, ""

    override_limit = float(strong_override_max_distance_pips)
    impulse_pips = float(order_block.get("impulse_pips", 0.0) or 0.0)
    if (
        confirmation_mode == "sweep_displacement_mss"
        and range_note == "range_ok"
        and override_limit > allowed_limit
        and impulse_pips >= float(strong_override_min_impulse_pips)
    ):
        return (
            override_limit,
            f"ob_override=sdmss_strong range_note={range_note} "
            f"ob_impulse={impulse_pips:.2f}p max_ob_dist={override_limit:.2f}p",
        )

    return allowed_limit, ""
