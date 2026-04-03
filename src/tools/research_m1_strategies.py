from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from src.execution.mt5_adapter import MT5Adapter
from src.strategy.filters import evaluate_bias
from src.strategy.liquidity import (
    M1PatternSignalResult,
    SessionOpenScalpSignalResult,
    SweepSignal,
    detect_ny_micro_pullback_drift_signal,
    detect_opening_range_breakout_signal,
    detect_opening_range_breakout_v2_signal,
    detect_overreaction_fade_signal,
    detect_two_candle_momentum_signal,
)


SESSION_WINDOWS = {
    "london": ("06:00", "09:00"),
    "newyork": ("12:30", "15:30"),
}


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    strategy: str
    session_name: str
    use_h1_bias: bool
    sl_pips: float
    rr: float
    max_hold_bars: int
    adverse_limit: int
    body_ratio_min: float = 0.0
    buffer_pips: float = 0.0
    open_range_minutes: int = 15
    watch_minutes: int = 180
    lookback_bars: int = 12
    range_multiple: float = 2.0
    pullback_bars: int = 2
    drift_lookback_bars: int = 4


@dataclass
class SimTrade:
    side: str
    entry_time: int
    entry_price: float
    sl: float
    tp: float
    hold_bars: int
    adverse_count: int
    entry_spread_pips: float


@dataclass
class ScenarioResult:
    scenario: str
    strategy: str
    session: str
    use_h1_bias: bool
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate_pct: float
    net_pips: float
    avg_pips: float
    avg_r: float
    profit_factor: float
    max_drawdown_pips: float


def _to_utc_datetime(value: str, *, end_of_day: bool = False) -> datetime:
    raw = value.strip()
    if "T" in raw:
        dt = datetime.fromisoformat(raw)
    else:
        suffix = "23:59:59" if end_of_day else "00:00:00"
        dt = datetime.fromisoformat(f"{raw}T{suffix}")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bar_dict(row: object) -> dict:
    return {
        "time": int(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "spread": int(row["spread"]) if "spread" in row.dtype.names else 0,
    }


def _fetch_chunked_rates(
    adapter: MT5Adapter,
    symbol: str,
    timeframe: str,
    date_from: datetime,
    date_to: datetime,
    *,
    chunk_days: int = 21,
) -> list[dict]:
    rows: list[dict] = []
    cursor = date_from
    while cursor < date_to:
        chunk_end = min(cursor + timedelta(days=chunk_days), date_to)
        part = [_bar_dict(item) for item in adapter.copy_rates_range(symbol, timeframe, cursor, chunk_end)]
        rows.extend(part)
        cursor = chunk_end

    deduped: list[dict] = []
    last_time: Optional[int] = None
    for item in sorted(rows, key=lambda row: int(row["time"])):
        current_time = int(item["time"])
        if current_time == last_time:
            continue
        deduped.append(item)
        last_time = current_time
    return deduped


def _append_dummy_forming_bar(closed_rates: Sequence[dict], timeframe_seconds: int) -> list[dict]:
    rows = [dict(item) for item in closed_rates]
    if not rows:
        return rows
    last = rows[-1]
    close_price = float(last["close"])
    rows.append(
        {
            "time": int(last["time"]) + int(timeframe_seconds),
            "open": close_price,
            "high": close_price,
            "low": close_price,
            "close": close_price,
            "spread": int(last.get("spread", 0)),
        }
    )
    return rows


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_raw, minute_raw = value.split(":", 1)
    return int(hour_raw), int(minute_raw)


def _session_allowed(ts: int, session_name: str) -> bool:
    start_raw, end_raw = SESSION_WINDOWS[session_name]
    dt = datetime.fromtimestamp(int(ts), timezone.utc)
    start_hour, start_minute = _parse_hhmm(start_raw)
    end_hour, end_minute = _parse_hhmm(end_raw)
    start_dt = dt.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_dt = dt.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return start_dt <= dt < end_dt


def _available_closed_bars(
    rates: Sequence[dict],
    times: Sequence[int],
    decision_time: int,
    timeframe_seconds: int,
    *,
    tail_bars: int,
) -> list[dict]:
    cutoff_open_time = int(decision_time) - int(timeframe_seconds)
    end = bisect.bisect_right(times, cutoff_open_time)
    start = max(0, end - int(tail_bars))
    return list(rates[start:end])


def _spread_pips(bar: dict, pip: float, point: float) -> float:
    spread_points = float(bar.get("spread", 0) or 0)
    if spread_points <= 0 or pip <= 0 or point <= 0:
        return 0.0
    return float((spread_points * point) / pip)


def _signal_from_result(result: M1PatternSignalResult | SessionOpenScalpSignalResult) -> Optional[SweepSignal]:
    return result.signal


def _bias_ok(h1_rates: Sequence[dict], side: str) -> bool:
    bias = evaluate_bias(h1_rates, ema_period=20)
    return bool(bias["ok_buy"] if side == "BUY" else bias["ok_sell"])


def _build_trade(side: str, entry_price: float, entry_time: int, sl_pips: float, rr: float, pip: float, entry_spread_pips: float) -> SimTrade:
    if side == "BUY":
        sl = float(entry_price - sl_pips * pip)
        tp = float(entry_price + sl_pips * rr * pip)
    else:
        sl = float(entry_price + sl_pips * pip)
        tp = float(entry_price - sl_pips * rr * pip)
    return SimTrade(
        side=side,
        entry_time=entry_time,
        entry_price=float(entry_price),
        sl=sl,
        tp=tp,
        hold_bars=0,
        adverse_count=0,
        entry_spread_pips=float(entry_spread_pips),
    )


def _close_trade(trade: SimTrade, exit_price: float, pip: float, reason: str) -> tuple[float, str]:
    if trade.side == "BUY":
        raw_pips = (float(exit_price) - float(trade.entry_price)) / pip
    else:
        raw_pips = (float(trade.entry_price) - float(exit_price)) / pip
    pnl_pips = float(raw_pips - trade.entry_spread_pips)
    return pnl_pips, reason


def _apply_trade_bar(trade: SimTrade, bar: dict, scenario: ScenarioConfig, pip: float) -> tuple[SimTrade, Optional[tuple[float, str]]]:
    high = float(bar["high"])
    low = float(bar["low"])
    close_price = float(bar["close"])
    open_price = float(bar["open"])
    trade.hold_bars += 1

    if trade.side == "BUY":
        hit_sl = low <= trade.sl
        hit_tp = high >= trade.tp
        if hit_sl and hit_tp:
            return trade, _close_trade(trade, trade.sl, pip, "stop_loss")
        if hit_sl:
            return trade, _close_trade(trade, trade.sl, pip, "stop_loss")
        if hit_tp:
            return trade, _close_trade(trade, trade.tp, pip, "take_profit")
        adverse_bar = close_price < open_price
    else:
        hit_sl = high >= trade.sl
        hit_tp = low <= trade.tp
        if hit_sl and hit_tp:
            return trade, _close_trade(trade, trade.sl, pip, "stop_loss")
        if hit_sl:
            return trade, _close_trade(trade, trade.sl, pip, "stop_loss")
        if hit_tp:
            return trade, _close_trade(trade, trade.tp, pip, "take_profit")
        adverse_bar = close_price > open_price

    if adverse_bar:
        trade.adverse_count += 1
        if trade.adverse_count >= int(scenario.adverse_limit):
            return trade, _close_trade(trade, close_price, pip, "adverse_close_exit")
    else:
        trade.adverse_count = 0

    if trade.hold_bars >= int(scenario.max_hold_bars):
        return trade, _close_trade(trade, close_price, pip, "time_exit")

    return trade, None


def _scenario_signal(scenario: ScenarioConfig, closed_m1: Sequence[dict], pip: float) -> Optional[SweepSignal]:
    rates = _append_dummy_forming_bar(closed_m1, 60)
    buffer_price = float(scenario.buffer_pips) * pip
    if scenario.strategy == "two_candle_momentum":
        return _signal_from_result(
            detect_two_candle_momentum_signal(
                rates,
                body_ratio_min=scenario.body_ratio_min,
                buffer_price=buffer_price,
            )
        )
    if scenario.strategy == "opening_range_breakout":
        session_start = "06:00" if scenario.session_name == "london" else "12:30"
        return _signal_from_result(
            detect_opening_range_breakout_signal(
                rates,
                session_start_utc=session_start,
                open_range_minutes=scenario.open_range_minutes,
                watch_minutes=scenario.watch_minutes,
                buffer_price=buffer_price,
                body_ratio_min=scenario.body_ratio_min,
            )
        )
    if scenario.strategy == "opening_range_breakout_v2":
        session_start = "06:00" if scenario.session_name == "london" else "12:30"
        return _signal_from_result(
            detect_opening_range_breakout_v2_signal(
                rates,
                session_start_utc=session_start,
                open_range_minutes=scenario.open_range_minutes,
                watch_minutes=scenario.watch_minutes,
                buffer_price=buffer_price,
                body_ratio_min=scenario.body_ratio_min,
                pullback_bars=scenario.pullback_bars,
                range_multiple=scenario.range_multiple,
            )
        )
    if scenario.strategy == "overreaction_fade":
        return _signal_from_result(
            detect_overreaction_fade_signal(
                rates,
                lookback_bars=scenario.lookback_bars,
                range_multiple=scenario.range_multiple,
                body_ratio_min=scenario.body_ratio_min,
                buffer_price=buffer_price,
            )
        )
    if scenario.strategy == "ny_micro_pullback_drift":
        return _signal_from_result(
            detect_ny_micro_pullback_drift_signal(
                rates,
                pullback_bars=scenario.pullback_bars,
                drift_lookback_bars=scenario.drift_lookback_bars,
                body_ratio_min=scenario.body_ratio_min,
                buffer_price=buffer_price,
            )
        )
    raise ValueError(f"Unsupported scenario strategy={scenario.strategy}")


def run_scenario(
    symbol: str,
    scenario: ScenarioConfig,
    m1: Sequence[dict],
    h1: Sequence[dict],
    *,
    start_utc: datetime,
    end_utc: datetime,
    pip: float,
    point: float,
) -> ScenarioResult:
    h1_times = [int(row["time"]) for row in h1]
    open_trade: Optional[SimTrade] = None
    pnl_pips: list[float] = []
    equity_curve = [0.0]

    for idx, bar in enumerate(m1):
        close_time = int(bar["time"]) + 60
        if close_time < int(start_utc.timestamp()) or close_time > int(end_utc.timestamp()):
            continue

        if open_trade is not None:
            open_trade, maybe_closed = _apply_trade_bar(open_trade, bar, scenario, pip)
            if maybe_closed is not None:
                pnl_value, _ = maybe_closed
                pnl_pips.append(pnl_value)
                equity_curve.append(equity_curve[-1] + pnl_value)
                open_trade = None

        if open_trade is not None:
            continue
        if idx < 30:
            continue
        if not _session_allowed(int(bar["time"]), scenario.session_name):
            continue

        closed_m1 = list(m1[max(0, idx - 200) : idx + 1])
        signal = _scenario_signal(scenario, closed_m1, pip)
        if signal is None:
            continue

        if scenario.use_h1_bias:
            h1_closed = _available_closed_bars(
                h1,
                h1_times,
                close_time,
                3600,
                tail_bars=100,
            )
            if not _bias_ok(h1_closed, signal.side):
                continue

        entry_spread_pips = _spread_pips(bar, pip, point)
        open_trade = _build_trade(
            signal.side,
            float(bar["close"]),
            close_time,
            scenario.sl_pips,
            scenario.rr,
            pip,
            entry_spread_pips,
        )

    if open_trade is not None and m1:
        final_close = float(m1[-1]["close"])
        pnl_value, _ = _close_trade(open_trade, final_close, pip, "end_of_data")
        pnl_pips.append(pnl_value)
        equity_curve.append(equity_curve[-1] + pnl_value)

    wins = sum(1 for item in pnl_pips if item > 0)
    losses = sum(1 for item in pnl_pips if item < 0)
    breakeven = sum(1 for item in pnl_pips if item == 0)
    trades = len(pnl_pips)
    win_rate = (wins / trades * 100.0) if trades else 0.0
    gross_profit = sum(item for item in pnl_pips if item > 0)
    gross_loss = abs(sum(item for item in pnl_pips if item < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
    peak = 0.0
    max_dd = 0.0
    for point_value in equity_curve:
        peak = max(peak, point_value)
        max_dd = max(max_dd, peak - point_value)

    return ScenarioResult(
        scenario=scenario.name,
        strategy=scenario.strategy,
        session=scenario.session_name,
        use_h1_bias=scenario.use_h1_bias,
        trades=trades,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate_pct=round(win_rate, 2),
        net_pips=round(sum(pnl_pips), 2),
        avg_pips=round(sum(pnl_pips) / trades, 3) if trades else 0.0,
        avg_r=round(sum(item / scenario.sl_pips for item in pnl_pips) / trades, 3) if trades else 0.0,
        profit_factor=round(profit_factor, 3),
        max_drawdown_pips=round(max_dd, 2),
    )


def default_scenarios() -> list[ScenarioConfig]:
    return [
        ScenarioConfig(
            name="two_candle_momentum_london",
            strategy="two_candle_momentum",
            session_name="london",
            use_h1_bias=True,
            sl_pips=3.0,
            rr=1.2,
            max_hold_bars=5,
            adverse_limit=2,
            body_ratio_min=0.45,
            buffer_pips=0.10,
        ),
        ScenarioConfig(
            name="two_candle_momentum_newyork",
            strategy="two_candle_momentum",
            session_name="newyork",
            use_h1_bias=True,
            sl_pips=3.0,
            rr=1.2,
            max_hold_bars=5,
            adverse_limit=2,
            body_ratio_min=0.45,
            buffer_pips=0.10,
        ),
        ScenarioConfig(
            name="opening_range_breakout_london",
            strategy="opening_range_breakout",
            session_name="london",
            use_h1_bias=True,
            sl_pips=4.0,
            rr=1.5,
            max_hold_bars=8,
            adverse_limit=2,
            body_ratio_min=0.45,
            buffer_pips=0.10,
            open_range_minutes=15,
            watch_minutes=180,
        ),
        ScenarioConfig(
            name="opening_range_breakout_newyork",
            strategy="opening_range_breakout",
            session_name="newyork",
            use_h1_bias=True,
            sl_pips=4.0,
            rr=1.5,
            max_hold_bars=8,
            adverse_limit=2,
            body_ratio_min=0.45,
            buffer_pips=0.10,
            open_range_minutes=15,
            watch_minutes=180,
        ),
        ScenarioConfig(
            name="opening_range_breakout_v2_newyork",
            strategy="opening_range_breakout_v2",
            session_name="newyork",
            use_h1_bias=True,
            sl_pips=4.0,
            rr=1.2,
            max_hold_bars=6,
            adverse_limit=2,
            body_ratio_min=0.45,
            buffer_pips=0.10,
            open_range_minutes=15,
            watch_minutes=180,
            pullback_bars=2,
            range_multiple=1.2,
        ),
        ScenarioConfig(
            name="opening_range_breakout_v2_newyork_tight",
            strategy="opening_range_breakout_v2",
            session_name="newyork",
            use_h1_bias=True,
            sl_pips=4.0,
            rr=1.0,
            max_hold_bars=5,
            adverse_limit=1,
            body_ratio_min=0.50,
            buffer_pips=0.10,
            open_range_minutes=15,
            watch_minutes=180,
            pullback_bars=2,
            range_multiple=1.3,
        ),
        ScenarioConfig(
            name="ny_micro_pullback_drift_newyork",
            strategy="ny_micro_pullback_drift",
            session_name="newyork",
            use_h1_bias=True,
            sl_pips=3.0,
            rr=1.0,
            max_hold_bars=3,
            adverse_limit=1,
            body_ratio_min=0.45,
            buffer_pips=0.05,
            pullback_bars=1,
            drift_lookback_bars=4,
        ),
        ScenarioConfig(
            name="ny_micro_pullback_drift_newyork_tight",
            strategy="ny_micro_pullback_drift",
            session_name="newyork",
            use_h1_bias=True,
            sl_pips=2.5,
            rr=0.8,
            max_hold_bars=2,
            adverse_limit=1,
            body_ratio_min=0.40,
            buffer_pips=0.03,
            pullback_bars=1,
            drift_lookback_bars=3,
        ),
        ScenarioConfig(
            name="overreaction_fade_london",
            strategy="overreaction_fade",
            session_name="london",
            use_h1_bias=False,
            sl_pips=4.0,
            rr=1.0,
            max_hold_bars=4,
            adverse_limit=1,
            body_ratio_min=0.60,
            buffer_pips=0.10,
            lookback_bars=12,
            range_multiple=2.0,
        ),
        ScenarioConfig(
            name="overreaction_fade_newyork",
            strategy="overreaction_fade",
            session_name="newyork",
            use_h1_bias=False,
            sl_pips=4.0,
            rr=1.0,
            max_hold_bars=4,
            adverse_limit=1,
            body_ratio_min=0.60,
            buffer_pips=0.10,
            lookback_bars=12,
            range_multiple=2.0,
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Research short-hold M1 strategy archetypes.")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    start_utc = _to_utc_datetime(args.start)
    end_utc = _to_utc_datetime(args.end, end_of_day=True)
    symbol = str(args.symbol).upper()

    adapter = MT5Adapter()
    adapter.initialize()
    adapter.ensure_symbol(symbol)
    fetch_start = start_utc - timedelta(days=5)
    fetch_end = end_utc + timedelta(days=1)
    m1 = _fetch_chunked_rates(adapter, symbol, "M1", fetch_start, fetch_end)
    h1 = _fetch_chunked_rates(adapter, symbol, "H1", fetch_start - timedelta(days=30), fetch_end)
    info = adapter.symbol_info(symbol)
    adapter.shutdown()

    pip = MT5Adapter.pip_size(info)
    point = float(info.point)
    results = [
        run_scenario(symbol, scenario, m1, h1, start_utc=start_utc, end_utc=end_utc, pip=pip, point=point)
        for scenario in default_scenarios()
    ]
    results.sort(key=lambda row: (row.net_pips, row.profit_factor), reverse=True)

    for result in results:
        print(
            f"{result.scenario}: trades={result.trades} net_pips={result.net_pips:.2f} "
            f"pf={result.profit_factor:.3f} win_rate={result.win_rate_pct:.2f}% avg_r={result.avg_r:.3f} "
            f"max_dd={result.max_drawdown_pips:.2f}"
        )

    csv_path = Path(args.csv) if args.csv else Path("reports") / f"m1_strategy_research_{symbol.lower()}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ScenarioResult.__dataclass_fields__.keys()))
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
