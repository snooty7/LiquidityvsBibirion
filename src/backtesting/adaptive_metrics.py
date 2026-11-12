"""Transparent ledger metrics; missing marked equity is never invented."""
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import random
from statistics import mean, stdev

from src.tools.walk_forward import trade_metrics


def ledger_metrics(trades, equity: float, start: datetime, end: datetime, observations=()) -> dict:
    """Report costs, net expectancy, realized daily Sharpe and block uncertainty.

    Sharpe uses UTC calendar daily realized returns, including zero-trade days,
    annualized by sqrt(365); this is explicitly not marked-to-market Sharpe.
    """
    fills = len(trades)
    grouped = defaultdict(list)
    for trade in trades:
        grouped[(trade.symbol, trade.side, trade.entry_time_utc, trade.signal_key)].append(trade)
    positions = []
    for items in grouped.values():
        last = max(items, key=lambda item: item.exit_time_utc)
        volume = sum(item.volume for item in items)
        totals = {name: sum(getattr(item, name) for item in items) for name in
                  ("pnl_money", "gross_pnl_money", "spread_cost_money", "commission_cost_money", "slippage_cost_money")}
        positions.append(replace(last, volume=volume, pnl_r=sum(item.pnl_r*item.volume for item in items)/volume,
                                 **totals))
    # Keep the fill-level cash flows for date-accurate fees and realized Sharpe.
    result = trade_metrics(trades, equity)
    position_metrics = trade_metrics(positions, equity)
    for name in ("trades", "win_rate_pct", "profit_factor", "profit_factor_note", "avg_r"):
        result[name] = position_metrics[name]
    result["exit_fills"] = fills
    if not positions:
        result.update(win_rate_pct=None, avg_r=None, profit_factor=None)
    daily = defaultdict(float)
    for trade in trades:
        entry = datetime.fromisoformat(trade.entry_time_utc).date()
        exit_day = datetime.fromisoformat(trade.exit_time_utc).date()
        fee = trade.commission_cost_money/2
        daily[entry] -= fee
        daily[exit_day] += trade.pnl_money+fee
    days = []
    current = start.date()
    while current < end.date():
        days.append(current)
        current += timedelta(days=1)
    balance, returns = equity, []
    for day in days:
        returns.append(daily[day]/balance if balance > 0 else None)
        balance += daily[day]
    valid = [value for value in returns if value is not None]
    sharpe = mean(valid)/stdev(valid)*math.sqrt(365) if len(valid) > 1 and stdev(valid) > 0 else None
    streak = longest = 0
    for trade in sorted(positions, key=lambda item: item.exit_time_utc):
        streak = streak+1 if trade.pnl_money < 0 else 0
        longest = max(longest, streak)
    result.update(expectancy_money=mean([trade.pnl_money for trade in positions]) if positions else None,
                  expectancy_r=mean([trade.pnl_r for trade in positions]) if positions else None,
                  sharpe_realized_calendar_daily=sharpe, sharpe_annualization_days=365,
                  daily_sample_size=len(valid), max_consecutive_losses=longest,
                  max_marked_equity_drawdown=None,
                  marked_equity_note="Unavailable: baseline replay does not export marked equity",
                  net_profit_after_costs=result["net_pnl"])
    # Five-calendar-day circular blocks; intentionally unavailable for tiny samples.
    interval = None
    if len(days) >= 30 and len(trades) >= 20:
        generator = random.Random(1729)
        values = [daily[day] for day in days]
        samples = []
        for _ in range(500):
            sample = []
            while len(sample) < len(values):
                begin = generator.randrange(len(values))
                sample.extend(values[(begin+i) % len(values)] for i in range(5))
            samples.append(sum(sample[:len(values)]))
        samples.sort()
        interval = [samples[12], samples[487]]
    result["net_profit_95pct_block_bootstrap_interval"] = interval
    result["bootstrap_note"] = "500 resamples, circular 5-day blocks, seed 1729; unavailable below 30 days / 20 trades; descriptive, not a selection criterion"
    regime_by_key = {row["signal_key"]: row["regime"] for row in observations if row.get("signal_key")}
    groups = {"regime": defaultdict(list), "instrument": defaultdict(list), "session": defaultdict(list)}
    for trade in positions:
        hour = datetime.fromisoformat(trade.entry_time_utc).astimezone(timezone.utc).hour
        session = "00-06 UTC" if hour < 6 else "06-12 UTC" if hour < 12 else "12-18 UTC" if hour < 18 else "18-24 UTC"
        groups["regime"][regime_by_key.get(trade.signal_key, "unobserved_baseline")].append(trade)
        groups["instrument"][trade.symbol].append(trade)
        groups["session"][session].append(trade)
    result["breakdowns"] = {dimension: {key: trade_metrics(items, equity) for key, items in groups_.items()}
                            for dimension, groups_ in groups.items()}
    return result
