"""Pure monthly direction adviser; has no execution or broker dependencies."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math


@dataclass(frozen=True)
class ClosedOutcome:
    """One fully known shadow-reference result, normalized by initial price risk."""

    exited_at: int
    side: str
    net_r: float

    def __post_init__(self):
        if self.side not in {"BUY", "SELL"} or not math.isfinite(self.net_r):
            raise ValueError("Finite outcome and valid side required")


@dataclass(frozen=True)
class MonthlyAdvice:
    """Frozen permission for a UTC calendar month and its auditable evidence."""

    fitted_at: int
    allowed_sides: tuple[str, ...]
    counts: tuple[int, int]
    mean_net_r: tuple[float | None, float | None]
    last_training_exit: int | None


def month_start(timestamp: int) -> int:
    """Get current UTC month boundary without reading future prices."""
    now = datetime.fromtimestamp(timestamp, timezone.utc)
    return int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())


def fit_month(outcomes, timestamp: int, *, best_only=False, lookback_days=180, minimum_trades=8):
    """Fit on exits strictly before month start; insufficient/nonpositive sides stay off.

    Shadow-reference trades must include all execution and financing costs.
    This is an exploratory sample-mean adviser, not a probabilistic forecast.
    """
    if lookback_days <= 0 or minimum_trades < 1:
        raise ValueError("Positive lookback and sample size required")
    boundary = month_start(timestamp)
    after = boundary-int(timedelta(days=lookback_days).total_seconds())
    available = [o for o in outcomes if after <= o.exited_at < boundary]
    counts, means, allowed = [], [], []
    for side in ("BUY", "SELL"):
        values = [o.net_r for o in available if o.side == side]
        counts.append(len(values))
        mean = math.fsum(values)/len(values) if values else None
        means.append(mean)
        if len(values) >= minimum_trades and mean > 0:
            allowed.append(side)
    if best_only and allowed:
        allowed = [min(allowed, key=lambda side: (-means[("BUY", "SELL").index(side)], side))]
    return MonthlyAdvice(boundary, tuple(allowed), tuple(counts), tuple(means),
                         max((o.exited_at for o in available), default=None))
