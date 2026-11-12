"""Verify a pending sweep and its actual lower-timeframe confirmation causally."""
import math
from datetime import datetime, timezone

from src.backtesting.history import TIMEFRAMES
from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.indicators import closed_atr_series
from src.strategy.adaptive.models import AlignedEvidence, Candle, MarketSnapshot, SignalAnchor, StructureEvent
from src.strategy.confirmations import evaluate_sweep_displacement_mss_confirmation
from src.strategy.liquidity import (SweepSignal, detect_sweep_signal,
                                    evaluate_sweep_significance, extract_pivot_levels)


def _contiguous(bars, step: int, allow_weekends: bool) -> bool:
    for before, after in zip(bars, bars[1:]):
        if after.time == before.time+step:
            continue
        if (not allow_weekends or after.time <= before.time or after.time-before.time > 3*86400 or
                not all(datetime.fromtimestamp(t, timezone.utc).weekday() >= 5
                        for t in range(before.time+step, after.time, step))):
            return False
    return True


def align_signal(context: MarketSnapshot, anchor: SignalAnchor, config: AdaptiveConfig) -> AlignedEvidence:
    """Never rediscover/substitute a different setup or credit a pre-close break.

    A pivot must have been confirmed before the sweep opens and belong to the
    baseline's ranked source map at creation. That map does not retire on wicks.
    """
    if anchor.signal_timeframe != config.entry_timeframe or anchor.side not in {"BUY", "SELL"}:
        return AlignedEvidence(None, None, ("anchor_identity_mismatch",))
    if (anchor.confirmation_timeframe not in TIMEFRAMES or
            any(type(value) is not int for value in (anchor.candle_time, anchor.expires_at, anchor.pivot_length,
                                                    anchor.structure_bars, anchor.significance_lookback,
                                                    anchor.max_levels, anchor.source_lookback)) or
            not all(math.isfinite(value) for value in (anchor.level, anchor.buffer_price,
                anchor.significance_range_multiple, anchor.minimum_penetration_price,
                anchor.displacement_body_ratio_min, anchor.displacement_range_multiple)) or
            anchor.level <= 0 or anchor.pivot_length < 1 or anchor.structure_bars < 1 or anchor.significance_lookback < 2 or
            anchor.max_levels < 1 or anchor.source_lookback < 2*anchor.pivot_length+1 or
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
    # Reconstruct creation-time history, not a truncated/different map at entry.
    creation_history = bars[:index+1]
    bars = creation_history[-anchor.source_lookback:]
    if len(bars) < anchor.source_lookback:
        return AlignedEvidence(None, None, ("anchor_source_history_unavailable",))
    index = len(bars)-1
    sweep_bar = bars[index]
    swept = (sweep_bar.low < anchor.level-anchor.buffer_price and sweep_bar.close > anchor.level
             if anchor.side == "BUY" else sweep_bar.high > anchor.level+anchor.buffer_price and sweep_bar.close < anchor.level)
    if not swept:
        return AlignedEvidence(None, None, ("anchor_not_a_sweep",))
    length = anchor.pivot_length
    proven = []
    gapped = False
    for pivot in range(length, index-length):
        bar = bars[pivot]
        window = bars[pivot-length:pivot+length+1]
        kinds = [kind for kind, level, extremum in (
            ("LOW", bar.low, min(item.low for item in window)),
            ("HIGH", bar.high, max(item.high for item in window)))
            if math.isclose(level, anchor.level, rel_tol=0, abs_tol=1e-10) and level == extremum]
        if not kinds:
            continue
        if not _contiguous(bars[pivot-length:index+1], step, config.allow_utc_weekend_gaps):
            gapped = True
            continue
        proven.append((pivot, kinds[0]))
    if not proven:
        reason = "anchor_level_history_gapped" if gapped else "anchor_level_not_confirmed"
        return AlignedEvidence(None, None, (reason,))
    close = sweep_bar.close
    source = [*bars, Candle(sweep_bar.time+step, close, close, close, close)]
    levels = extract_pivot_levels(source, anchor.pivot_length, anchor.max_levels)
    if not any(math.isclose(level, anchor.level, rel_tol=0, abs_tol=1e-10) for level in levels):
        return AlignedEvidence(None, None, ("anchor_level_not_active",))
    selected = detect_sweep_signal(source, levels, anchor.buffer_price)
    if (selected is None or selected.side != anchor.side or selected.candle_time != anchor.candle_time or
            not math.isclose(selected.level, anchor.level, rel_tol=0, abs_tol=1e-10)):
        return AlignedEvidence(None, None, ("anchor_source_signal_mismatch",))
    quality = evaluate_sweep_significance(
        bars, SweepSignal(anchor.side, anchor.level, anchor.candle_time),
        lookback_bars=anchor.significance_lookback,
        min_range_multiple=anchor.significance_range_multiple,
        min_penetration_price=anchor.minimum_penetration_price)
    if not quality.valid:
        return AlignedEvidence(None, None, (f"anchor_quality:{quality.note}",))
    signal_history = creation_history[-config.lookback:]
    if len(signal_history) < config.lookback or not _contiguous(signal_history, step, config.allow_utc_weekend_gaps):
        return AlignedEvidence(None, None, ("sweep_atr_history_unavailable",))
    signal_atr = closed_atr_series(signal_history, config.atr_period)[-1]
    if not math.isfinite(signal_atr) or signal_atr <= 0:
        return AlignedEvidence(None, None, ("sweep_atr_unavailable",))
    penetration = anchor.level-sweep_bar.low if anchor.side == "BUY" else sweep_bar.high-anchor.level
    pivot, kind = proven[-1]
    crossings = sum(item.low < anchor.level if anchor.side == "BUY" else item.high > anchor.level
                    for item in bars[pivot+length+1:index])
    sweep = StructureEvent("SWEEP", anchor.side, anchor.level, bars[pivot].time,
                           available, penetration/signal_atr, anchor.signal_timeframe, kind,
                           "baseline_ranked_rolling_pivots", crossings, penetration, signal_atr)
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
        if not _contiguous(history, lower_step, config.allow_utc_weekend_gaps):
            return AlignedEvidence(sweep, None, ("confirmation_atr_history_gapped",))
        atr = closed_atr_series(history, config.atr_period)[-1]
        if not math.isfinite(atr) or atr <= 0 or abs(current.close-current.open)/atr < config.min_displacement_atr:
            continue
        event = StructureEvent("CONFIRMATION_BREAK", anchor.side, level, previous[-1].time,
                               current.time+lower_step, abs(current.close-level)/atr, anchor.confirmation_timeframe,
                               raw_move=abs(current.close-level), normalization_atr=atr)
        return AlignedEvidence(sweep, event, ())
    return AlignedEvidence(sweep, None, ("no_post_sweep_confirmation",))
