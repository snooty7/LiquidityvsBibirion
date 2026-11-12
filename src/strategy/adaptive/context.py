"""Causal, closed-only snapshots with explicit missing/stale/gapped observations."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math

from src.backtesting.history import TIMEFRAMES
from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.models import Candle, MarketSnapshot
from src.strategy.filters import evaluate_bias


def snapshot(symbol: str, decision_time: int, rates: dict, config: AdaptiveConfig, *,
             additional_timeframes: tuple[str, ...] = (), lookbacks: dict[str, int] | None = None) -> MarketSnapshot:
    """Ignore future/forming rows before validating; never let them alter past features.

    D1 is an explicit UTC calendar. Native non-UTC daily bars must be converted
    by a separate session-aware importer rather than relabeled as UTC.
    """
    series, reasons = [], []
    lookbacks = lookbacks or {}
    for timeframe in dict.fromkeys((config.entry_timeframe, *config.context_timeframes, *additional_timeframes)):
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unknown additional timeframe")
        count = lookbacks.get(timeframe, config.lookback)
        if type(count) is not int or count < config.lookback:
            raise ValueError("Provenance lookbacks cannot reduce the configured warmup")
        step = TIMEFRAMES[timeframe]
        bars = []
        previous = None
        try:
            rows = []
            for row in rates.get(timeframe, ()):
                if type(row["time"]) is not int:
                    raise ValueError("invalid_timestamp")
                if row["time"] + step <= decision_time:
                    rows.append(row)
            selected = rows[-count:]
            for position, row in enumerate(selected):
                bar = Candle(**{name: row[name] for name in ("time", "open", "high", "low", "close")},
                             tick_volume=float(row.get("tick_volume", 0)) if isinstance(row, dict) else float(row["tick_volume"]))
                if (type(bar.time) is not int or bar.time % step or
                        not all(math.isfinite(v) and v > 0 for v in (bar.open, bar.high, bar.low, bar.close)) or
                        not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high or
                        not math.isfinite(bar.tick_volume) or bar.tick_volume < 0):
                    raise ValueError("invalid_bar")
                if previous is not None and bar.time != previous + step:
                    if bar.time <= previous:
                        raise ValueError("gapped_or_unordered")
                    weekend_gap = (config.allow_utc_weekend_gaps and bar.time > previous
                                   and bar.time-previous <= 3*86400
                                   and all(datetime.fromtimestamp(t, timezone.utc).weekday() >= 5
                                           for t in range(previous+step, bar.time, step)))
                    # Extended provenance is not a larger indicator window.
                    # Its actually used pivot/consumption/ATR intervals are
                    # checked by align_signal; unrelated older gaps cannot erase
                    # an otherwise complete fixed-window feature series.
                    older_provenance = count > config.lookback and position <= len(selected)-config.lookback
                    if not weekend_gap and not older_provenance:
                        raise ValueError("gapped_or_unordered")
                previous = bar.time
                bars.append(bar)
            if len(bars) < count:
                raise ValueError("insufficient_bars")
            if decision_time - (bars[-1].time + step) > config.max_age_bars * step:
                raise ValueError("stale_bars")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reasons.append(f"{timeframe}:{exc}")
            bars = []
        series.append((timeframe, tuple(bars)))
    payload = [(tf, [asdict(bar) for bar in bars]) for tf, bars in series]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return MarketSnapshot(symbol, decision_time, tuple(series), digest, tuple(reasons))


def directions(context: MarketSnapshot, config: AdaptiveConfig) -> tuple[tuple[str, str], ...]:
    """Higher-timeframe bias from the same EMA definition as the existing bot."""
    result = []
    for timeframe in config.context_timeframes:
        bars = context.bars(timeframe)[-config.lookback:]
        if len(bars) < config.lookback or any(not math.isfinite(bar.close) or bar.close <= 0 for bar in bars):
            result.append((timeframe, "UNCERTAIN"))
            continue
        bias = evaluate_bias(bars, 20)
        result.append((timeframe, "BUY" if bias["ok_buy"] else "SELL" if bias["ok_sell"] else "UNCERTAIN"))
    return tuple(result)


def timeframe_block_reasons(alignment: tuple[tuple[str, str], ...], side: str | None,
                            required: tuple[str, ...]) -> tuple[str, ...]:
    """Keep unanimous alignment mandatory; distinguish uncertainty from opposition."""
    if side not in {"BUY", "SELL"}:
        return ("timeframe_candidate_side_unavailable",)
    lookup = dict(alignment)
    if len(lookup) != len(alignment) or set(lookup) != set(required):
        return ("timeframe_context_invalid",)
    reasons = []
    for timeframe in required:
        direction = lookup[timeframe]
        if direction not in {"BUY", "SELL"}:
            reasons.append(f"timeframe_uncertain:{timeframe}")
        elif direction != side:
            reasons.extend(("timeframe_conflict", f"timeframe_conflict:{timeframe}"))
    return tuple(dict.fromkeys(reasons))
