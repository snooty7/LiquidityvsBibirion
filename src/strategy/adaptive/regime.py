"""Explainable regime classification using past-only indicator observations."""
import math
from statistics import pstdev

from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.models import Candle, Regime, RegimeResult
from src.strategy.filters import ema
from src.strategy.liquidity import _adx_value


def _closed_atrs(bars: tuple[Candle, ...], period: int) -> list[float]:
    """Seed ATR with a mean of actual transitions, never an unknown first TR.

    First output belongs to bars[period]; every input TR has a prior close.
    Subsequent values use the same period's Wilder recurrence.
    """
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


def detect_regime(bars: tuple[Candle, ...], config: AdaptiveConfig) -> RegimeResult:
    """Classify a fixed closed window; ATR excludes the unobservable first transition."""
    if len(bars) < config.lookback:
        return RegimeResult(Regime.UNCERTAIN, 0, 0, 0, 0, 0, "insufficient_context")
    bars = bars[-config.lookback:]
    if any(not all(math.isfinite(value) and value > 0 for value in (bar.open, bar.high, bar.low, bar.close))
           or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
           for bar in bars):
        return RegimeResult(Regime.UNCERTAIN, 0, 0, 0, 0, 0, "invalid_context")
    atrs = _closed_atrs(bars, config.atr_period)
    if not all(math.isfinite(value) for value in atrs):
        return RegimeResult(Regime.UNCERTAIN, 0, 0, 0, 0, 0, "invalid_indicators")
    atr = atrs[-1]
    reference = atrs[:-1]
    # Treat numerical noise in a constant ATR as a tie, not a new volatility high.
    percentile = sum(value < atr and not math.isclose(value, atr, rel_tol=1e-6)
                     for value in reference) / len(reference) if reference else 0.0
    adx = _adx_value(bars, config.adx_period)
    closes = [bar.close for bar in bars]
    ratios = [b/a for a, b in zip(closes[-21:-1], closes[-20:])]
    if not math.isfinite(adx) or not all(math.isfinite(value) and value > 0 for value in ratios):
        return RegimeResult(Regime.UNCERTAIN, 0, 0, 0, 0, 0, "invalid_indicators")
    volatility = pstdev([math.log(value) for value in ratios])
    momentum = (closes[-1]-closes[-6])/atr if atr > 0 else 0.0
    recent, prior = bars[-10:], bars[-20:-10]
    bullish_structure = max(bar.high for bar in recent) > max(bar.high for bar in prior) and min(bar.low for bar in recent) > min(bar.low for bar in prior)
    bearish_structure = max(bar.high for bar in recent) < max(bar.high for bar in prior) and min(bar.low for bar in recent) < min(bar.low for bar in prior)
    fast, slow = ema(closes, 20), ema(closes, 50)
    if atr <= 0:
        regime, reason = Regime.UNCERTAIN, "zero_atr"
    elif percentile >= config.high_atr_percentile or volatility >= config.high_realized_volatility:
        regime, reason = Regime.HIGH_VOLATILITY, "extreme_atr_or_realized_volatility"
    elif adx >= config.trend_adx and closes[-1] > fast[-1] > slow[-1] and slow[-1] > slow[-4] and momentum > 0 and bullish_structure:
        regime, reason = Regime.TRENDING_BULLISH, "adx_ema_channel_structure_momentum_up"
    elif adx >= config.trend_adx and closes[-1] < fast[-1] < slow[-1] and slow[-1] < slow[-4] and momentum < 0 and bearish_structure:
        regime, reason = Regime.TRENDING_BEARISH, "adx_ema_channel_structure_momentum_down"
    elif adx <= config.range_adx and abs(momentum) < 1 and max(closes[-20:])-min(closes[-20:]) <= 4*atr:
        regime, reason = Regime.RANGING, "low_adx_bounded_range"
    else:
        regime, reason = Regime.UNCERTAIN, "conflicting_indicators"
    return RegimeResult(regime, atr, adx, percentile, volatility, momentum, reason)
