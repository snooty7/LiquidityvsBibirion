from __future__ import annotations

from dataclasses import dataclass
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING


class RiskSizingError(ValueError):
    """The proposed trade cannot be sized within its risk budget."""


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
    if not all(math.isfinite(v) and v > 0 for v in (
        symbol_info.trade_tick_value, symbol_info.trade_tick_size, symbol_info.point,
    )):
        return 0.0
    pip = pip_size(symbol_info.digits, symbol_info.point)
    return float(symbol_info.trade_tick_value * (pip / symbol_info.trade_tick_size))


def _round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return float((Decimal(str(value)) / Decimal(str(step))).to_integral_value(
        rounding=ROUND_FLOOR
    ) * Decimal(str(step)))


def calc_lot_by_risk(
    equity: float,
    sl_pips: float,
    risk_pct: float,
    symbol_info: SymbolTradeInfo,
    max_lot: float,
    min_lot: float = 0.0,
) -> float:
    if not all(math.isfinite(v) and v > 0 for v in (
        equity, sl_pips, risk_pct, max_lot, symbol_info.volume_min,
        symbol_info.volume_max, symbol_info.volume_step,
    )) or not math.isfinite(min_lot) or min_lot < 0:
        raise RiskSizingError("Risk, equity, stop distance and volume limits must be valid and positive.")

    risk_money = equity * (risk_pct / 100.0)
    pvl = pip_value_per_lot(symbol_info)

    if pvl <= 0 or not math.isfinite(pvl):
        raise RiskSizingError("Symbol valuation is unavailable; cannot size risk.")
    lot = risk_money / (sl_pips * pvl)

    hard_cap = min(symbol_info.volume_max, max_lot)
    hard_floor = max(symbol_info.volume_min, min_lot)
    step = Decimal(str(symbol_info.volume_step))
    hard_floor = float((Decimal(str(hard_floor)) / step).to_integral_value(
        rounding=ROUND_CEILING
    ) * step)
    lot = _round_to_step(min(lot, hard_cap), symbol_info.volume_step)
    if lot < hard_floor or lot <= 0:
        raise RiskSizingError("Minimum tradable volume exceeds the risk budget or volume cap.")

    if not math.isfinite(lot):
        raise RiskSizingError("Computed lot is not finite.")

    return float(lot)


def calc_position_risk_money(
    entry_price: float,
    stop_price: float,
    volume: float,
    symbol_info: SymbolTradeInfo,
) -> float:
    if not all(math.isfinite(v) for v in (entry_price, stop_price, volume)):
        return float("inf")
    if volume <= 0:
        return 0.0
    if stop_price <= 0:
        return float("inf")

    pip = pip_size(symbol_info.digits, symbol_info.point)
    pvl = pip_value_per_lot(symbol_info)
    if pip <= 0 or pvl <= 0 or not math.isfinite(pvl):
        return float("inf")

    sl_pips = abs(float(entry_price) - float(stop_price)) / pip
    return float(sl_pips * pvl * abs(float(volume)))


def daily_loss_limit_hit(realized_pnl: float, limit: float) -> bool:
    """A nonpositive daily limit disables the guard in both execution modes."""
    return limit > 0 and realized_pnl <= -limit


def valid_entry_protection(side: str, price: float, sl: float, tp: float) -> bool:
    """Require finite, positive prices with protection on the correct side."""
    if not all(math.isfinite(value) and value > 0 for value in (price, sl, tp)):
        return False
    return sl < price < tp if side == "BUY" else tp < price < sl


def projected_risk_message(equity: float, open_risk: float, proposed_risk: float, cap_pct: float) -> str | None:
    """Check measured monetary exposure, including the proposed order."""
    if not all(math.isfinite(v) and v >= 0 for v in (open_risk, proposed_risk)):
        return "open or proposed position risk is unknown"
    if not math.isfinite(equity) or equity <= 0:
        return "invalid equity for portfolio cap"
    if cap_pct > 0 and open_risk + proposed_risk > equity * cap_pct / 100.0 + 1e-9:
        return f"projected_risk_pct={(open_risk + proposed_risk) / equity * 100:.2f} cap={cap_pct:.2f}"
    return None
