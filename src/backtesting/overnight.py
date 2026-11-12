"""Explicit offline exit policy; never changes a live configuration."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class OvernightPolicy:
    """Flatten selected sides five minutes before broker midnight.

    Close on the first available bar open at/after the deadline. Missing quotes
    never produce a fabricated pre-rollover fill; incurred swap remains payable.
    Entries are blocked from the deadline until midnight to prevent re-entry.
    """

    sides: tuple[str, ...] = ("BUY", "SELL")
    timezone: str = "Etc/GMT-3"
    minutes_before: int = 5

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if not self.sides or any(s not in {"BUY", "SELL"} for s in self.sides):
            raise ValueError("Policy must specify BUY and/or SELL")
        if isinstance(self.minutes_before, bool) or not isinstance(self.minutes_before, int) or not 1 <= self.minutes_before < 1440:
            raise ValueError("Cutoff must be between 1 and 1439 whole minutes")

    def deadline(self, entry_time: int) -> int:
        """Get the first midnight deadline after entry in the declared broker clock."""
        zone = ZoneInfo(self.timezone)
        day = datetime.fromtimestamp(entry_time, zone).date() + timedelta(days=1)
        return int((datetime.combine(day, time(), zone)-timedelta(minutes=self.minutes_before)).timestamp())

    def blocks_entry(self, side: str, timestamp: int) -> bool:
        """Block affected sides during the pre-midnight closing interval."""
        return side in self.sides and timestamp >= self.deadline(timestamp)

    def exit_due(self, side: str, entry_time: int, timestamp: int) -> bool:
        """Keep overdue positions due even if a market gap crosses midnight."""
        return side in self.sides and timestamp >= self.deadline(entry_time)
