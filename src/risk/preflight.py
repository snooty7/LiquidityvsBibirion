"""Pure adaptive preflight; never connects to a broker or changes legacy guards."""
from dataclasses import dataclass
from decimal import Decimal
import math
from statistics import correlation

from src.risk.sizing import (
    SymbolTradeInfo, RiskSizingError, calc_lot_by_risk, calc_position_risk_money,
    daily_loss_limit_hit, projected_risk_message, valid_entry_protection,
)

FX_CURRENCIES = frozenset({"EUR", "USD", "GBP", "CHF", "JPY", "AUD", "NZD", "CAD", "NOK", "SEK", "DKK", "SGD", "HKD", "ZAR", "MXN"})


@dataclass(frozen=True)
class Exposure:
    """One unique account position, valued in account currency at its initial stop."""

    ticket: int
    symbol: str
    side: str
    risk_money: float


@dataclass(frozen=True)
class BrokerLimits:
    """Explicit metadata; research may declare zero distance, never assume it live."""

    minimum_stop_price: float
    freeze_price: float
    tick_size: float


@dataclass(frozen=True)
class PreflightResult:
    """An allowed volume or explicit reasons; no executable order is produced."""

    allowed: bool
    reasons: tuple[str, ...]
    volume: float = 0.0
    risk_money: float = 0.0


def aligned_correlation(left: dict[int, float], right: dict[int, float], *,
                        decision_time: int, minimum: int = 30, lookback: int = 120) -> float | None:
    """Correlate only already available aligned returns, with enough variation."""
    times = sorted(set(left) & set(right))
    if lookback < minimum or minimum < 3:
        raise ValueError("Correlation lookback must cover at least three minimum samples")
    times = [timestamp for timestamp in times if timestamp <= decision_time][-lookback:]
    if len(times) < max(3, minimum):
        return None
    x, y = [left[t] for t in times], [right[t] for t in times]
    if not all(math.isfinite(v) for v in x + y) or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return correlation(x, y)


def check_entry(*, side: str, symbol: str, price: float, sl: float, tp: float,
                equity: float, risk_pct: float, authorized_risk_pct: float,
                info: SymbolTradeInfo, limits: BrokerLimits, max_lot: float,
                min_lot: float, spread_pips: float, max_spread_pips: float,
                quote_time: float, decision_time: float, max_quote_age: float,
                realized_today: float, daily_limit: float, positions: tuple[Exposure, ...],
                portfolio_cap_pct: float, max_positions: int,
                currency_cap_pct: float, correlation_cap_pct: float,
                correlations: dict[str, float | None], min_rr: float = 1.0,
                round_trip_cost_price: float = 0.0,
                margin_available: bool | None = None, research: bool = False) -> PreflightResult:
    """Fail closed on unknown risk, metadata, history, concentration or live margin.

    Positions must cover the entire account. No offsetting exposure credit is given.
    The caller obtains fresh quotes/metadata; this service performs no I/O.
    """
    reasons = []
    values = (price, sl, tp, equity, risk_pct, authorized_risk_pct, spread_pips,
              max_spread_pips, quote_time, decision_time, max_quote_age,
              realized_today, daily_limit, portfolio_cap_pct, currency_cap_pct,
              correlation_cap_pct, min_rr, round_trip_cost_price,
              limits.minimum_stop_price, limits.freeze_price, limits.tick_size)
    if not all(math.isfinite(v) for v in values):
        return PreflightResult(False, ("nonfinite_preflight",))
    if (side not in {"BUY", "SELL"} or not valid_entry_protection(side, price, sl, tp)
            or equity <= 0 or risk_pct <= 0 or risk_pct > authorized_risk_pct
            or min(portfolio_cap_pct, currency_cap_pct, correlation_cap_pct, max_quote_age) <= 0
            or max_positions < 1 or min_rr <= 0 or round_trip_cost_price < 0):
        return PreflightResult(False, ("invalid_protection_or_budget",))
    if spread_pips < 0 or max_spread_pips < 0 or spread_pips > max_spread_pips + 1e-9:
        reasons.append("spread_limit")
    if quote_time > decision_time or decision_time - quote_time > max_quote_age:
        reasons.append("stale_or_future_quote")
    if daily_loss_limit_hit(realized_today, daily_limit):
        reasons.append("daily_loss_limit")
    if not research and margin_available is not True:
        reasons.append("margin_unverified")
    if limits.tick_size <= 0 or min(limits.minimum_stop_price, limits.freeze_price) < 0:
        reasons.append("invalid_broker_limits")
    else:
        for value in (price, sl, tp):
            ticks = value / limits.tick_size
            if not math.isclose(ticks, round(ticks), abs_tol=1e-6, rel_tol=0):
                reasons.append("price_off_tick")
                break
        if min(abs(price-sl), abs(price-tp)) + 1e-12 < max(limits.minimum_stop_price, limits.freeze_price):
            reasons.append("broker_stop_distance")
    stop = abs(price-sl)
    if (abs(tp-price)-round_trip_cost_price) / (stop+round_trip_cost_price) < min_rr:
        reasons.append("net_reward_risk")
    unique = {}
    for item in positions:
        if item.ticket <= 0 or item.side not in {"BUY", "SELL"} or not math.isfinite(item.risk_money) or item.risk_money < 0:
            reasons.append("unknown_position_exposure")
        if item.ticket in unique and unique[item.ticket] != item:
            reasons.append("conflicting_position_snapshot")
        unique[item.ticket] = item
    if len(unique) >= max_positions:
        reasons.append("position_limit")
    try:
        volume = calc_lot_by_risk(equity, stop / (info.point * (10 if info.digits in (3, 5) else 1)),
                                  risk_pct, info, max_lot, min_lot)
    except (RiskSizingError, ZeroDivisionError) as exc:
        return PreflightResult(False, tuple(reasons + [f"sizing:{exc}"]))
    risk = calc_position_risk_money(price, sl, volume, info)
    if projected_risk_message(equity, sum(p.risk_money for p in unique.values()), risk, portfolio_cap_pct):
        reasons.append("portfolio_risk_limit")
    # Explicit six-letter FX currency scope. Non-FX symbols require a future asset map.
    if len(symbol) != 6 or symbol[:3] not in FX_CURRENCIES or symbol[3:] not in FX_CURRENCIES:
        reasons.append("currency_mapping_unavailable")
    else:
        for currency in (symbol[:3], symbol[3:]):
            existing = sum(p.risk_money for p in unique.values()
                           if currency in (p.symbol[:3], p.symbol[3:]))
            if existing + risk > equity * currency_cap_pct / 100 + 1e-9:
                reasons.append(f"currency_limit:{currency}")
    correlated_risk = risk
    for item in unique.values():
        if len(item.symbol) != 6 or item.symbol[:3] not in FX_CURRENCIES or item.symbol[3:] not in FX_CURRENCIES:
            reasons.append(f"currency_mapping_unavailable:{item.symbol}")
        coefficient = 1.0 if item.symbol == symbol else correlations.get(item.symbol)
        if coefficient is None or not math.isfinite(coefficient) or abs(coefficient) > 1:
            reasons.append(f"correlation_unavailable:{item.symbol}")
        elif abs(coefficient) >= 0.7:
            # Conservative absolute dependence, no hedge/diversification credit.
            correlated_risk += item.risk_money
    if correlated_risk > equity * correlation_cap_pct / 100 + 1e-9:
        reasons.append("correlation_exposure_limit")
    return PreflightResult(not reasons, tuple(dict.fromkeys(reasons)), volume if not reasons else 0.0, risk)


def partial_close_volume(volume: float, fraction: float, info: SymbolTradeInfo) -> float:
    """Round down a partial close only when both closed and residual lots are valid."""
    if not all(math.isfinite(v) for v in (volume, fraction, info.volume_step, info.volume_min)):
        return 0.0
    if not 0 < fraction < 1 or info.volume_step <= 0 or info.volume_min <= 0:
        return 0.0
    step = Decimal(str(info.volume_step))
    amount = (Decimal(str(volume)) * Decimal(str(fraction)) // step) * step
    remainder = Decimal(str(volume)) - amount
    if amount < Decimal(str(info.volume_min)) or remainder < Decimal(str(info.volume_min)) or remainder % step:
        return 0.0
    return float(amount)
