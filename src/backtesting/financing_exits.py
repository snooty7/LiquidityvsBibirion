"""Offline financing hypotheses, using the existing scheduled-exit fill path."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import lru_cache
from math import isfinite
from zoneinfo import ZoneInfo

from src.backtesting.overnight import OvernightPolicy


@dataclass(frozen=True)
class FinancingExitPolicy(OvernightPolicy):
    """Allow ordinary carry, but exit before a declared financing budget expires."""

    mode: str = "triple_only"
    charge_weights: tuple[float, ...] = (1, 1, 3, 1, 1, 0, 0)

    def __post_init__(self):
        super().__post_init__()
        if self.mode not in {"triple_only", "one_unit"}:
            raise ValueError("Unknown financing exit mode")
        if len(self.charge_weights) != 7 or any(not isfinite(w) or w < 0 or 0 < w < 1 for w in self.charge_weights):
            raise ValueError("Seven nonnegative weekday weights, with positive weights >=1, required")
        if sum(self.charge_weights) == 0 or (self.mode == "triple_only" and max(self.charge_weights) <= 1):
            raise ValueError("Financing schedule cannot reach the selected deadline")

    @property
    def exit_reason(self):
        """Identify this research exit in the ordinary trade ledger."""
        return "triple_swap_exit" if self.mode == "triple_only" else "carry_budget_exit"

    @lru_cache(maxsize=4096)
    def deadline(self, entry_time: int) -> int:
        """Use only entry time and declared schedule; never future market prices."""
        zone = ZoneInfo(self.timezone)
        day = datetime.fromtimestamp(entry_time, zone).date() + timedelta(days=1)
        units = 0.0
        for _ in range(15):
            weight = self.charge_weights[(day-timedelta(days=1)).weekday()]
            units += weight
            if (self.mode == "triple_only" and weight > 1) or (self.mode == "one_unit" and units > 1):
                return int((datetime.combine(day, time(), zone)-timedelta(minutes=self.minutes_before)).timestamp())
            day += timedelta(days=1)
        raise ValueError("Financing deadline not reached within two weekly cycles")


@dataclass(frozen=True)
class LateSellEntryPolicy(OvernightPolicy):
    """Inherit pre-midnight entry blackout, leaving all existing positions alone."""

    minutes_before: int = 90

    def exit_due(self, side: str, entry_time: int, timestamp: int) -> bool:
        """This hypothesis changes entries only."""
        return False
