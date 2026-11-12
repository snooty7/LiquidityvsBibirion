"""Shared causal adaptive indicators; legacy strategy implementations stay intact."""
import math

from src.strategy.adaptive.models import Candle


def closed_atr_series(bars: tuple[Candle, ...], period: int) -> list[float]:
    """Seed from actual transitions; first output belongs to bars[period]."""
    if type(period) is not int or period < 2:
        raise ValueError("ATR period must be an integer >= 2")
    ranges = [max(bar.high-bar.low, abs(bar.high-previous.close), abs(bar.low-previous.close))
              for previous, bar in zip(bars, bars[1:])]
    if len(ranges) < period:
        return []
    running = math.fsum(value/period for value in ranges[:period])
    result = [running]
    for value in ranges[period:]:
        running = running*((period-1)/period)+value/period
        result.append(running)
    return result
