from src.risk.sizing import SymbolTradeInfo
from src.services.config import RuntimeConfig, SymbolConfig
from src.tools.backtest_mt5 import OpenTrade, _append_dummy_forming_bar, _apply_open_trade_bar


def _runtime() -> RuntimeConfig:
    return RuntimeConfig(
        poll_seconds=5,
        dry_run=False,
        default_deviation=20,
        db_path="bot_state.sqlite3",
        log_file="bot_events.csv",
        daily_loss_limit_usd=50.0,
        close_positions_on_daily_loss=True,
        max_loss_per_trade_usd=3.0,
        per_trade_loss_guard_mode="position_risk",
        per_trade_loss_risk_multiple=1.0,
        max_profit_per_trade_usd=0.0,
        trailing_stop_mode="r_multiple",
        trailing_activation_r=1.0,
        trailing_gap_r=1.0,
        trailing_remove_tp_on_activation=True,
        risk_close_retry_sec=20,
        max_open_positions_total=5,
        max_total_open_risk_pct=0.5,
        checkpoint_interval_sec=5,
        maintenance_interval_sec=3600,
        event_retention_days=30,
        event_retention_batch_size=5000,
        event_archive_dir="state_archives",
        push_notifications_enabled=False,
        push_notification_url="",
        push_notification_token="",
        push_notification_timeout_sec=5,
    )


def _cfg() -> SymbolConfig:
    return SymbolConfig(
        symbol="EURUSD",
        timeframe="M5",
        bars=500,
        pivot_len=5,
        buffer_pips=0.3,
        sl_pips=10.0,
        rr=2.0,
        risk_pct=0.1,
        max_lot=0.05,
        max_spread_pips=1.8,
        cooldown_sec=900,
        magic=92001,
    )


def _info() -> SymbolTradeInfo:
    return SymbolTradeInfo(
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=10.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
    )


def test_append_dummy_forming_bar_adds_next_timestamp() -> None:
    rows = [
        {"time": 100, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "spread": 10},
        {"time": 160, "open": 1.15, "high": 1.16, "low": 1.14, "close": 1.155, "spread": 11},
    ]

    result = _append_dummy_forming_bar(rows, 60)

    assert len(result) == 3
    assert result[-1]["time"] == 220
    assert result[-1]["open"] == 1.155
    assert result[-1]["high"] == 1.155
    assert result[-1]["low"] == 1.155
    assert result[-1]["close"] == 1.155


def test_apply_open_trade_bar_prefers_stop_when_tp_and_sl_hit_same_bar() -> None:
    trade = OpenTrade(
        side="BUY",
        entry_time=0,
        entry_price=1.1000,
        sl=1.0990,
        tp=1.1020,
        volume=0.05,
        risk_money=5.0,
        signal_key="BUY|1.10000",
        confirm_note="sdmss_buy_confirmed",
        initial_sl=1.0990,
        initial_tp=1.1020,
    )

    updated, closed = _apply_open_trade_bar(
        _cfg(),
        _runtime(),
        trade,
        {"time": 60, "open": 1.1000, "high": 1.1025, "low": 1.0985, "close": 1.1010},
        _info(),
    )

    assert updated is trade
    assert closed is not None
    assert closed.reason == "stop_loss"
    assert closed.exit_price == 1.0990
