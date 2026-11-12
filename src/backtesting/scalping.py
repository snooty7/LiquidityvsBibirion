"""Causal intraday holding limits for offline scalping experiments."""
from dataclasses import dataclass
from datetime import datetime, time, timezone


@dataclass(frozen=True)
class ScalpPolicy:
    """Trade both sides during UTC daytime; never invent a fill through a quote gap."""

    max_minutes: int
    entry_start_hour: int = 5
    entry_end_hour: int = 18
    flat_hour: int = 19
    sides: tuple = ("BUY", "SELL")
    exit_reason: str = "scalp_time_exit"

    def __post_init__(self):
        if isinstance(self.max_minutes, bool) or not isinstance(self.max_minutes, int) or not 1 <= self.max_minutes <= 60:
            raise ValueError("Scalp duration must be 1 to 60 whole minutes")
        if not 0 <= self.entry_start_hour < self.entry_end_hour < self.flat_hour <= 19:
            raise ValueError("Entries and flattening must finish before evening financing")
        if set(self.sides) != {"BUY", "SELL"}:
            raise ValueError("No-overnight scalping must cover both sides")

    def deadline(self, entry_time: int) -> int:
        """Use elapsed wall-clock minutes, not a count of available candles."""
        date = datetime.fromtimestamp(entry_time, timezone.utc).date()
        flat = int(datetime.combine(date, time(self.flat_hour), timezone.utc).timestamp())
        return min(entry_time+self.max_minutes*60, flat)

    def blocks_entry(self, side: str, timestamp: int) -> bool:
        """Allow only weekday daytime entries; original strategy sessions still apply."""
        now = datetime.fromtimestamp(timestamp, timezone.utc)
        return side not in self.sides or now.weekday() >= 5 or not self.entry_start_hour <= now.hour < self.entry_end_hour

    def exit_due(self, side: str, entry_time: int, timestamp: int) -> bool:
        """An overdue position remains due after a missing-quote or weekend gap."""
        return side in self.sides and timestamp >= self.deadline(entry_time)
