"""Causal direction advice with explicit update cadence and recency weighting."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from src.strategy.cost_aware_agent import month_start


@dataclass(frozen=True)
class AdviceConfig:
    """Fixed research parameters; none may alter risk sizing or broker protection."""

    cadence: str = "monthly"
    lookback_days: int = 180
    minimum_trades: int = 8
    half_life_days: float | None = None

    def __post_init__(self):
        if self.cadence not in {"monthly", "weekly"}:
            raise ValueError("Cadence must be monthly or weekly")
        for value in (self.lookback_days, self.minimum_trades):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("Positive whole lookback and sample size required")
        if self.half_life_days is not None and (not math.isfinite(self.half_life_days) or self.half_life_days <= 0):
            raise ValueError("Half life must be finite and positive")


@dataclass(frozen=True)
class DirectionAdvice:
    """Evidence and allowed side, frozen until the next declared update boundary."""

    fitted_at: int
    allowed_sides: tuple[str, ...]
    counts: tuple[int, int]
    mean_net_r: tuple[float | None, float | None]
    last_training_exit: int | None


def update_boundary(timestamp: int, config: AdviceConfig) -> int:
    """Use UTC month start or Monday00:00, independent of machine timezone."""
    if config.cadence == "monthly":
        return month_start(timestamp)
    now = datetime.fromtimestamp(timestamp, timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight-timedelta(days=now.weekday())).timestamp())


def fit_advice(outcomes, timestamp: int, config: AdviceConfig):
    """Rank positive sides using only fully closed outcomes before update time."""
    boundary = update_boundary(timestamp, config)
    after = boundary-config.lookback_days*86400
    available = [o for o in outcomes if after <= o.exited_at < boundary]
    counts, means, allowed = [], [], []
    for side in ("BUY", "SELL"):
        rows = [o for o in available if o.side == side]
        counts.append(len(rows))
        if config.half_life_days is None:
            mean = math.fsum(o.net_r for o in rows)/len(rows) if rows else None
        else:
            weights = [2**(-(boundary-o.exited_at)/(86400*config.half_life_days)) for o in rows]
            total = math.fsum(weights)
            mean = math.fsum(o.net_r*w for o, w in zip(rows, weights))/total if total else None
        means.append(mean)
        if len(rows) >= config.minimum_trades and mean is not None and mean > 0:
            allowed.append(side)
    if allowed:
        allowed = [min(allowed, key=lambda s: (-means[("BUY", "SELL").index(s)], s))]
    return DirectionAdvice(boundary, tuple(allowed), tuple(counts), tuple(means),
        max((o.exited_at for o in available), default=None))
