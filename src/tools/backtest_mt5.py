from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Sequence

from src.engine.orchestrator import (
    TIMEFRAME_SECONDS,
    compute_r_multiple_trailing_stop,
    effective_trailing_settings,
    resolve_loss_guard,
    semantic_setup_key,
    session_allowed,
)
from src.execution.mt5_adapter import MT5Adapter
from src.persistence.recovery import compute_setup_expiry
from src.risk.sizing import SymbolTradeInfo, calc_lot_by_risk, calc_position_risk_money
from src.services.config import AppConfig, RuntimeConfig, SymbolConfig, load_config
from src.strategy.confirmations import (
    ConfirmationResult,
    evaluate_none_confirmation,
    evaluate_c3_c4_confirmation,
    evaluate_cisd_confirmation,
    evaluate_session_open_scalp_c1_confirmation,
    evaluate_sweep_displacement_mss_confirmation,
)
from src.strategy.filters import (
    evaluate_bias,
    find_local_order_block,
    order_block_distance_pips,
    resolve_order_block_distance_limit_pips,
)
from src.strategy.liquidity import (
    SweepSignal,
    detect_h4_bias_micro_burst_signal,
    detect_session_open_scalp_signal,
    detect_sweep_signal,
    detect_trend_micro_burst_v2_signal,
    evaluate_compression_window,
    evaluate_range_filter,
    evaluate_sweep_significance,
    extract_pivot_levels,
)


@dataclass
class PendingSetupLite:
    signal_key: str
    side: str
    level: float
    candle_time: int
    expires_at: int
    last_note: str = ""


@dataclass
class OpenTrade:
    side: str
    entry_time: int
    entry_price: float
    sl: float
    tp: float
    volume: float
    risk_money: float
    signal_key: str
    confirm_note: str
    initial_sl: float
    initial_tp: float
    adverse_close_count: int = 0


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_time_utc: str
    exit_time_utc: str
    entry_price: float
    exit_price: float
    sl_initial: float
    tp_initial: float
    exit_sl: float
    exit_tp: float
    volume: float
    pnl_money: float
    pnl_r: float
    reason: str
    confirm_note: str
    signal_key: str


@dataclass
class BacktestResult:
    symbol: str
    side_mode: str
    start_utc: str
    end_utc: str
    bars_m1: int
    bars_m5: int
    bars_bias: int
    initial_equity: float
    ending_equity: float
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate_pct: float
    net_pnl_money: float
    avg_pnl_money: float
    avg_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_money: float
    max_drawdown_pct: float
    skipped_sweep_weak: int
    skipped_range_chop: int
    skipped_duplicate_setup: int
    skipped_pending_exists: int
    skipped_confirm_rejected: int
    skipped_bias: int
    skipped_order_block: int
    skipped_session: int
    skipped_cooldown: int
    skipped_daily_loss: int


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


def _side_allowed(side_mode: str, side: str) -> bool:
    mode = side_mode.lower()
    if mode == "both":
        return True
    return side.upper() == mode.upper()


def _bar_dict(row: object) -> dict:
    return {
        "time": int(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "tick_volume": int(row["tick_volume"]) if "tick_volume" in row.dtype.names else 0,
        "spread": int(row["spread"]) if "spread" in row.dtype.names else 0,
        "real_volume": int(row["real_volume"]) if "real_volume" in row.dtype.names else 0,
    }


def _append_dummy_forming_bar(closed_rates: Sequence[dict], timeframe_seconds: int) -> list[dict]:
    rows = [dict(item) for item in closed_rates]
    if not rows:
        return []
    last = rows[-1]
    close_price = float(last["close"])
    rows.append(
        {
            "time": int(last["time"]) + int(timeframe_seconds),
            "open": close_price,
            "high": close_price,
            "low": close_price,
            "close": close_price,
            "tick_volume": 0,
            "spread": int(last.get("spread", 0)),
            "real_volume": 0,
        }
    )
    return rows


def _spread_pips(bar: dict, pip: float, point: float) -> float:
    spread_points = float(bar.get("spread", 0) or 0)
    if spread_points <= 0 or pip <= 0 or point <= 0:
        return 0.0
    return float((spread_points * point) / pip)


def _available_closed_bars(
    rates: Sequence[dict],
    times: Sequence[int],
    decision_time: int,
    timeframe_seconds: int,
    *,
    tail_bars: Optional[int] = None,
) -> list[dict]:
    cutoff_open_time = int(decision_time) - int(timeframe_seconds)
    end = bisect.bisect_right(times, cutoff_open_time)
    start = 0
    if tail_bars is not None and tail_bars > 0:
        start = max(0, end - int(tail_bars))
    return list(rates[start:end])


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
        if last_time == current_time:
            continue
        deduped.append(item)
        last_time = current_time
    return deduped


def _latest_close_price(closed_rates: Sequence[dict]) -> float:
    if not closed_rates:
        raise ValueError("No closed rates available.")
    return float(closed_rates[-1]["close"])


def _evaluate_confirmation(
    cfg: SymbolConfig,
    pending: PendingSetupLite,
    closed_m1: Sequence[dict],
) -> ConfirmationResult:
    rates = _append_dummy_forming_bar(closed_m1, TIMEFRAME_SECONDS.get(cfg.cisd_timeframe, 60))
    mode = cfg.confirmation_mode.lower()
    if mode == "none":
        return evaluate_none_confirmation(rates, pending.candle_time)
    if mode in ("c3", "c4"):
        return evaluate_c3_c4_confirmation(rates, pending.side, pending.candle_time, mode)
    if mode == "cisd":
        return evaluate_cisd_confirmation(rates, pending.side, pending.candle_time, cfg.cisd_structure_bars)
    if mode == "sweep_displacement_mss":
        return evaluate_sweep_displacement_mss_confirmation(
            rates,
            pending.side,
            pending.candle_time,
            cfg.cisd_structure_bars,
            displacement_body_ratio_min=cfg.confirmation_displacement_body_ratio_min,
            displacement_range_multiple=cfg.confirmation_displacement_range_multiple,
        )
    if mode == "session_open_scalp_c1":
        return evaluate_session_open_scalp_c1_confirmation(rates, pending.side, pending.candle_time)
    return ConfirmationResult(False, False, f"unknown_confirmation_mode={mode}")


def _position_like(trade: OpenTrade) -> object:
    side_value = 0 if trade.side == "BUY" else 1
    return SimpleNamespace(
        type=side_value,
        price_open=trade.entry_price,
        sl=trade.sl,
        tp=trade.tp,
        volume=trade.volume,
    )


def _close_trade(
    cfg: SymbolConfig,
    trade: OpenTrade,
    exit_time: int,
    exit_price: float,
    reason: str,
    symbol_info: SymbolTradeInfo,
) -> ClosedTrade:
    if trade.side == "BUY":
        pnl_price = float(exit_price) - float(trade.entry_price)
    else:
        pnl_price = float(trade.entry_price) - float(exit_price)

    pip = MT5Adapter.pip_size(symbol_info)
    pvl = 0.0
    if symbol_info.trade_tick_value > 0 and symbol_info.trade_tick_size > 0:
        pvl = symbol_info.trade_tick_value * (pip / symbol_info.trade_tick_size)
    pnl_money = float((pnl_price / pip) * pvl * trade.volume) if pip > 0 and pvl > 0 else 0.0
    pnl_r = float(pnl_money / trade.risk_money) if trade.risk_money > 0 else 0.0

    return ClosedTrade(
        symbol=cfg.symbol,
        side=trade.side,
        entry_time_utc=datetime.fromtimestamp(trade.entry_time, timezone.utc).isoformat(),
        exit_time_utc=datetime.fromtimestamp(exit_time, timezone.utc).isoformat(),
        entry_price=float(trade.entry_price),
        exit_price=float(exit_price),
        sl_initial=float(trade.initial_sl),
        tp_initial=float(trade.initial_tp),
        exit_sl=float(trade.sl),
        exit_tp=float(trade.tp),
        volume=float(trade.volume),
        pnl_money=pnl_money,
        pnl_r=pnl_r,
        reason=reason,
        confirm_note=trade.confirm_note,
        signal_key=trade.signal_key,
    )


def _apply_open_trade_bar(
    cfg: SymbolConfig,
    runtime: RuntimeConfig,
    trade: OpenTrade,
    bar: dict,
    symbol_info: SymbolTradeInfo,
) -> tuple[OpenTrade, Optional[ClosedTrade]]:
    high = float(bar["high"])
    low = float(bar["low"])
    close_price = float(bar["close"])
    close_time = int(bar["time"]) + TIMEFRAME_SECONDS["M1"]

    hit_sl = False
    hit_tp = False
    if trade.side == "BUY":
        hit_sl = low <= float(trade.sl) if trade.sl > 0 else False
        hit_tp = high >= float(trade.tp) if trade.tp > 0 else False
        if hit_sl and hit_tp:
            return trade, _close_trade(cfg, trade, close_time, float(trade.sl), "stop_loss", symbol_info)
        if hit_sl:
            reason = "trailing_stop" if trade.sl > trade.entry_price else "stop_loss"
            return trade, _close_trade(cfg, trade, close_time, float(trade.sl), reason, symbol_info)
        if hit_tp:
            return trade, _close_trade(cfg, trade, close_time, float(trade.tp), "take_profit", symbol_info)
    else:
        hit_sl = high >= float(trade.sl) if trade.sl > 0 else False
        hit_tp = low <= float(trade.tp) if trade.tp > 0 else False
        if hit_sl and hit_tp:
            return trade, _close_trade(cfg, trade, close_time, float(trade.sl), "stop_loss", symbol_info)
        if hit_sl:
            reason = "trailing_stop" if trade.sl < trade.entry_price else "stop_loss"
            return trade, _close_trade(cfg, trade, close_time, float(trade.sl), reason, symbol_info)
        if hit_tp:
            return trade, _close_trade(cfg, trade, close_time, float(trade.tp), "take_profit", symbol_info)

    trailing_mode, trailing_activation_r, trailing_gap_r, trailing_remove_tp = effective_trailing_settings(cfg, runtime)
    if trailing_mode == "r_multiple":
        desired_sl = compute_r_multiple_trailing_stop(
            side=trade.side,
            open_price=trade.entry_price,
            current_exit_price_value=close_price,
            current_sl=trade.sl,
            risk_distance_price=abs(trade.entry_price - trade.initial_sl),
            activation_r=float(trailing_activation_r),
            gap_r=float(trailing_gap_r),
        )
        if desired_sl is not None:
            if trade.side == "BUY":
                if desired_sl > trade.sl:
                    trade.sl = float(desired_sl)
                    if trailing_remove_tp:
                        trade.tp = 0.0
            else:
                if trade.sl <= 0 or desired_sl < trade.sl:
                    trade.sl = float(desired_sl)
                    if trailing_remove_tp:
                        trade.tp = 0.0

    adverse_limit = int(getattr(cfg, "early_exit_consecutive_adverse_closes", 0) or 0)
    large_adverse_r = float(getattr(cfg, "early_exit_large_adverse_body_r", 0.0) or 0.0)
    if adverse_limit > 0 or large_adverse_r > 0:
        adverse_bar = close_price < float(bar["open"]) if trade.side == "BUY" else close_price > float(bar["open"])
        if adverse_bar:
            trade.adverse_close_count += 1
            body_size = abs(close_price - float(bar["open"]))
            risk_distance = abs(trade.entry_price - trade.initial_sl)
            if large_adverse_r > 0 and risk_distance > 0 and body_size >= risk_distance * large_adverse_r:
                return trade, _close_trade(cfg, trade, close_time, close_price, "large_adverse_bar_exit", symbol_info)
            if adverse_limit > 0 and trade.adverse_close_count >= adverse_limit:
                return trade, _close_trade(cfg, trade, close_time, close_price, "adverse_close_exit", symbol_info)
        else:
            trade.adverse_close_count = 0

    position = _position_like(trade)
    loss_limit_money, loss_reason, _ = resolve_loss_guard(runtime, position, symbol_info)
    if loss_limit_money is not None:
        close_trade = _close_trade(cfg, trade, close_time, close_price, "mark_to_close", symbol_info)
        if close_trade.pnl_money <= -abs(float(loss_limit_money)):
            close_trade.reason = loss_reason or "max_loss"
            return trade, close_trade
    if runtime.max_profit_per_trade_usd > 0:
        close_trade = _close_trade(cfg, trade, close_time, close_price, "mark_to_close", symbol_info)
        if close_trade.pnl_money >= float(runtime.max_profit_per_trade_usd):
            close_trade.reason = f"max_profit ${runtime.max_profit_per_trade_usd:.2f}"
            return trade, close_trade

    return trade, None


def _build_entry_trade(
    cfg: SymbolConfig,
    runtime: RuntimeConfig,
    symbol_info: SymbolTradeInfo,
    equity: float,
    entry_side: str,
    entry_time: int,
    entry_price: float,
    signal_key: str,
    confirm_note: str,
) -> OpenTrade:
    pip = MT5Adapter.pip_size(symbol_info)
    if entry_side == "BUY":
        sl = float(entry_price - cfg.sl_pips * pip)
        tp = float(entry_price + cfg.tp_pips * pip)
    else:
        sl = float(entry_price + cfg.sl_pips * pip)
        tp = float(entry_price - cfg.tp_pips * pip)

    volume = calc_lot_by_risk(equity, cfg.sl_pips, cfg.risk_pct, symbol_info, cfg.max_lot)
    risk_money = calc_position_risk_money(
        entry_price=entry_price,
        stop_price=sl,
        volume=volume,
        symbol_info=symbol_info,
    )
    trailing_mode, _, _, _ = effective_trailing_settings(cfg, runtime)
    if runtime.max_profit_per_trade_usd <= 0 and trailing_mode == "r_multiple":
        # Matches live config where TP is removed after trailing activation, but not at entry.
        initial_tp = tp
    else:
        initial_tp = tp

    return OpenTrade(
        side=entry_side,
        entry_time=entry_time,
        entry_price=float(entry_price),
        sl=float(sl),
        tp=float(tp),
        volume=float(volume),
        risk_money=float(risk_money),
        signal_key=signal_key,
        confirm_note=confirm_note,
        initial_sl=float(sl),
        initial_tp=float(initial_tp),
    )


def _max_buffer_days(cfg: SymbolConfig) -> int:
    bars_minutes = [
        cfg.bars * (TIMEFRAME_SECONDS.get(cfg.timeframe, 300) // 60),
        cfg.bias_lookback_bars * (TIMEFRAME_SECONDS.get(cfg.bias_timeframe, 900) // 60),
        cfg.cisd_lookback_bars * (TIMEFRAME_SECONDS.get(cfg.cisd_timeframe, 60) // 60),
    ]
    max_minutes = max(bars_minutes)
    return max(7, int(max_minutes / (60 * 24)) + 3)


def run_backtest(
    app_config: AppConfig,
    cfg: SymbolConfig,
    start_utc: datetime,
    end_utc: datetime,
    *,
    initial_equity: float,
    side_mode: str = "both",
    trades_csv: Optional[Path] = None,
) -> tuple[BacktestResult, list[ClosedTrade]]:
    adapter = MT5Adapter(default_deviation=app_config.runtime.default_deviation)
    adapter.initialize()
    adapter.ensure_symbol(cfg.symbol)

    buffer_days = _max_buffer_days(cfg)
    fetch_start = start_utc - timedelta(days=buffer_days)
    fetch_end = end_utc + timedelta(days=1)

    m1 = _fetch_chunked_rates(adapter, cfg.symbol, "M1", fetch_start, fetch_end)
    m5 = _fetch_chunked_rates(adapter, cfg.symbol, cfg.timeframe, fetch_start, fetch_end)
    bias_rates = _fetch_chunked_rates(adapter, cfg.symbol, cfg.bias_timeframe, fetch_start, fetch_end)
    symbol_info = SymbolTradeInfo.from_mt5(adapter.symbol_info(cfg.symbol))
    adapter.shutdown()

    if len(m1) < 10 or len(m5) < 10:
        raise RuntimeError("Not enough MT5 historical data for backtest.")

    m1_times = [int(item["time"]) for item in m1]
    m5_times = [int(item["time"]) for item in m5]
    bias_times = [int(item["time"]) for item in bias_rates]
    pip = MT5Adapter.pip_size(symbol_info)
    point = float(symbol_info.point)

    equity = float(initial_equity)
    peak_equity = equity
    max_drawdown_money = 0.0
    previous_m5_close_time: Optional[int] = None
    last_closed_m1: list[dict] = []
    cooldown_until = 0.0
    last_signal_key: Optional[str] = None
    pending: Optional[PendingSetupLite] = None
    open_trade: Optional[OpenTrade] = None
    closed_trades: list[ClosedTrade] = []
    current_day = ""
    daily_realized_pnl = 0.0
    daily_loss_reached = False

    skip_sweep_weak = 0
    skip_range_chop = 0
    skip_duplicate_setup = 0
    skip_pending_exists = 0
    skip_confirm_rejected = 0
    skip_bias = 0
    skip_order_block = 0
    skip_session = 0
    skip_cooldown = 0
    skip_daily_loss = 0

    for idx, current_m5 in enumerate(m5):
        decision_time = int(current_m5["time"]) + TIMEFRAME_SECONDS.get(cfg.timeframe, 300)
        if decision_time < int(start_utc.timestamp()):
            previous_m5_close_time = decision_time
            continue
        if decision_time > int((end_utc + timedelta(days=1)).timestamp()):
            break

        if previous_m5_close_time is None:
            previous_m5_close_time = decision_time - TIMEFRAME_SECONDS.get(cfg.timeframe, 300)

        day_key = datetime.fromtimestamp(decision_time, timezone.utc).strftime("%Y-%m-%d")
        if current_day != day_key:
            current_day = day_key
            daily_realized_pnl = 0.0
            daily_loss_reached = False

        m1_start = bisect.bisect_right(m1_times, int(previous_m5_close_time) - TIMEFRAME_SECONDS["M1"])
        m1_end = bisect.bisect_right(m1_times, int(decision_time) - TIMEFRAME_SECONDS["M1"])
        interval_m1 = m1[m1_start:m1_end]
        previous_m5_close_time = decision_time

        if open_trade is not None:
            for bar in interval_m1:
                open_trade, maybe_closed = _apply_open_trade_bar(cfg, app_config.runtime, open_trade, bar, symbol_info)
                if maybe_closed is None:
                    continue
                closed_trades.append(maybe_closed)
                equity += maybe_closed.pnl_money
                daily_realized_pnl += maybe_closed.pnl_money
                peak_equity = max(peak_equity, equity)
                max_drawdown_money = max(max_drawdown_money, peak_equity - equity)
                open_trade = None
                if daily_realized_pnl <= -abs(float(app_config.runtime.daily_loss_limit_usd)):
                    daily_loss_reached = True
                break

        closed_m1 = _available_closed_bars(
            m1,
            m1_times,
            decision_time,
            TIMEFRAME_SECONDS["M1"],
            tail_bars=max(cfg.cisd_lookback_bars + 5, 300),
        )
        last_closed_m1 = closed_m1
        closed_m5 = _available_closed_bars(
            m5,
            m5_times,
            decision_time,
            TIMEFRAME_SECONDS.get(cfg.timeframe, 300),
            tail_bars=max(cfg.bars, 600),
        )
        closed_bias = _available_closed_bars(
            bias_rates,
            bias_times,
            decision_time,
            TIMEFRAME_SECONDS.get(cfg.bias_timeframe, 900),
            tail_bars=max(cfg.bias_lookback_bars, cfg.bias_ema_period + 3, 120),
        )
        if len(closed_m5) < 3:
            continue

        closed_bar_time = int(closed_m5[-1]["time"])
        if pending is not None and int(closed_bar_time) >= int(pending.expires_at):
            pending = None

        if pending is not None:
            confirm_result = _evaluate_confirmation(cfg, pending, closed_m1)
            if confirm_result.confirmed:
                entry_time = decision_time
                entry_price = _latest_close_price(closed_m1)
                now_utc = datetime.fromtimestamp(entry_time, timezone.utc)
                if daily_loss_reached:
                    skip_daily_loss += 1
                    pending = None
                    continue
                if not session_allowed(cfg, now_utc):
                    skip_session += 1
                    pending = None
                    continue
                if float(entry_time) < cooldown_until:
                    skip_cooldown += 1
                    pending = None
                    continue
                if open_trade is not None and cfg.one_position_per_symbol:
                    pending = None
                    continue

                current_m1_bar = closed_m1[-1]
                spread_pips = _spread_pips(current_m1_bar, pip, point)
                if spread_pips > cfg.max_spread_pips:
                    pending = None
                    continue

                if cfg.use_bias_filter:
                    bias_info = evaluate_bias(closed_bias, cfg.bias_ema_period)
                    bias_ok = bias_info["ok_buy"] if pending.side == "BUY" else bias_info["ok_sell"]
                    if not bias_ok:
                        skip_bias += 1
                        pending = None
                        continue

                if cfg.use_order_block_filter:
                    m5_rates = _append_dummy_forming_bar(closed_m5, TIMEFRAME_SECONDS.get(cfg.timeframe, 300))
                    signal_index = len(m5_rates) - 2
                    order_block = find_local_order_block(
                        rates=m5_rates,
                        signal_index=signal_index,
                        side=pending.side,
                        pip=pip,
                        lookback_bars=cfg.order_block_lookback_bars,
                        max_age_bars=cfg.order_block_max_age_bars,
                        zone_mode=cfg.order_block_zone_mode,
                        min_impulse_pips=cfg.order_block_min_impulse_pips,
                    )
                    if order_block is None:
                        skip_order_block += 1
                        pending = None
                        continue
                    ob_distance = order_block_distance_pips(entry_price, order_block["low"], order_block["high"], pip)
                    allowed_ob_distance, _ = resolve_order_block_distance_limit_pips(
                        cfg.order_block_max_distance_pips,
                        order_block,
                        confirmation_mode=cfg.confirmation_mode,
                        range_note="range_ok",
                        strong_override_max_distance_pips=cfg.order_block_strong_override_max_distance_pips,
                        strong_override_min_impulse_pips=cfg.order_block_strong_override_min_impulse_pips,
                    )
                    if ob_distance > allowed_ob_distance:
                        skip_order_block += 1
                        pending = None
                        continue

                open_trade = _build_entry_trade(
                    cfg,
                    app_config.runtime,
                    symbol_info,
                    equity,
                    pending.side,
                    entry_time,
                    entry_price,
                    pending.signal_key,
                    str(confirm_result.note),
                )
                cooldown_until = float(entry_time) + float(cfg.cooldown_sec)
                pending = None
            elif confirm_result.pending:
                pending.last_note = str(confirm_result.note)
            else:
                skip_confirm_rejected += 1
                pending = None

        if pending is None:
            m5_rates = _append_dummy_forming_bar(closed_m5, TIMEFRAME_SECONDS.get(cfg.timeframe, 300))
            levels: list[float] = []
            if cfg.strategy_mode == "session_open_scalp":
                scalp_result = detect_session_open_scalp_signal(
                    m5_rates,
                    session_start_utc=cfg.scalp_session_start_utc,
                    open_range_minutes=cfg.scalp_open_range_minutes,
                    watch_minutes=cfg.scalp_watch_minutes,
                    buffer_price=cfg.buffer_pips * pip,
                    body_ratio_min=cfg.confirmation_displacement_body_ratio_min,
                    preopen_lookback_bars=cfg.scalp_preopen_lookback_bars,
                    preopen_max_compression_ratio=cfg.scalp_preopen_max_compression_ratio,
                )
                signal = scalp_result.signal
            elif cfg.strategy_mode == "h4_bias_micro_burst":
                signal = detect_h4_bias_micro_burst_signal(
                    m5_rates,
                    pullback_bars=cfg.micro_burst_pullback_bars,
                    body_ratio_min=cfg.micro_burst_body_ratio_min,
                    buffer_price=cfg.buffer_pips * pip,
                ).signal
            elif cfg.strategy_mode == "trend_micro_burst_v2":
                signal = detect_trend_micro_burst_v2_signal(
                    m5_rates,
                    pullback_bars=cfg.micro_burst_pullback_bars,
                    body_ratio_min=cfg.micro_burst_body_ratio_min,
                    range_multiple=cfg.confirmation_displacement_range_multiple,
                    buffer_price=cfg.buffer_pips * pip,
                ).signal
            else:
                levels = extract_pivot_levels(m5_rates, cfg.pivot_len, cfg.max_levels)
                signal = detect_sweep_signal(m5_rates, levels, cfg.buffer_pips * pip)
            if signal is not None:
                if not _side_allowed(side_mode, signal.side):
                    continue
                if cfg.strategy_mode == "session_open_scalp":
                    compression = evaluate_compression_window(
                        m5_rates[:-2],
                        lookback_bars=cfg.scalp_preopen_lookback_bars,
                        max_compression_ratio=cfg.scalp_preopen_max_compression_ratio,
                    )
                    if not compression.blocked:
                        skip_range_chop += 1
                        continue
                elif cfg.strategy_mode in ("h4_bias_micro_burst", "trend_micro_burst_v2"):
                    pass
                else:
                    prior_closed = m5_rates[:-2]
                    chop_result = evaluate_range_filter(
                        prior_closed,
                        lookback_bars=cfg.range_filter_lookback_bars,
                        max_compression_ratio=cfg.range_filter_max_compression_ratio,
                        min_overlap_ratio=cfg.range_filter_min_overlap_ratio,
                    )
                    if chop_result.blocked:
                        skip_range_chop += 1
                        continue

                    sweep_quality = evaluate_sweep_significance(
                        m5_rates,
                        signal,
                        lookback_bars=cfg.sweep_significance_lookback_bars,
                        min_range_multiple=cfg.sweep_significance_range_multiple,
                        min_penetration_price=cfg.sweep_min_penetration_pips * pip,
                    )
                    if not sweep_quality.valid:
                        skip_sweep_weak += 1
                        continue

                signal_key = semantic_setup_key(signal.candle_time, signal.side, signal.level)
                if signal_key == last_signal_key:
                    skip_duplicate_setup += 1
                    continue

                last_signal_key = signal_key
                pending = PendingSetupLite(
                    signal_key=signal_key,
                    side=signal.side,
                    level=float(signal.level),
                    candle_time=int(signal.candle_time),
                    expires_at=compute_setup_expiry(
                        signal.candle_time,
                        TIMEFRAME_SECONDS.get(cfg.timeframe, 300),
                        cfg.confirm_expiry_bars,
                    ),
                    last_note="created",
                )
        else:
            m5_rates = _append_dummy_forming_bar(closed_m5, TIMEFRAME_SECONDS.get(cfg.timeframe, 300))
            if cfg.strategy_mode == "session_open_scalp":
                signal = detect_session_open_scalp_signal(
                    m5_rates,
                    session_start_utc=cfg.scalp_session_start_utc,
                    open_range_minutes=cfg.scalp_open_range_minutes,
                    watch_minutes=cfg.scalp_watch_minutes,
                    buffer_price=cfg.buffer_pips * pip,
                    body_ratio_min=cfg.confirmation_displacement_body_ratio_min,
                    preopen_lookback_bars=cfg.scalp_preopen_lookback_bars,
                    preopen_max_compression_ratio=cfg.scalp_preopen_max_compression_ratio,
                ).signal
            elif cfg.strategy_mode == "h4_bias_micro_burst":
                signal = detect_h4_bias_micro_burst_signal(
                    m5_rates,
                    pullback_bars=cfg.micro_burst_pullback_bars,
                    body_ratio_min=cfg.micro_burst_body_ratio_min,
                    buffer_price=cfg.buffer_pips * pip,
                ).signal
            elif cfg.strategy_mode == "trend_micro_burst_v2":
                signal = detect_trend_micro_burst_v2_signal(
                    m5_rates,
                    pullback_bars=cfg.micro_burst_pullback_bars,
                    body_ratio_min=cfg.micro_burst_body_ratio_min,
                    range_multiple=cfg.confirmation_displacement_range_multiple,
                    buffer_price=cfg.buffer_pips * pip,
                ).signal
            else:
                levels = extract_pivot_levels(m5_rates, cfg.pivot_len, cfg.max_levels)
                signal = detect_sweep_signal(m5_rates, levels, cfg.buffer_pips * pip)
            if signal is not None:
                skip_pending_exists += 1

    if open_trade is not None and last_closed_m1:
        final_close_time = int(last_closed_m1[-1]["time"]) + TIMEFRAME_SECONDS["M1"]
        final_close_price = float(last_closed_m1[-1]["close"])
        closed = _close_trade(cfg, open_trade, final_close_time, final_close_price, "end_of_test", symbol_info)
        closed_trades.append(closed)
        equity += closed.pnl_money
        daily_realized_pnl += closed.pnl_money
        peak_equity = max(peak_equity, equity)
        max_drawdown_money = max(max_drawdown_money, peak_equity - equity)

    gross_profit = sum(item.pnl_money for item in closed_trades if item.pnl_money > 0)
    gross_loss = abs(sum(item.pnl_money for item in closed_trades if item.pnl_money < 0))
    total_trades = len(closed_trades)
    wins = sum(1 for item in closed_trades if item.pnl_money > 0)
    losses = sum(1 for item in closed_trades if item.pnl_money < 0)
    breakeven = total_trades - wins - losses
    avg_pnl = sum(item.pnl_money for item in closed_trades) / total_trades if total_trades else 0.0
    avg_r = sum(item.pnl_r for item in closed_trades) / total_trades if total_trades else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    max_drawdown_pct = (max_drawdown_money / peak_equity * 100.0) if peak_equity > 0 else 0.0
    win_rate_pct = (wins / total_trades * 100.0) if total_trades else 0.0

    result = BacktestResult(
        symbol=cfg.symbol,
        side_mode=side_mode.lower(),
        start_utc=start_utc.isoformat(),
        end_utc=end_utc.isoformat(),
        bars_m1=len(m1),
        bars_m5=len(m5),
        bars_bias=len(bias_rates),
        initial_equity=float(initial_equity),
        ending_equity=float(equity),
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate_pct=win_rate_pct,
        net_pnl_money=float(equity - initial_equity),
        avg_pnl_money=avg_pnl,
        avg_r=avg_r,
        expectancy_r=avg_r,
        profit_factor=profit_factor,
        max_drawdown_money=max_drawdown_money,
        max_drawdown_pct=max_drawdown_pct,
        skipped_sweep_weak=skip_sweep_weak,
        skipped_range_chop=skip_range_chop,
        skipped_duplicate_setup=skip_duplicate_setup,
        skipped_pending_exists=skip_pending_exists,
        skipped_confirm_rejected=skip_confirm_rejected,
        skipped_bias=skip_bias,
        skipped_order_block=skip_order_block,
        skipped_session=skip_session,
        skipped_cooldown=skip_cooldown,
        skipped_daily_loss=skip_daily_loss,
    )

    if trades_csv is not None:
        trades_csv.parent.mkdir(parents=True, exist_ok=True)
        with trades_csv.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = list(asdict(closed_trades[0]).keys()) if closed_trades else list(ClosedTrade.__dataclass_fields__.keys())
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for trade in closed_trades:
                writer.writerow(asdict(trade))

    return result, closed_trades


def _print_summary(result: BacktestResult) -> None:
    print(
        f"BACKTEST {result.symbol} side={result.side_mode} {result.start_utc} -> {result.end_utc}\n"
        f"bars M1={result.bars_m1} M5={result.bars_m5} bias={result.bars_bias}\n"
        f"trades={result.total_trades} wins={result.wins} losses={result.losses} be={result.breakeven} "
        f"win_rate={result.win_rate_pct:.2f}%\n"
        f"net_pnl=${result.net_pnl_money:.2f} avg_pnl=${result.avg_pnl_money:.2f} "
        f"avg_r={result.avg_r:.3f} pf={result.profit_factor:.3f}\n"
        f"equity {result.initial_equity:.2f} -> {result.ending_equity:.2f} "
        f"max_dd=${result.max_drawdown_money:.2f} ({result.max_drawdown_pct:.2f}%)\n"
        f"skips weak={result.skipped_sweep_weak} chop={result.skipped_range_chop} "
        f"dup={result.skipped_duplicate_setup} pending_exists={result.skipped_pending_exists} "
        f"confirm_rejected={result.skipped_confirm_rejected} bias={result.skipped_bias} "
        f"ob={result.skipped_order_block} session={result.skipped_session} "
        f"cooldown={result.skipped_cooldown} daily_loss={result.skipped_daily_loss}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical MT5 backtest for the liquidity bot")
    parser.add_argument("--config", default="config/settings.json", help="Path to bot config")
    parser.add_argument("--symbol", default="", help="Optional symbol override")
    parser.add_argument("--start", required=True, help="UTC start date/time, e.g. 2026-02-26 or 2026-02-26T00:00:00")
    parser.add_argument("--end", required=True, help="UTC end date/time, e.g. 2026-03-27 or 2026-03-27T23:59:59")
    parser.add_argument("--initial-equity", type=float, default=100000.0, help="Initial equity for lot sizing")
    parser.add_argument("--side", choices=["both", "buy", "sell"], default="both", help="Trade side filter")
    parser.add_argument("--trades-csv", default="", help="Optional output CSV path for trades")
    args = parser.parse_args()

    app_config = load_config(args.config)
    cfg = next((item for item in app_config.symbols if not args.symbol or item.symbol == args.symbol.upper()), None)
    if cfg is None:
        raise ValueError(f"Symbol not found in config: {args.symbol}")

    start_utc = _to_utc_datetime(args.start)
    end_utc = _to_utc_datetime(args.end, end_of_day="T" not in args.end)
    trades_csv = Path(args.trades_csv) if args.trades_csv else None

    result, _ = run_backtest(
        app_config=app_config,
        cfg=cfg,
        start_utc=start_utc,
        end_utc=end_utc,
        initial_equity=float(args.initial_equity),
        side_mode=str(args.side).lower(),
        trades_csv=trades_csv,
    )
    _print_summary(result)
    if trades_csv is not None:
        print(f"trades_csv={trades_csv}")


if __name__ == "__main__":
    main()
