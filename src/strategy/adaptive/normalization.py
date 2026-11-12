"""Auditable bounded evidence mappings, without weights or threshold fitting."""
import math

from src.strategy.adaptive.models import FeatureObservation, Regime, RegimeResult, StructureEvent, Zone
from src.strategy.filters import order_block_distance_pips


def event_observation(name: str, event: StructureEvent | None, decision_time: int) -> FeatureObservation:
    """Clip a nonnegative ATR-relative move; invalid data is unavailable, never 1."""
    if event is None:
        return FeatureObservation(name, None, "event_unavailable", decision_time)
    if event.available_at > decision_time:
        return FeatureObservation(name, None, "future_event", decision_time)
    if not math.isfinite(event.strength) or event.strength < 0:
        return FeatureObservation(name, None, "invalid_strength", decision_time)
    raw = (("move_atr", event.strength),)
    if event.raw_move is not None or event.normalization_atr is not None:
        if (event.raw_move is None or event.normalization_atr is None or
                not math.isfinite(event.raw_move) or event.raw_move < 0 or
                not math.isfinite(event.normalization_atr) or event.normalization_atr <= 0):
            return FeatureObservation(name, None, "invalid_move_or_atr", decision_time)
        ratio = event.raw_move/event.normalization_atr
        if not math.isfinite(ratio) or not math.isclose(ratio, event.strength, rel_tol=1e-12, abs_tol=1e-12):
            return FeatureObservation(name, None, "inconsistent_move_or_atr", decision_time)
        raw = (("move_price", event.raw_move), ("atr", event.normalization_atr), ("move_atr", ratio))
    return FeatureObservation(name, min(1.0, event.strength), f"move_atr:{event.timeframe}", decision_time, raw)


def zone_observation(zones: tuple[Zone, ...], side: str | None, price: float, atr: float,
                     decision_time: int) -> FeatureObservation:
    """Maximum proximity to an active interval, at the existing two-ATR scale."""
    if not math.isfinite(price) or price <= 0 or not math.isfinite(atr) or atr <= 0:
        return FeatureObservation("zone", None, "price_or_atr_unavailable", decision_time)
    active = [zone for zone in zones if zone.side == side and zone.status == "active"]
    if not active:
        return FeatureObservation("zone", None, "no_active_zone", decision_time)
    if any(zone.available_at > decision_time or not all(math.isfinite(v) and v > 0 for v in (zone.low, zone.high))
           or zone.low >= zone.high for zone in active):
        return FeatureObservation("zone", None, "invalid_or_future_zone", decision_time)
    selected = min(active, key=lambda zone: order_block_distance_pips(price, zone.low, zone.high, 1.0))
    distance = order_block_distance_pips(price, selected.low, selected.high, 1.0)
    distance_atr = distance/atr
    if not math.isfinite(distance_atr):
        return FeatureObservation("zone", None, "invalid_distance_or_atr", decision_time)
    quality = max(0.0, 1-distance_atr/2)
    return FeatureObservation("zone", quality, "max_interval_proximity", decision_time,
                              (("entry_price", price), ("atr", atr), ("zone_low", selected.low),
                               ("zone_high", selected.high), ("distance_price", distance),
                               ("distance_atr", distance_atr), ("scale_atr", 2.0),
                               ("active_zone_count", float(len(active)))))


def regime_observation(regime: RegimeResult, side: str | None, decision_time: int) -> FeatureObservation:
    """A known regime contributes evidence only when compatible with the side."""
    if (side not in {"BUY", "SELL"} or regime.regime not in set(Regime)
            or regime.reason in {"insufficient_context", "invalid_context", "invalid_indicators", "zero_atr"}
            or not all(math.isfinite(value) for value in (regime.atr, regime.adx, regime.atr_percentile, regime.realized_volatility))
            or regime.atr <= 0):
        return FeatureObservation("regime", None, "regime_or_side_unavailable", decision_time)
    compatible = (regime.regime == Regime.RANGING or
                  regime.regime == Regime.TRENDING_BULLISH and side == "BUY" or
                  regime.regime == Regime.TRENDING_BEARISH and side == "SELL")
    return FeatureObservation("regime", float(compatible), f"{regime.reason}:side_{'compatible' if compatible else 'incompatible'}",
                              decision_time, (("atr", regime.atr), ("adx", regime.adx),
                                              ("atr_percentile", regime.atr_percentile),
                                              ("realized_volatility", regime.realized_volatility)))
