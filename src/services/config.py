from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any, Union


DEFAULT_CONFIG: dict[str, Any] = {
    "runtime": {
        "poll_seconds": 5,
        "dry_run": True,
        "default_deviation": 20,
        "db_path": "bot_state.sqlite3",
        "log_file": "bot_events.csv",
        "daily_loss_limit_usd": 50.0,
        "close_positions_on_daily_loss": True,
        "max_loss_per_trade_usd": 5.0,
        "per_trade_loss_guard_mode": "position_risk",
        "per_trade_loss_risk_multiple": 1.0,
        "max_profit_per_trade_usd": 6.0,
        "trailing_stop_mode": "off",
        "trailing_activation_r": 1.0,
        "trailing_gap_r": 1.0,
        "trailing_remove_tp_on_activation": True,
        "risk_close_retry_sec": 20,
        "max_open_positions_total": 5,
        "max_total_open_risk_pct": 0.50,
        "checkpoint_interval_sec": 5,
        "maintenance_interval_sec": 3600,
        "event_retention_days": 30,
        "event_retention_batch_size": 5000,
        "event_archive_dir": "state_archives",
        "push_notifications_enabled": False,
        "push_notification_url": "",
        "push_notification_token": "",
        "push_notification_timeout_sec": 5,
        "news_filter_enabled": False,
        "news_provider": "investpy",
        "news_cache_path": "news_calendar_cache.json",
        "news_refresh_interval_sec": 1800,
        "news_timezone": "Europe/Sofia",
        "news_block_minutes_before": 30,
        "news_block_minutes_after": 15,
        "news_blocked_importances": ["high", "medium"],
    },
    "symbols": [
        {
            "symbol": "EURUSD",
            "timeframe": "M5",
            "bars": 500,
            "pivot_len": 5,
            "buffer_pips": 0.3,
            "sl_pips": 10.0,
            "rr": 2.0,
            "risk_pct": 0.10,
            "min_lot": 0.0,
            "max_lot": 0.10,
            "max_spread_pips": 1.8,
            "cooldown_sec": 300,
            "magic": 92001,
            "trade_side_filter": "both",
            "max_levels": 25,
            "one_position_per_symbol": True,
            "strategy_mode": "liquidity_sweep",
            "allowed_sessions_utc": ["06:00-11:55", "12:00-22:00"],
            "use_bias_filter": True,
            "bias_timeframe": "M15",
            "bias_ema_period": 20,
            "bias_lookback_bars": 80,
            "use_order_block_filter": True,
            "ignore_portfolio_cap": False,
            "order_block_lookback_bars": 20,
            "order_block_max_distance_pips": 8.0,
            "order_block_strong_override_max_distance_pips": 8.0,
            "order_block_strong_override_min_impulse_pips": 20.0,
            "order_block_zone_mode": "body",
            "order_block_min_impulse_pips": 3.0,
            "order_block_max_age_bars": 15,
            "confirmation_mode": "sweep_displacement_mss",
            "confirm_expiry_bars": 5,
            "cisd_timeframe": "M1",
            "cisd_lookback_bars": 120,
            "cisd_structure_bars": 4,
            "scalp_session_start_utc": "06:00",
            "scalp_open_range_minutes": 15,
            "scalp_watch_minutes": 180,
            "scalp_preopen_lookback_bars": 12,
            "scalp_preopen_max_compression_ratio": 2.0,
            "sweep_significance_lookback_bars": 12,
            "sweep_significance_range_multiple": 1.25,
            "sweep_min_penetration_pips": 0.5,
            "range_filter_lookback_bars": 8,
            "range_filter_max_compression_ratio": 2.5,
            "range_filter_min_overlap_ratio": 0.75,
            "confirmation_displacement_body_ratio_min": 0.55,
            "confirmation_displacement_range_multiple": 1.8,
            "micro_burst_pullback_bars": 2,
            "micro_burst_body_ratio_min": 0.45,
            "max_hold_bars": 0,
            "early_exit_consecutive_adverse_closes": 0,
            "early_exit_large_adverse_body_r": 0.0,
            "trailing_stop_mode": "",
            "trailing_activation_r": None,
            "trailing_gap_r": None,
            "trailing_remove_tp_on_activation": None,
            "refresh_pending_on_newer_signal": False,
            "refresh_pending_min_age_bars": 1,
        }
    ],
}


@dataclass(frozen=True)
class RuntimeConfig:
    poll_seconds: int
    dry_run: bool
    default_deviation: int
    db_path: str
    log_file: str
    daily_loss_limit_usd: float
    close_positions_on_daily_loss: bool
    max_loss_per_trade_usd: float
    per_trade_loss_guard_mode: str
    per_trade_loss_risk_multiple: float
    max_profit_per_trade_usd: float
    trailing_stop_mode: str
    trailing_activation_r: float
    trailing_gap_r: float
    trailing_remove_tp_on_activation: bool
    risk_close_retry_sec: int
    max_open_positions_total: int
    max_total_open_risk_pct: float
    checkpoint_interval_sec: int
    maintenance_interval_sec: int
    event_retention_days: int
    event_retention_batch_size: int
    event_archive_dir: str
    push_notifications_enabled: bool
    push_notification_url: str
    push_notification_token: str
    push_notification_timeout_sec: int
    news_filter_enabled: bool = False
    news_provider: str = "investpy"
    news_cache_path: str = "news_calendar_cache.json"
    news_refresh_interval_sec: int = 1800
    news_timezone: str = "Europe/Sofia"
    news_block_minutes_before: int = 30
    news_block_minutes_after: int = 15
    news_blocked_importances: tuple[str, ...] = ("high", "medium")


@dataclass(frozen=True)
class SymbolConfig:
    symbol: str
    timeframe: str
    bars: int
    pivot_len: int
    buffer_pips: float
    sl_pips: float
    rr: float
    risk_pct: float
    max_lot: float
    max_spread_pips: float
    cooldown_sec: int
    magic: int
    trade_side_filter: str = "both"
    min_lot: float = 0.0
    max_levels: int = 25
    one_position_per_symbol: bool = True
    strategy_mode: str = "liquidity_sweep"
    allowed_sessions_utc: tuple[str, ...] = ()
    use_bias_filter: bool = True
    bias_timeframe: str = "M15"
    bias_ema_period: int = 20
    bias_lookback_bars: int = 80
    use_order_block_filter: bool = True
    ignore_portfolio_cap: bool = False
    order_block_lookback_bars: int = 20
    order_block_max_distance_pips: float = 8.0
    order_block_strong_override_max_distance_pips: float = 8.0
    order_block_strong_override_min_impulse_pips: float = 20.0
    order_block_zone_mode: str = "body"
    order_block_min_impulse_pips: float = 3.0
    order_block_max_age_bars: int = 15
    confirmation_mode: str = "sweep_displacement_mss"
    confirm_expiry_bars: int = 3
    cisd_timeframe: str = "M1"
    cisd_lookback_bars: int = 120
    cisd_structure_bars: int = 4
    scalp_session_start_utc: str = "06:00"
    scalp_open_range_minutes: int = 15
    scalp_watch_minutes: int = 180
    scalp_preopen_lookback_bars: int = 12
    scalp_preopen_max_compression_ratio: float = 2.0
    sweep_significance_lookback_bars: int = 12
    sweep_significance_range_multiple: float = 1.25
    sweep_min_penetration_pips: float = 0.5
    range_filter_lookback_bars: int = 8
    range_filter_max_compression_ratio: float = 2.5
    range_filter_min_overlap_ratio: float = 0.75
    confirmation_displacement_body_ratio_min: float = 0.55
    confirmation_displacement_range_multiple: float = 1.8
    micro_burst_pullback_bars: int = 2
    micro_burst_body_ratio_min: float = 0.45
    setup_timeframe: str = "H1"
    setup_lookback_bars: int = 120
    ema_fast_period: int = 9
    ema_mid_period: int = 21
    ema_slow_period: int = 50
    atr_period: int = 14
    adx_period: int = 14
    adx_threshold: float = 18.0
    volume_sma_period: int = 20
    breakout_volume_multiple: float = 1.2
    structure_pivot_len: int = 3
    setup_max_age_bars: int = 6
    trigger_sweep_lookback_bars: int = 4
    retest_zone_atr_multiple: float = 0.25
    reclaim_max_atr_multiple: float = 1.8
    stop_atr_multiple: float = 0.15
    entry_max_atr_multiple: float = 1.6
    htf_target_min_r: float = 1.0
    overlap_lookback_bars: int = 8
    max_overlap_ratio: float = 0.60
    weekend_risk_multiplier: float = 1.0
    max_hold_bars: int = 0
    early_exit_consecutive_adverse_closes: int = 0
    early_exit_large_adverse_body_r: float = 0.0
    trailing_stop_mode: str = ""
    trailing_activation_r: float | None = None
    trailing_gap_r: float | None = None
    trailing_remove_tp_on_activation: bool | None = None
    refresh_pending_on_newer_signal: bool = False
    refresh_pending_min_age_bars: int = 1

    @property
    def tp_pips(self) -> float:
        return self.sl_pips * self.rr


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig
    symbols: tuple[SymbolConfig, ...]


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Union[str, Path]) -> AppConfig:
    cfg_path = Path(path)
    raw = json.loads(json.dumps(DEFAULT_CONFIG))

    if cfg_path.exists():
        user_data = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw = _merge(raw, user_data)

    local_override_path = cfg_path.with_name(f"{cfg_path.stem}.local{cfg_path.suffix}")
    if local_override_path.exists():
        local_data = json.loads(local_override_path.read_text(encoding="utf-8"))
        raw = _merge(raw, local_data)

    runtime_raw = raw.get("runtime", {})
    runtime = RuntimeConfig(
        poll_seconds=int(runtime_raw.get("poll_seconds", 5)),
        dry_run=bool(runtime_raw.get("dry_run", True)),
        default_deviation=int(runtime_raw.get("default_deviation", 20)),
        db_path=str(runtime_raw.get("db_path", "bot_state.sqlite3")),
        log_file=str(runtime_raw.get("log_file", "bot_events.csv")),
        daily_loss_limit_usd=float(runtime_raw.get("daily_loss_limit_usd", 50.0)),
        close_positions_on_daily_loss=bool(runtime_raw.get("close_positions_on_daily_loss", True)),
        max_loss_per_trade_usd=float(runtime_raw.get("max_loss_per_trade_usd", 5.0)),
        per_trade_loss_guard_mode=str(runtime_raw.get("per_trade_loss_guard_mode", "position_risk")).lower(),
        per_trade_loss_risk_multiple=float(runtime_raw.get("per_trade_loss_risk_multiple", 1.0)),
        max_profit_per_trade_usd=float(runtime_raw.get("max_profit_per_trade_usd", 6.0)),
        trailing_stop_mode=str(runtime_raw.get("trailing_stop_mode", "off")).lower(),
        trailing_activation_r=float(runtime_raw.get("trailing_activation_r", 1.0)),
        trailing_gap_r=float(runtime_raw.get("trailing_gap_r", 1.0)),
        trailing_remove_tp_on_activation=bool(runtime_raw.get("trailing_remove_tp_on_activation", True)),
        risk_close_retry_sec=int(runtime_raw.get("risk_close_retry_sec", 20)),
        max_open_positions_total=int(runtime_raw.get("max_open_positions_total", 5)),
        max_total_open_risk_pct=float(runtime_raw.get("max_total_open_risk_pct", 0.50)),
        checkpoint_interval_sec=int(runtime_raw.get("checkpoint_interval_sec", 5)),
        maintenance_interval_sec=int(runtime_raw.get("maintenance_interval_sec", 3600)),
        event_retention_days=int(runtime_raw.get("event_retention_days", 30)),
        event_retention_batch_size=int(runtime_raw.get("event_retention_batch_size", 5000)),
        event_archive_dir=str(runtime_raw.get("event_archive_dir", "state_archives")),
        push_notifications_enabled=bool(runtime_raw.get("push_notifications_enabled", False)),
        push_notification_url=str(runtime_raw.get("push_notification_url", "")),
        push_notification_token=str(runtime_raw.get("push_notification_token", "")),
        push_notification_timeout_sec=int(runtime_raw.get("push_notification_timeout_sec", 5)),
        news_filter_enabled=bool(runtime_raw.get("news_filter_enabled", False)),
        news_provider=str(runtime_raw.get("news_provider", "investpy")).lower(),
        news_cache_path=str(runtime_raw.get("news_cache_path", "news_calendar_cache.json")),
        news_refresh_interval_sec=int(runtime_raw.get("news_refresh_interval_sec", 1800)),
        news_timezone=str(runtime_raw.get("news_timezone", "Europe/Sofia")),
        news_block_minutes_before=int(runtime_raw.get("news_block_minutes_before", 30)),
        news_block_minutes_after=int(runtime_raw.get("news_block_minutes_after", 15)),
        news_blocked_importances=tuple(str(item).lower() for item in runtime_raw.get("news_blocked_importances", ["high", "medium"])),
    )

    symbols: list[SymbolConfig] = []
    for row in raw.get("symbols", []):
        symbols.append(
            SymbolConfig(
                symbol=str(row["symbol"]).upper(),
                timeframe=str(row.get("timeframe", "M5")).upper(),
                bars=int(row.get("bars", 500)),
                pivot_len=int(row.get("pivot_len", 5)),
                buffer_pips=float(row.get("buffer_pips", 0.3)),
                sl_pips=float(row.get("sl_pips", 10.0)),
                rr=float(row.get("rr", 2.0)),
                risk_pct=float(row.get("risk_pct", 0.1)),
                min_lot=float(row.get("min_lot", 0.0)),
                max_lot=float(row.get("max_lot", 0.10)),
                max_spread_pips=float(row.get("max_spread_pips", 1.8)),
                cooldown_sec=int(row.get("cooldown_sec", 300)),
                magic=int(row.get("magic", 92000)),
                trade_side_filter=str(row.get("trade_side_filter", "both")).lower(),
                max_levels=int(row.get("max_levels", 25)),
                one_position_per_symbol=bool(row.get("one_position_per_symbol", True)),
                strategy_mode=str(row.get("strategy_mode", "liquidity_sweep")).lower(),
                allowed_sessions_utc=tuple(row.get("allowed_sessions_utc", [])),
                use_bias_filter=bool(row.get("use_bias_filter", True)),
                bias_timeframe=str(row.get("bias_timeframe", "M15")).upper(),
                bias_ema_period=int(row.get("bias_ema_period", 20)),
                bias_lookback_bars=int(row.get("bias_lookback_bars", 80)),
                use_order_block_filter=bool(row.get("use_order_block_filter", True)),
                ignore_portfolio_cap=bool(row.get("ignore_portfolio_cap", False)),
                order_block_lookback_bars=int(row.get("order_block_lookback_bars", 20)),
                order_block_max_distance_pips=float(row.get("order_block_max_distance_pips", 8.0)),
                order_block_strong_override_max_distance_pips=float(
                    row.get("order_block_strong_override_max_distance_pips", 8.0)
                ),
                order_block_strong_override_min_impulse_pips=float(
                    row.get("order_block_strong_override_min_impulse_pips", 20.0)
                ),
                order_block_zone_mode=str(row.get("order_block_zone_mode", "body")).lower(),
                order_block_min_impulse_pips=float(row.get("order_block_min_impulse_pips", 3.0)),
                order_block_max_age_bars=int(row.get("order_block_max_age_bars", 15)),
                confirmation_mode=str(row.get("confirmation_mode", "sweep_displacement_mss")).lower(),
                confirm_expiry_bars=int(row.get("confirm_expiry_bars", 3)),
                cisd_timeframe=str(row.get("cisd_timeframe", "M1")).upper(),
                cisd_lookback_bars=int(row.get("cisd_lookback_bars", 120)),
                cisd_structure_bars=int(row.get("cisd_structure_bars", 4)),
                scalp_session_start_utc=str(row.get("scalp_session_start_utc", "06:00")),
                scalp_open_range_minutes=int(row.get("scalp_open_range_minutes", 15)),
                scalp_watch_minutes=int(row.get("scalp_watch_minutes", 180)),
                scalp_preopen_lookback_bars=int(row.get("scalp_preopen_lookback_bars", 12)),
                scalp_preopen_max_compression_ratio=float(row.get("scalp_preopen_max_compression_ratio", 2.0)),
                sweep_significance_lookback_bars=int(row.get("sweep_significance_lookback_bars", 12)),
                sweep_significance_range_multiple=float(row.get("sweep_significance_range_multiple", 1.25)),
                sweep_min_penetration_pips=float(row.get("sweep_min_penetration_pips", 0.5)),
                range_filter_lookback_bars=int(row.get("range_filter_lookback_bars", 8)),
                range_filter_max_compression_ratio=float(row.get("range_filter_max_compression_ratio", 2.5)),
                range_filter_min_overlap_ratio=float(row.get("range_filter_min_overlap_ratio", 0.75)),
                confirmation_displacement_body_ratio_min=float(
                    row.get("confirmation_displacement_body_ratio_min", 0.55)
                ),
                confirmation_displacement_range_multiple=float(
                    row.get("confirmation_displacement_range_multiple", 1.8)
                ),
                micro_burst_pullback_bars=int(row.get("micro_burst_pullback_bars", 2)),
                micro_burst_body_ratio_min=float(row.get("micro_burst_body_ratio_min", 0.45)),
                setup_timeframe=str(row.get("setup_timeframe", "H1")).upper(),
                setup_lookback_bars=int(row.get("setup_lookback_bars", 120)),
                ema_fast_period=int(row.get("ema_fast_period", 9)),
                ema_mid_period=int(row.get("ema_mid_period", 21)),
                ema_slow_period=int(row.get("ema_slow_period", 50)),
                atr_period=int(row.get("atr_period", 14)),
                adx_period=int(row.get("adx_period", 14)),
                adx_threshold=float(row.get("adx_threshold", 18.0)),
                volume_sma_period=int(row.get("volume_sma_period", 20)),
                breakout_volume_multiple=float(row.get("breakout_volume_multiple", 1.2)),
                structure_pivot_len=int(row.get("structure_pivot_len", 3)),
                setup_max_age_bars=int(row.get("setup_max_age_bars", 6)),
                trigger_sweep_lookback_bars=int(row.get("trigger_sweep_lookback_bars", 4)),
                retest_zone_atr_multiple=float(row.get("retest_zone_atr_multiple", 0.25)),
                reclaim_max_atr_multiple=float(row.get("reclaim_max_atr_multiple", 1.8)),
                stop_atr_multiple=float(row.get("stop_atr_multiple", 0.15)),
                entry_max_atr_multiple=float(row.get("entry_max_atr_multiple", 1.6)),
                htf_target_min_r=float(row.get("htf_target_min_r", 1.0)),
                overlap_lookback_bars=int(row.get("overlap_lookback_bars", 8)),
                max_overlap_ratio=float(row.get("max_overlap_ratio", 0.60)),
                weekend_risk_multiplier=float(row.get("weekend_risk_multiplier", 1.0)),
                max_hold_bars=int(row.get("max_hold_bars", 0)),
                early_exit_consecutive_adverse_closes=int(row.get("early_exit_consecutive_adverse_closes", 0)),
                early_exit_large_adverse_body_r=float(row.get("early_exit_large_adverse_body_r", 0.0)),
                trailing_stop_mode=str(row.get("trailing_stop_mode", "") or "").lower(),
                trailing_activation_r=(
                    float(row["trailing_activation_r"]) if row.get("trailing_activation_r") is not None else None
                ),
                trailing_gap_r=(
                    float(row["trailing_gap_r"]) if row.get("trailing_gap_r") is not None else None
                ),
                trailing_remove_tp_on_activation=(
                    bool(row["trailing_remove_tp_on_activation"])
                    if row.get("trailing_remove_tp_on_activation") is not None
                    else None
                ),
                refresh_pending_on_newer_signal=bool(row.get("refresh_pending_on_newer_signal", False)),
                refresh_pending_min_age_bars=int(row.get("refresh_pending_min_age_bars", 1)),
            )
        )

    if not symbols:
        raise ValueError("No symbols configured.")

    valid_guard_modes = {"fixed_usd", "position_risk"}
    if runtime.per_trade_loss_guard_mode not in valid_guard_modes:
        raise ValueError(f"Unsupported per_trade_loss_guard_mode={runtime.per_trade_loss_guard_mode}")
    if runtime.per_trade_loss_risk_multiple <= 0:
        raise ValueError("per_trade_loss_risk_multiple must be > 0")
    if runtime.push_notification_timeout_sec <= 0:
        raise ValueError("push_notification_timeout_sec must be > 0")
    if runtime.push_notifications_enabled and not runtime.push_notification_url:
        raise ValueError("push_notification_url is required when push_notifications_enabled=true")
    valid_news_providers = {"investpy"}
    if runtime.news_provider not in valid_news_providers:
        raise ValueError(f"Unsupported news_provider={runtime.news_provider}")
    if runtime.news_refresh_interval_sec <= 0:
        raise ValueError("news_refresh_interval_sec must be > 0")
    if runtime.news_block_minutes_before < 0:
        raise ValueError("news_block_minutes_before must be >= 0")
    if runtime.news_block_minutes_after < 0:
        raise ValueError("news_block_minutes_after must be >= 0")
    valid_news_importances = {"high", "medium", "low"}
    invalid_importances = [item for item in runtime.news_blocked_importances if item not in valid_news_importances]
    if invalid_importances:
        raise ValueError(f"Unsupported news_blocked_importances={invalid_importances}")
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(runtime.news_timezone)
    except Exception as exc:
        raise ValueError(f"Invalid news_timezone={runtime.news_timezone}") from exc

    valid_confirmation_modes = {
        "none",
        "c3",
        "c4",
        "cisd",
        "sweep_displacement_mss",
        "sweep_displacement_only",
        "session_open_scalp_c1",
    }
    valid_strategy_modes = {
        "liquidity_sweep",
        "session_open_scalp",
        "opening_range_breakout_v2",
        "h4_bias_micro_burst",
        "trend_micro_burst_v2",
        "trend_day_acceleration",
        "btc_mtf_trend_retest_reclaim",
    }
    valid_trade_side_filters = {"both", "buy", "sell"}
    valid_trailing_modes = {"", "off", "r_multiple"}
    for symbol in symbols:
        if symbol.strategy_mode not in valid_strategy_modes:
            raise ValueError(f"Unsupported strategy_mode={symbol.strategy_mode} for {symbol.symbol}")
        if symbol.confirmation_mode not in valid_confirmation_modes:
            raise ValueError(f"Unsupported confirmation_mode={symbol.confirmation_mode} for {symbol.symbol}")
        if symbol.trade_side_filter not in valid_trade_side_filters:
            raise ValueError(f"Unsupported trade_side_filter={symbol.trade_side_filter} for {symbol.symbol}")
        if symbol.sweep_significance_lookback_bars < 2:
            raise ValueError(f"sweep_significance_lookback_bars must be >= 2 for {symbol.symbol}")
        if symbol.sweep_significance_range_multiple <= 0:
            raise ValueError(f"sweep_significance_range_multiple must be > 0 for {symbol.symbol}")
        if symbol.sweep_min_penetration_pips <= 0:
            raise ValueError(f"sweep_min_penetration_pips must be > 0 for {symbol.symbol}")
        if symbol.scalp_open_range_minutes <= 0:
            raise ValueError(f"scalp_open_range_minutes must be > 0 for {symbol.symbol}")
        if symbol.scalp_watch_minutes <= symbol.scalp_open_range_minutes:
            raise ValueError(f"scalp_watch_minutes must be > scalp_open_range_minutes for {symbol.symbol}")
        if symbol.scalp_preopen_lookback_bars < 3:
            raise ValueError(f"scalp_preopen_lookback_bars must be >= 3 for {symbol.symbol}")
        if symbol.setup_lookback_bars < 20:
            raise ValueError(f"setup_lookback_bars must be >= 20 for {symbol.symbol}")
        if min(symbol.ema_fast_period, symbol.ema_mid_period, symbol.ema_slow_period) <= 0:
            raise ValueError(f"EMA periods must be > 0 for {symbol.symbol}")
        if symbol.atr_period <= 1:
            raise ValueError(f"atr_period must be > 1 for {symbol.symbol}")
        if symbol.adx_period <= 1:
            raise ValueError(f"adx_period must be > 1 for {symbol.symbol}")
        if symbol.volume_sma_period <= 1:
            raise ValueError(f"volume_sma_period must be > 1 for {symbol.symbol}")
        if symbol.breakout_volume_multiple <= 0:
            raise ValueError(f"breakout_volume_multiple must be > 0 for {symbol.symbol}")
        if symbol.structure_pivot_len < 2:
            raise ValueError(f"structure_pivot_len must be >= 2 for {symbol.symbol}")
        if symbol.setup_max_age_bars < 1:
            raise ValueError(f"setup_max_age_bars must be >= 1 for {symbol.symbol}")
        if symbol.trigger_sweep_lookback_bars < 2:
            raise ValueError(f"trigger_sweep_lookback_bars must be >= 2 for {symbol.symbol}")
        if symbol.retest_zone_atr_multiple <= 0:
            raise ValueError(f"retest_zone_atr_multiple must be > 0 for {symbol.symbol}")
        if symbol.reclaim_max_atr_multiple <= 0:
            raise ValueError(f"reclaim_max_atr_multiple must be > 0 for {symbol.symbol}")
        if symbol.stop_atr_multiple < 0:
            raise ValueError(f"stop_atr_multiple must be >= 0 for {symbol.symbol}")
        if symbol.entry_max_atr_multiple <= 0:
            raise ValueError(f"entry_max_atr_multiple must be > 0 for {symbol.symbol}")
        if symbol.htf_target_min_r < 0:
            raise ValueError(f"htf_target_min_r must be >= 0 for {symbol.symbol}")
        if symbol.overlap_lookback_bars < 2:
            raise ValueError(f"overlap_lookback_bars must be >= 2 for {symbol.symbol}")
        if not 0 <= symbol.max_overlap_ratio <= 1:
            raise ValueError(f"max_overlap_ratio must be between 0 and 1 for {symbol.symbol}")
        if symbol.weekend_risk_multiplier <= 0:
            raise ValueError(f"weekend_risk_multiplier must be > 0 for {symbol.symbol}")
        if symbol.scalp_preopen_max_compression_ratio <= 0:
            raise ValueError(f"scalp_preopen_max_compression_ratio must be > 0 for {symbol.symbol}")
        if symbol.range_filter_lookback_bars < 3:
            raise ValueError(f"range_filter_lookback_bars must be >= 3 for {symbol.symbol}")
        if symbol.range_filter_max_compression_ratio <= 0:
            raise ValueError(f"range_filter_max_compression_ratio must be > 0 for {symbol.symbol}")
        if not 0.0 <= symbol.range_filter_min_overlap_ratio <= 1.0:
            raise ValueError(f"range_filter_min_overlap_ratio must be between 0 and 1 for {symbol.symbol}")
        if symbol.order_block_max_distance_pips <= 0:
            raise ValueError(f"order_block_max_distance_pips must be > 0 for {symbol.symbol}")
        if symbol.order_block_strong_override_max_distance_pips < symbol.order_block_max_distance_pips:
            raise ValueError(
                f"order_block_strong_override_max_distance_pips must be >= order_block_max_distance_pips for {symbol.symbol}"
            )
        if symbol.order_block_strong_override_min_impulse_pips <= 0:
            raise ValueError(
                f"order_block_strong_override_min_impulse_pips must be > 0 for {symbol.symbol}"
            )
        if not 0.0 < symbol.confirmation_displacement_body_ratio_min <= 1.0:
            raise ValueError(
                f"confirmation_displacement_body_ratio_min must be in (0, 1] for {symbol.symbol}"
            )
        if symbol.confirmation_displacement_range_multiple <= 0:
            raise ValueError(f"confirmation_displacement_range_multiple must be > 0 for {symbol.symbol}")
        if symbol.micro_burst_pullback_bars < 1:
            raise ValueError(f"micro_burst_pullback_bars must be >= 1 for {symbol.symbol}")
        if not 0.0 < symbol.micro_burst_body_ratio_min <= 1.0:
            raise ValueError(f"micro_burst_body_ratio_min must be in (0, 1] for {symbol.symbol}")
        if symbol.max_hold_bars < 0:
            raise ValueError(f"max_hold_bars must be >= 0 for {symbol.symbol}")
        if symbol.early_exit_consecutive_adverse_closes < 0:
            raise ValueError(f"early_exit_consecutive_adverse_closes must be >= 0 for {symbol.symbol}")
        if symbol.early_exit_large_adverse_body_r < 0:
            raise ValueError(f"early_exit_large_adverse_body_r must be >= 0 for {symbol.symbol}")
        if symbol.trailing_stop_mode not in valid_trailing_modes:
            raise ValueError(f"Unsupported trailing_stop_mode={symbol.trailing_stop_mode} for {symbol.symbol}")
        if symbol.trailing_activation_r is not None and symbol.trailing_activation_r <= 0:
            raise ValueError(f"trailing_activation_r must be > 0 for {symbol.symbol}")
        if symbol.trailing_gap_r is not None and symbol.trailing_gap_r < 0:
            raise ValueError(f"trailing_gap_r must be >= 0 for {symbol.symbol}")
        if symbol.refresh_pending_min_age_bars < 1:
            raise ValueError(f"refresh_pending_min_age_bars must be >= 1 for {symbol.symbol}")

    return AppConfig(runtime=runtime, symbols=tuple(symbols))
