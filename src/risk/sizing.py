from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SymbolTradeInfo:
    digits: int
    point: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_tick_value: float
    trade_tick_size: float

    @staticmethod
    def from_mt5(symbol_info: object) -> "SymbolTradeInfo":
        return SymbolTradeInfo(
            digits=int(symbol_info.digits),
            point=float(symbol_info.point),
            volume_min=float(symbol_info.volume_min),
            volume_max=float(symbol_info.volume_max),
            volume_step=float(symbol_info.volume_step or 0.01),
            trade_tick_value=float(symbol_info.trade_tick_value),
            trade_tick_size=float(symbol_info.trade_tick_size),
        )


def pip_size(digits: int, point: float) -> float:
    if digits in (3, 5):
        return 10.0 * point
    return point


def pip_value_per_lot(symbol_info: SymbolTradeInfo) -> float:
    if symbol_info.trade_tick_value <= 0 or symbol_info.trade_tick_size <= 0:
        return 0.0
    pip = pip_size(symbol_info.digits, symbol_info.point)
    return float(symbol_info.trade_tick_value * (pip / symbol_info.trade_tick_size))


def _round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(value / step) * step


def calc_lot_by_risk(
    equity: float,
    sl_pips: float,
    risk_pct: float,
    symbol_info: SymbolTradeInfo,
    max_lot: float,
    min_lot: float = 0.0,
) -> float:
    if equity <= 0:
        raise ValueError("Equity must be positive.")

    risk_money = equity * (risk_pct / 100.0)
    pvl = pip_value_per_lot(symbol_info)

    if pvl <= 0 or sl_pips <= 0:
        lot = max(symbol_info.volume_min, 0.01)
    else:
        lot = risk_money / (sl_pips * pvl)

    hard_cap = min(symbol_info.volume_max, max_lot)
    hard_floor = max(symbol_info.volume_min, min_lot)
    if hard_floor > hard_cap:
        hard_floor = hard_cap
    lot = max(lot, hard_floor)
    lot = min(lot, hard_cap)
    lot = _round_to_step(lot, symbol_info.volume_step)
    lot = max(lot, hard_floor)
    lot = min(lot, hard_cap)

    if not math.isfinite(lot):
        raise ValueError("Computed lot is not finite.")

    return float(lot)


def calc_position_risk_money(
    entry_price: float,
    stop_price: float,
    volume: float,
    symbol_info: SymbolTradeInfo,
) -> float:
    if volume <= 0:
        return 0.0
    if stop_price <= 0:
        return float("inf")

    pip = pip_size(symbol_info.digits, symbol_info.point)
    pvl = pip_value_per_lot(symbol_info)
    if pip <= 0 or pvl <= 0:
        return 0.0

    sl_pips = abs(float(entry_price) - float(stop_price)) / pip
    return float(sl_pips * pvl * abs(float(volume)))
