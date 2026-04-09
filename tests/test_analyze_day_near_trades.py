from __future__ import annotations

from datetime import date

from src.risk.sizing import SymbolTradeInfo
from src.services.config import SymbolConfig
from src.tools.analyze_day_near_trades import (
    NearTradeRow,
    _build_money_summary,
    _build_timeline,
    _local_day_bounds_utc,
)


def _row(**kwargs) -> dict:
    return dict(kwargs)


def test_local_day_bounds_utc_handles_sofia_offset() -> None:
    start_utc, end_utc = _local_day_bounds_utc(date(2026, 4, 2), "Europe/Sofia")
    assert start_utc.isoformat() == "2026-04-01T21:00:00+00:00"
    assert end_utc.isoformat() == "2026-04-02T21:00:00+00:00"


def test_build_timeline_prefers_confirmed_anchor() -> None:
    setup_row = _row(
        setup_id="abc",
        status="CANCELED",
        created_at="2026-04-02T07:00:00+00:00",
        updated_at="2026-04-02T07:20:00+00:00",
        closed_reason="entry_blocked:SKIP_ORDER_BLOCK",
    )
    events = [
        _row(
            event_type="SETUP_PENDING",
            created_at_utc="2026-04-02T07:00:00+00:00",
        ),
        _row(
            event_type="SETUP_CONFIRMED",
            created_at_utc="2026-04-02T07:05:00+00:00",
        ),
    ]

    timeline = _build_timeline(setup_row, events)

    assert timeline.stage == "confirmed"
    assert timeline.anchor_reason == "confirmed"
    assert timeline.anchor_time_utc == "2026-04-02T07:05:00+00:00"
    assert timeline.canceled_reason == "entry_blocked:SKIP_ORDER_BLOCK"


def test_build_timeline_uses_pending_anchor_when_never_confirmed() -> None:
    setup_row = _row(
        setup_id="abc",
        status="EXPIRED",
        created_at="2026-04-02T08:00:00+00:00",
        updated_at="2026-04-02T08:15:00+00:00",
        closed_reason="expired_before_confirmation",
    )

    timeline = _build_timeline(setup_row, [])

    assert timeline.stage == "pending_only"
    assert timeline.anchor_reason == "pending_created"
    assert timeline.anchor_time_utc == "2026-04-02T08:00:00+00:00"
    assert timeline.canceled_reason == "expired_before_confirmation"


def test_build_money_summary_aggregates_branch_eur_values() -> None:
    cfg = SymbolConfig(
        symbol="EURUSD",
        timeframe="M5",
        bars=500,
        pivot_len=5,
        buffer_pips=0.3,
        sl_pips=10.0,
        rr=2.0,
        risk_pct=0.1,
        max_lot=0.25,
        max_spread_pips=1.8,
        cooldown_sec=300,
        magic=92001,
    )
    rows = [
        NearTradeRow(
            setup_id="a",
            symbol="EURUSD",
            timeframe="M5",
            magic=92001,
            branch_id="EURUSD|M5|92001",
            strategy_mode="liquidity_sweep",
            side="BUY",
            status="EXPIRED",
            created_at_utc="2026-04-08T06:00:00+00:00",
            stage="pending_only",
            anchor_reason="pending_created",
            anchor_time_utc="2026-04-08T06:00:00+00:00",
            confirmed_at_utc="",
            terminal_reason="expired_before_confirmation",
            entry_time_utc="",
            entry_price=0.0,
            exit_time_utc="",
            exit_price=0.0,
            outcome="trailing_stop",
            pnl_pips=10.0,
            pnl_r=1.0,
            mfe_pips=12.0,
            mae_pips=2.0,
            sl_pips=10.0,
            tp_pips=20.0,
            note="",
        ),
        NearTradeRow(
            setup_id="b",
            symbol="EURUSD",
            timeframe="M5",
            magic=92001,
            branch_id="EURUSD|M5|92001",
            strategy_mode="liquidity_sweep",
            side="BUY",
            status="CANCELED",
            created_at_utc="2026-04-08T07:00:00+00:00",
            stage="confirmed",
            anchor_reason="confirmed",
            anchor_time_utc="2026-04-08T07:05:00+00:00",
            confirmed_at_utc="2026-04-08T07:05:00+00:00",
            terminal_reason="entry_blocked:SKIP_ORDER_BLOCK",
            entry_time_utc="",
            entry_price=0.0,
            exit_time_utc="",
            exit_price=0.0,
            outcome="stop_loss",
            pnl_pips=-5.0,
            pnl_r=-0.5,
            mfe_pips=1.0,
            mae_pips=6.0,
            sl_pips=10.0,
            tp_pips=20.0,
            note="",
        ),
    ]
    info = SymbolTradeInfo(
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
    )

    summary = _build_money_summary(rows, {"EURUSD|M5|92001": cfg}, {"EURUSD": info})
    branch = summary["branch_rollup"][92001]

    assert round(summary["pip_value_by_symbol"]["EURUSD"], 2) == 10.0
    assert summary["max_lot_by_magic"][92001] == 0.25
    assert round(branch["pnl_pips"], 2) == 5.0
    assert round(branch["pnl_eur"], 2) == 12.5
    assert round(branch["positive_eur"], 2) == 25.0
    assert round(branch["confirmed_positive_eur"], 2) == 0.0
