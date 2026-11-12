"""Explainable regime classification using past-only indicator observations."""
import math
from statistics import pstdev

from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.models import Candle, Regime, RegimeResult
from src.strategy.filters import ema
from src.strategy.liquidity import _atr_series, _adx_value


def detect_regime(bars: tuple[Candle, ...], config: AdaptiveConfig) -> RegimeResult:
    """Reuse legacy ATR/ADX smoothing, without claiming a new Wilder implementation."""
    if len(bars) < config.lookback:
        return RegimeResult(Regime.UNCERTAIN, 0, 0, 0, 0, 0, "insufficient_context")
    atrs = _atr_series(bars, config.atr_period)
    atr = atrs[-1]
    reference = atrs[config.atr_period:-1]
    # Treat numerical noise in a constant ATR as a tie, not a new volatility high.
    percentile = sum(value < atr and not math.isclose(value, atr, rel_tol=1e-6)
                     for value in reference) / len(reference) if reference else 0.0
    adx = _adx_value(bars, config.adx_period)
    closes = [bar.close for bar in bars]
    volatility = pstdev([math.log(b/a) for a, b in zip(closes[-21:-1], closes[-20:])])
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
