"""Causal pivots, sweep/structure events and zone lifecycles from closed bars."""
from src.backtesting.history import TIMEFRAMES
from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.models import Candle, StructureContext, StructureEvent, Zone
from src.strategy.filters import find_local_order_block


def analyze_structure(bars: tuple[Candle, ...], config: AdaptiveConfig, atr: float, pip: float) -> StructureContext:
    """Confirm pivots after right bars close; never give the sweep its own level.

    FVGs use the research script's three-candle definition. A touched gap is
    marked mitigated and is no longer scored; a close through it invalidates it.
    """
    length, step = config.pivot_length, TIMEFRAMES[config.entry_timeframe]
    events, pivots, zones = [], [], []
    trend = None
    broken = set()
    consumed = set()
    for index, current in enumerate(bars):
        # Add newly confirmed pivots only after evaluating the current event.
        # Consequently no current bar can create the level it allegedly swept.
        for pivot_index, kind, level, available in pivots:
            if available >= current.time + step:
                continue
            side = "SELL" if kind == "HIGH" else "BUY"
            swept = current.high > level and current.close < level if side == "SELL" else current.low < level and current.close > level
            if swept:
                consumed.add((pivot_index, kind))
                penetration = current.high-level if side == "SELL" else level-current.low
                events.append(StructureEvent("SWEEP", side, level, bars[pivot_index].time,
                                             current.time+step, penetration/max(atr, 1e-12)))
            direction = "BUY" if kind == "HIGH" else "SELL"
            crossed = current.close > level if direction == "BUY" else current.close < level
            identifier = (pivot_index, kind)
            if crossed and identifier not in broken:
                broken.add(identifier)
                kind_name = "MSS" if trend is not None and direction != trend else "BOS"
                strength = abs(current.close-level)/max(atr, 1e-12)
                if abs(current.close-current.open)/max(atr, 1e-12) >= config.min_displacement_atr:
                    events.append(StructureEvent(kind_name, direction, level, bars[pivot_index].time, current.time+step, strength))
                    trend = direction
        pivot_index = index-length
        if pivot_index >= length:
            window = bars[pivot_index-length:index+1]
            candidate = bars[pivot_index]
            if candidate.high == max(bar.high for bar in window):
                pivots.append((pivot_index, "HIGH", candidate.high, current.time+step))
            if candidate.low == min(bar.low for bar in window):
                pivots.append((pivot_index, "LOW", candidate.low, current.time+step))
        if index >= 2:
            first = bars[index-2]
            side = "BUY" if current.low > first.high else "SELL" if current.high < first.low else None
            if side:
                low, high = (first.high, current.low) if side == "BUY" else (current.high, first.low)
                later = bars[index+1:]
                invalid = any(bar.close < low if side == "BUY" else bar.close > high for bar in later)
                touched = any(bar.low <= high if side == "BUY" else bar.high >= low for bar in later)
                status = "invalidated" if invalid else "expired" if len(later) > config.zone_expiry_bars else "mitigated" if touched else "active"
                zones.append(Zone("FVG", side, low, high, current.time+step, status))
    if bars:
        for side in ("BUY", "SELL"):
            block = find_local_order_block(bars, len(bars)-1, side, pip, config.zone_expiry_bars,
                                          config.zone_expiry_bars, "body", max(atr/pip*.25, .1))
            if block:
                zones.append(Zone("OB", side, block["low"], block["high"], bars[-1].time+step, "active"))
    confirmed = [level for _, _, level, _ in pivots]
    levels = tuple(sorted(set(level for index, kind, level, _ in pivots
                              if (index, kind) not in broken | consumed)))
    low = min(confirmed) if confirmed else None
    high = max(confirmed) if confirmed else None
    zone = "UNAVAILABLE"
    if low is not None and high is not None and low < high and bars:
        midpoint = (low+high)/2
        zone = "DISCOUNT" if bars[-1].close < midpoint else "PREMIUM" if bars[-1].close > midpoint else "EQUILIBRIUM"
    return StructureContext(tuple(events), tuple(zones), levels, low, high, zone)
