"""Strict immutable configuration, separate from existing strategy defaults."""
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math


@dataclass(frozen=True)
class AdaptiveConfig:
    """Experimental parameters; enabling observation never authorizes live execution."""

    enabled: bool = False
    dynamic_leverage: bool = False
    hedging: bool = False
    ml_shadow: bool = False
    entry_timeframe: str = "M5"
    context_timeframes: tuple[str, ...] = ("H1", "H4")
    lookback: int = 100
    max_age_bars: int = 2
    allow_utc_weekend_gaps: bool = False
    pivot_length: int = 3
    sweep_expiry_bars: int = 8
    zone_expiry_bars: int = 20
    atr_period: int = 14
    adx_period: int = 14
    trend_adx: float = 25.0
    range_adx: float = 18.0
    high_atr_percentile: float = 0.98
    high_realized_volatility: float = 0.01
    min_displacement_atr: float = 0.5
    min_rr: float = 1.5
    stop_atr_buffer: float = 0.15
    score_threshold: float = 0.65
    weights: tuple[float, ...] = (0.30, 0.25, 0.20, 0.15, 0.10)
    require_order_flow: bool = False
    currency_cap_pct: float = 0.5
    correlation_cap_pct: float = 0.5
    break_even_r: float = 0.0
    trailing_activation_r: float = 0.0
    trailing_gap_r: float = 1.0
    partial_exit_r: float = 0.0
    partial_exit_fraction: float = 0.5

    def __post_init__(self) -> None:
        """Reject unsupported activation and invalid numeric settings eagerly."""
        from src.backtesting.history import TIMEFRAMES

        for name in ("enabled", "dynamic_leverage", "hedging", "ml_shadow", "require_order_flow", "allow_utc_weekend_gaps"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if self.dynamic_leverage or self.hedging:
            raise ValueError("Dynamic leverage and hedging are unsupported and must remain disabled")
        for name in ("lookback", "max_age_bars", "pivot_length", "sweep_expiry_bars", "zone_expiry_bars", "atr_period", "adx_period"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.atr_period < 2 or self.adx_period < 2 or self.lookback < max(4*self.atr_period, 4*self.adx_period, 2*self.pivot_length+5):
            raise ValueError("Insufficient fixed indicator/structure warmup")
        if self.entry_timeframe not in TIMEFRAMES or not self.context_timeframes or len(set(self.context_timeframes)) != len(self.context_timeframes):
            raise ValueError("Invalid timeframes")
        if any(tf not in TIMEFRAMES or TIMEFRAMES[tf] <= TIMEFRAMES[self.entry_timeframe] for tf in self.context_timeframes):
            raise ValueError("Context timeframes must be higher than entry")
        if len(self.weights) != 5 or any(not math.isfinite(v) or v < 0 for v in self.weights) or not math.isclose(sum(self.weights), 1.0):
            raise ValueError("Five finite nonnegative weights must sum to one")
        numeric = (self.trend_adx, self.range_adx, self.high_atr_percentile, self.high_realized_volatility,
                   self.min_displacement_atr, self.min_rr, self.stop_atr_buffer, self.score_threshold,
                   self.currency_cap_pct, self.correlation_cap_pct, self.break_even_r,
                   self.trailing_activation_r, self.trailing_gap_r, self.partial_exit_r, self.partial_exit_fraction)
        if not all(math.isfinite(v) for v in numeric):
            raise ValueError("Adaptive parameters must be finite")
        if not 0 <= self.score_threshold <= 1 or not 0 < self.high_atr_percentile <= 1 or not 0 <= self.range_adx < self.trend_adx <= 100:
            raise ValueError("Invalid score or regime thresholds")
        if min(self.high_realized_volatility, self.min_rr, self.currency_cap_pct, self.correlation_cap_pct) <= 0 or min(self.min_displacement_atr, self.stop_atr_buffer, self.break_even_r, self.trailing_activation_r, self.trailing_gap_r, self.partial_exit_r) < 0 or not 0 < self.partial_exit_fraction < 1:
            raise ValueError("Invalid risk or exit settings")

    def digest(self) -> str:
        """Fingerprint the effective settings for audit records."""
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, allow_nan=False).encode()).hexdigest()


def load_adaptive(raw: dict) -> AdaptiveConfig:
    """Reject unknown fields and normalize JSON arrays into immutable tuples."""
    if not isinstance(raw, dict) or set(raw) - {item.name for item in fields(AdaptiveConfig)}:
        raise ValueError("Unknown adaptive configuration fields")
    values = dict(raw)
    for key in ("context_timeframes", "weights"):
        if key in values:
            values[key] = tuple(values[key])
    return AdaptiveConfig(**values)
