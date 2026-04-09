from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class ConfirmationResult:
    confirmed: bool
    pending: bool
    note: str


def _price(bar: object, field: str) -> float:
    if isinstance(bar, dict):
        return float(bar[field])
    return float(bar[field])


def locate_candle_index_by_time(rates: Sequence[object], candle_time: int) -> Optional[int]:
    for idx, bar in enumerate(rates):
        if int(bar["time"]) == int(candle_time):
            return idx
    return None


def candle_body_ratio(candle: object) -> float:
    high = _price(candle, "high")
    low = _price(candle, "low")
    candle_range = max(high - low, 1e-10)
    return abs(_price(candle, "close") - _price(candle, "open")) / candle_range


def candle_body_size(candle: object) -> float:
    return abs(_price(candle, "close") - _price(candle, "open"))


def candle_range(candle: object) -> float:
    return max(_price(candle, "high") - _price(candle, "low"), 1e-10)


def is_strong_c2(candle: object, side: str) -> bool:
    open_price = _price(candle, "open")
    close_price = _price(candle, "close")
    high = _price(candle, "high")
    low = _price(candle, "low")
    midpoint = (high + low) / 2.0
    body_ok = candle_body_ratio(candle) >= 0.35

    if side == "BUY":
        return close_price > open_price and close_price > midpoint and body_ok
    return close_price < open_price and close_price < midpoint and body_ok


def confirm_c3(c2: object, candle: object, side: str) -> bool:
    close_price = _price(candle, "close")
    high = _price(candle, "high")
    low = _price(candle, "low")

    if side == "BUY":
        return close_price > max(_price(c2, "open"), _price(c2, "close")) and low >= _price(c2, "low")
    return close_price < min(_price(c2, "open"), _price(c2, "close")) and high <= _price(c2, "high")


def confirm_c4(c3: object, candle: object, side: str) -> bool:
    close_price = _price(candle, "close")
    c3_close = _price(c3, "close")
    if side == "BUY":
        return close_price > c3_close
    return close_price < c3_close


def evaluate_c3_c4_confirmation(
    rates: Sequence[object],
    side: str,
    sweep_candle_time: int,
    mode: str,
) -> ConfirmationResult:
    mode_norm = mode.lower()
    if mode_norm not in ("c3", "c4"):
        return ConfirmationResult(False, False, f"invalid_confirmation_mode={mode}")

    sweep_index = locate_candle_index_by_time(rates, sweep_candle_time)
    if sweep_index is None:
        return ConfirmationResult(False, False, "sweep_candle_not_found")

    last_closed_idx = len(rates) - 2
    if sweep_index >= last_closed_idx:
        return ConfirmationResult(False, True, "await_next_closed_candle")

    c2 = rates[sweep_index]
    if not is_strong_c2(c2, side):
        return ConfirmationResult(False, False, "c2_not_strong")

    c3_idx = sweep_index + 1
    if c3_idx > last_closed_idx:
        return ConfirmationResult(False, True, "await_c3")

    c3 = rates[c3_idx]
    if not confirm_c3(c2, c3, side):
        return ConfirmationResult(False, False, "c3_rejected")

    if mode_norm == "c3":
        return ConfirmationResult(True, False, "c3_confirmed")

    c4_idx = sweep_index + 2
    if c4_idx > last_closed_idx:
        return ConfirmationResult(False, True, "await_c4")

    c4 = rates[c4_idx]
    if not confirm_c4(c3, c4, side):
        return ConfirmationResult(False, False, "c4_rejected")

    return ConfirmationResult(True, False, "c4_confirmed")


def evaluate_none_confirmation(
    rates: Sequence[object],
    since_ts: int,
) -> ConfirmationResult:
    signal_index = locate_candle_index_by_time(rates, since_ts)
    if signal_index is None:
        return ConfirmationResult(False, False, "signal_candle_not_found")

    last_closed_idx = len(rates) - 2
    if signal_index >= last_closed_idx:
        return ConfirmationResult(False, True, "await_next_closed_candle")

    return ConfirmationResult(True, False, "none_confirmed")


def evaluate_cisd_confirmation(
    rates: Sequence[object],
    side: str,
    since_ts: int,
    structure_bars: int,
) -> ConfirmationResult:
    closed = [bar for bar in rates[:-1] if int(bar["time"]) >= int(since_ts)]
    needed = max(2, int(structure_bars) + 1)
    if len(closed) < needed:
        return ConfirmationResult(False, True, f"await_cisd_{len(closed)}/{needed}")

    recent = closed[-needed:]
    highs = [_price(bar, "high") for bar in recent]
    lows = [_price(bar, "low") for bar in recent]
    closes = [_price(bar, "close") for bar in recent]

    if side == "BUY":
        structure_ok = highs[-1] > highs[0] and lows[-1] > lows[0]
        displacement_ok = closes[-1] > max(highs[:-1])
        if structure_ok and displacement_ok:
            return ConfirmationResult(True, False, "cisd_buy_confirmed")
        return ConfirmationResult(False, True, "cisd_buy_waiting")

    structure_ok = highs[-1] < highs[0] and lows[-1] < lows[0]
    displacement_ok = closes[-1] < min(lows[:-1])
    if structure_ok and displacement_ok:
        return ConfirmationResult(True, False, "cisd_sell_confirmed")
    return ConfirmationResult(False, True, "cisd_sell_waiting")


def evaluate_sweep_displacement_mss_confirmation(
    rates: Sequence[object],
    side: str,
    since_ts: int,
    structure_bars: int,
    *,
    displacement_body_ratio_min: float = 0.60,
    displacement_range_multiple: float = 1.50,
) -> ConfirmationResult:
    closed = [bar for bar in rates[:-1] if int(bar["time"]) >= int(since_ts)]
    needed_context = max(2, int(structure_bars))
    if len(closed) <= needed_context:
        return ConfirmationResult(False, True, f"await_sdmss_context_{len(closed)}/{needed_context + 1}")

    displacement_idx: Optional[int] = None
    saw_displacement_without_bos = False
    for idx in range(needed_context, len(closed)):
        candle = closed[idx]
        prior = closed[idx - needed_context : idx]
        avg_range = sum(candle_range(item) for item in prior) / max(len(prior), 1)
        ratio_ok = candle_body_ratio(candle) >= displacement_body_ratio_min
        size_ok = candle_range(candle) >= max(avg_range * displacement_range_multiple, 1e-10)

        if side == "BUY":
            direction_ok = _price(candle, "close") > _price(candle, "open")
            structure_level = max(_price(item, "high") for item in prior)
            structure_break_ok = _price(candle, "close") > structure_level
        else:
            direction_ok = _price(candle, "close") < _price(candle, "open")
            structure_level = min(_price(item, "low") for item in prior)
            structure_break_ok = _price(candle, "close") < structure_level

        if ratio_ok and size_ok and direction_ok and not structure_break_ok:
            saw_displacement_without_bos = True
            continue

        if ratio_ok and size_ok and direction_ok and structure_break_ok:
            displacement_idx = idx
            break

    if displacement_idx is None:
        if saw_displacement_without_bos:
            return ConfirmationResult(False, True, "sdmss_wait_bos")
        return ConfirmationResult(False, True, "sdmss_wait_displacement")

    if side == "BUY":
        return ConfirmationResult(True, False, "sdmss_buy_confirmed")
    return ConfirmationResult(True, False, "sdmss_sell_confirmed")


def evaluate_sweep_displacement_only_confirmation(
    rates: Sequence[object],
    side: str,
    since_ts: int,
    structure_bars: int,
    *,
    displacement_body_ratio_min: float = 0.60,
    displacement_range_multiple: float = 1.50,
) -> ConfirmationResult:
    closed = [bar for bar in rates[:-1] if int(bar["time"]) >= int(since_ts)]
    needed_context = max(2, int(structure_bars))
    if len(closed) <= needed_context:
        return ConfirmationResult(False, True, f"await_sdd_context_{len(closed)}/{needed_context + 1}")

    for idx in range(needed_context, len(closed)):
        candle = closed[idx]
        prior = closed[idx - needed_context : idx]
        avg_range = sum(candle_range(item) for item in prior) / max(len(prior), 1)
        ratio_ok = candle_body_ratio(candle) >= displacement_body_ratio_min
        size_ok = candle_range(candle) >= max(avg_range * displacement_range_multiple, 1e-10)
        if side == "BUY":
            direction_ok = _price(candle, "close") > _price(candle, "open")
        else:
            direction_ok = _price(candle, "close") < _price(candle, "open")
        if ratio_ok and size_ok and direction_ok:
            if side == "BUY":
                return ConfirmationResult(True, False, "sdd_buy_confirmed")
            return ConfirmationResult(True, False, "sdd_sell_confirmed")

    return ConfirmationResult(False, True, "sdd_wait_displacement")


def evaluate_session_open_scalp_c1_confirmation(
    rates: Sequence[object],
    side: str,
    since_ts: int,
) -> ConfirmationResult:
    signal_index = locate_candle_index_by_time(rates, since_ts)
    if signal_index is None:
        return ConfirmationResult(False, False, "scalp_signal_candle_not_found")

    last_closed_idx = len(rates) - 2
    if signal_index >= last_closed_idx:
        return ConfirmationResult(False, True, "scalp_wait_c1")

    signal_candle = rates[signal_index]
    for idx in range(signal_index + 1, last_closed_idx + 1):
        candle = rates[idx]
        close_price = _price(candle, "close")
        if side == "BUY":
            if close_price > _price(signal_candle, "high"):
                return ConfirmationResult(True, False, "scalp_c1_buy_confirmed")
        else:
            if close_price < _price(signal_candle, "low"):
                return ConfirmationResult(True, False, "scalp_c1_sell_confirmed")

    return ConfirmationResult(False, True, "scalp_wait_c1")
