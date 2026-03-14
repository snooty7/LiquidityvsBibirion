from __future__ import annotations

from typing import Optional, Sequence


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