"""Explicit signed financing cash flows for offline replay (never a broker adapter)."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import math
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SwapModel:
    """Account-currency swap per lot and financing day; negative means a debit.

    Weekday weights apply to the day ending at broker midnight. A position
    entered at midnight is charged starting at the following rollover.
    Current broker rates are an assumption, not historical rate observations.
    """

    buy_per_lot: float
    sell_per_lot: float
    timezone: str = "Etc/GMT-3"
    weekday_weights: tuple = (1, 1, 3, 1, 1, 0, 0)
    debit_multiplier: float = 1.0

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if len(self.weekday_weights) != 7 or not all(
            math.isfinite(v) and v >= 0 for v in self.weekday_weights
        ):
            raise ValueError("Seven finite nonnegative weekday weights required")
        if not all(math.isfinite(v) for v in (self.buy_per_lot, self.sell_per_lot)):
            raise ValueError("Swap rates must be finite")
        if not math.isfinite(self.debit_multiplier) or self.debit_multiplier < 1:
            raise ValueError("Debit multiplier must be finite and at least one")

    def events(self, after: int, through: int, side: str, volume: float):
        """Return UTC timestamp/amount pairs in (after, through], without weekend fabrication."""
        if side not in {"BUY", "SELL"} or not math.isfinite(volume) or volume <= 0:
            raise ValueError("Valid side and positive finite volume required")
        zone = ZoneInfo(self.timezone)
        day = datetime.fromtimestamp(after, zone).date() + timedelta(days=1)
        rate = self.buy_per_lot if side == "BUY" else self.sell_per_lot
        while True:
            timestamp = int(datetime.combine(day, time(), zone).timestamp())
            if timestamp > through:
                break
            amount = rate * volume * self.weekday_weights[(day-timedelta(days=1)).weekday()]
            if amount < 0:
                amount *= self.debit_multiplier
            if amount:
                yield timestamp, amount
            day += timedelta(days=1)


def accrue_swaps(trade, through: int, model: SwapModel | None):
    """Accrue each rollover once; callers book returned cash flows immediately."""
    if model is None:
        return []
    after = trade.entry_time if trade.swap_last_timestamp is None else trade.swap_last_timestamp
    if through < after:
        return []
    events = list(model.events(after, through, trade.side, trade.volume))
    trade.swap_last_timestamp = through
    trade.swap_events.extend(events)
    trade.swap_money += sum(amount for _, amount in events)
    return events


def rates_from_snapshot(snapshot: dict, info, account_currency: str):
    """Normalize supported MT5 rate modes; reject unknown currency/interest conversions."""
    mode = snapshot["swap_mode"]
    if mode == 0:
        return 0.0, 0.0
    if mode == 1:
        if snapshot["point"] != info.point or info.trade_tick_size <= 0 or info.trade_tick_value <= 0:
            raise ValueError("Incompatible points or missing account-currency tick valuation")
        factor = info.point / info.trade_tick_size * info.trade_tick_value
    elif mode == 4:
        if account_currency != "EUR":
            raise ValueError("This research requires EUR deposit currency")
        factor = 1.0
    else:
        raise ValueError(f"Unsupported swap mode {mode}; explicit currency/interest conversion required")
    return snapshot["swap_long"] * factor, snapshot["swap_short"] * factor


def weekday_weights(snapshot: dict, triple_day_override: int | None = None):
    """Reject invalid MT5 weekday codes unless the caller declares an override.

    MT5 weekdays are Sunday=0 through Saturday=6. Never modulo-wrap an
    unexpected value: it can otherwise silently invent a financing schedule.
    """
    day = snapshot["swap_rollover3days"] if triple_day_override is None else triple_day_override
    if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
        raise ValueError("Invalid triple-swap weekday; supply an explicit documented override")
    weights = [1, 1, 1, 1, 1, 0, 0]
    weights[(day-1) % 7] = 3
    return tuple(weights)
