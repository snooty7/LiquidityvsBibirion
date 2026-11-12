"""Verify a pending sweep and its actual lower-timeframe confirmation causally."""
import math

from src.backtesting.history import TIMEFRAMES
from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.models import AlignedEvidence, MarketSnapshot, SignalAnchor, StructureEvent
from src.strategy.confirmations import evaluate_sweep_displacement_mss_confirmation
from src.strategy.liquidity import SweepSignal, _atr_series, evaluate_sweep_significance


def align_signal(context: MarketSnapshot, anchor: SignalAnchor, config: AdaptiveConfig) -> AlignedEvidence:
    """Never rediscover/substitute a different setup or credit a pre-close break.

    A pivot must have been confirmed before the sweep opens. Taken liquidity is
    not replenished unless a later confirmed pivot establishes that level anew.
    """
    if anchor.signal_timeframe != config.entry_timeframe or anchor.side not in {"BUY", "SELL"}:
        return AlignedEvidence(None, None, ("anchor_identity_mismatch",))
    if (anchor.confirmation_timeframe not in TIMEFRAMES or
            any(type(value) is not int for value in (anchor.candle_time, anchor.expires_at, anchor.pivot_length,
                                                    anchor.structure_bars, anchor.significance_lookback)) or
            not all(math.isfinite(value) for value in (anchor.level, anchor.buffer_price,
                anchor.significance_range_multiple, anchor.minimum_penetration_price,
                anchor.displacement_body_ratio_min, anchor.displacement_range_multiple)) or
            anchor.level <= 0 or anchor.pivot_length < 1 or anchor.structure_bars < 1 or anchor.significance_lookback < 2 or
            min(anchor.buffer_price, anchor.minimum_penetration_price) < 0 or
            min(anchor.significance_range_multiple, anchor.displacement_range_multiple) <= 0 or
            not 0 <= anchor.displacement_body_ratio_min <= 1):
        return AlignedEvidence(None, None, ("invalid_anchor",))
    step = TIMEFRAMES[anchor.signal_timeframe]
    available = anchor.candle_time+step
    if available > context.decision_time:
        return AlignedEvidence(None, None, ("anchor_not_closed",))
    if context.decision_time >= anchor.expires_at or context.decision_time-available > config.sweep_expiry_bars*step:
        return AlignedEvidence(None, None, ("anchor_expired",))
    bars = context.bars(anchor.signal_timeframe)
    index = next((i for i, bar in enumerate(bars) if bar.time == anchor.candle_time), None)
    if index is None:
        return AlignedEvidence(None, None, ("anchor_bar_unavailable",))
    sweep_bar = bars[index]
    swept = (sweep_bar.low < anchor.level-anchor.buffer_price and sweep_bar.close > anchor.level
             if anchor.side == "BUY" else sweep_bar.high > anchor.level+anchor.buffer_price and sweep_bar.close < anchor.level)
    if not swept:
        return AlignedEvidence(None, None, ("anchor_not_a_sweep",))
    length = anchor.pivot_length
    confirmed, untaken = [], []
    for pivot in range(length, index-length):
        bar = bars[pivot]
        window = bars[pivot-length:pivot+length+1]
        level = bar.low if anchor.side == "BUY" else bar.high
        extremum = min(item.low for item in window) if anchor.side == "BUY" else max(item.high for item in window)
        if not math.isclose(level, anchor.level, rel_tol=0, abs_tol=1e-10) or level != extremum:
            continue
        confirmed.append(pivot)
        intervening = bars[pivot+length+1:index]
        if not any(item.low < level if anchor.side == "BUY" else item.high > level for item in intervening):
            untaken.append(pivot)
    if not untaken:
        return AlignedEvidence(None, None, ("anchor_liquidity_already_consumed" if confirmed else "anchor_level_not_confirmed",))
    quality = evaluate_sweep_significance(
        bars, SweepSignal(anchor.side, anchor.level, anchor.candle_time),
        lookback_bars=anchor.significance_lookback,
        min_range_multiple=anchor.significance_range_multiple,
        min_penetration_price=anchor.minimum_penetration_price)
    if not quality.valid:
        return AlignedEvidence(None, None, (f"anchor_quality:{quality.note}",))
    signal_atr = _atr_series(bars[max(0, index+1-config.lookback):index+1], config.atr_period)[-1]
    penetration = anchor.level-sweep_bar.low if anchor.side == "BUY" else sweep_bar.high-anchor.level
    sweep = StructureEvent("SWEEP", anchor.side, anchor.level, bars[untaken[-1]].time,
                           available, penetration/max(signal_atr, 1e-12), anchor.signal_timeframe)
    if anchor.confirmation_mode != "sweep_displacement_mss":
        return AlignedEvidence(sweep, None, ("anchor_confirmation_mode_unsupported",))
    lower = context.bars(anchor.confirmation_timeframe)
    lower_step = TIMEFRAMES[anchor.confirmation_timeframe]
    if any(bar.time+lower_step > context.decision_time for bar in lower):
        return AlignedEvidence(sweep, None, ("confirmation_not_closed",))
    if not lower or context.decision_time-(lower[-1].time+lower_step) > config.max_age_bars*lower_step:
        return AlignedEvidence(sweep, None, ("confirmation_context_stale",))
    # The signal only exists when its sweep closes. Confirmation cannot use an
    # M1 candle that started before that close, even if the baseline counted it.
    after = [bar for bar in lower if bar.time >= available]
    for position in range(max(2, anchor.structure_bars), len(after)):
        prefix = after[:position+1]
        window = prefix[-max(2, anchor.structure_bars)-1:]
        result = evaluate_sweep_displacement_mss_confirmation(
            [*window, window[-1]], anchor.side, available, anchor.structure_bars,
            displacement_body_ratio_min=anchor.displacement_body_ratio_min,
            displacement_range_multiple=anchor.displacement_range_multiple)
        if not result.confirmed:
            continue
        current = prefix[-1]
        previous = prefix[-1-max(2, anchor.structure_bars):-1]
        level = max(bar.high for bar in previous) if anchor.side == "BUY" else min(bar.low for bar in previous)
        history = [bar for bar in lower if bar.time <= current.time][-config.lookback:]
        if len(history) < config.lookback:
            return AlignedEvidence(sweep, None, ("confirmation_atr_warmup_unavailable",))
        atr = _atr_series(history, config.atr_period)[-1]
        if atr <= 0 or abs(current.close-current.open)/atr < config.min_displacement_atr:
            continue
        event = StructureEvent("CONFIRMATION_BREAK", anchor.side, level, previous[-1].time,
                               current.time+lower_step, abs(current.close-level)/atr, anchor.confirmation_timeframe)
        return AlignedEvidence(sweep, event, ())
    return AlignedEvidence(sweep, None, ("no_post_sweep_confirmation",))
