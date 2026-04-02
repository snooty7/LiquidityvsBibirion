from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from types import SimpleNamespace

from src.engine.orchestrator import (
    branch_id,
    process_symbol,
    GlobalState,
    PendingSetup,
    SymbolState,
    checkpoint_state_snapshot,
    compute_r_multiple_trailing_stop,
    has_active_pending_setup,
    is_pending_expired,
    matches_signal_key,
    portfolio_caps_message,
    _revalidate_restored_pending,
    resolve_loss_guard,
    restore_runtime_state,
    semantic_setup_key,
    sync_open_positions_for_symbol,
)
from src.strategy.confirmations import ConfirmationResult
from src.persistence.maintenance import archive_and_prune_events
from src.persistence.models import (
    GuardStateRecord,
    OpenPositionRecord,
    PENDING_STATUS_PENDING,
    POSITION_STATUS_CLOSED,
    POSITION_STATUS_OPEN,
    SymbolRuntimeStateRecord,
)
from src.persistence.recovery import (
    bootstrap_recovery,
    build_pending_setup_record,
    compute_setup_expiry,
    latest_closed_bar_time,
    reconcile_broker_positions,
)
from src.persistence.repository import SQLiteRepository
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, RuntimeConfig, SymbolConfig, load_config


def _make_config(db_path: Path) -> AppConfig:
    runtime = RuntimeConfig(
        poll_seconds=5,
        dry_run=False,
        default_deviation=20,
        db_path=str(db_path),
        log_file="bot_events.csv",
        daily_loss_limit_usd=50.0,
        close_positions_on_daily_loss=True,
        max_loss_per_trade_usd=5.0,
        per_trade_loss_guard_mode="position_risk",
        per_trade_loss_risk_multiple=1.0,
        max_profit_per_trade_usd=6.0,
        trailing_stop_mode="off",
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
    symbol = SymbolConfig(
        symbol="EURUSD",
        timeframe="M5",
        bars=500,
        pivot_len=5,
        buffer_pips=0.3,
        sl_pips=10.0,
        rr=2.0,
        risk_pct=0.1,
        max_lot=0.1,
        max_spread_pips=1.8,
        cooldown_sec=300,
        magic=92001,
        confirmation_mode="sweep_displacement_mss",
    )
    return AppConfig(runtime=runtime, symbols=(symbol,))


@dataclass
class FakeAdapter:
    positions: dict[str, list[object]]

    def positions_get(self, symbol: str, magic: int | None = None) -> list[object]:
        items = list(self.positions.get(symbol, []))
        if magic is None:
            return items
        return [item for item in items if int(getattr(item, "magic", -1)) == int(magic)]


@dataclass
class CapOnlyAdapter:
    positions: dict[str, list[object]]

    def positions_get(self, symbol: str, magic: int | None = None) -> list[object]:
        items = list(self.positions.get(symbol, []))
        if magic is None:
            return items
        return [item for item in items if int(getattr(item, "magic", -1)) == int(magic)]


@dataclass
class RecoveryBarAdapter:
    positions: dict[str, list[object]]
    rates: dict[str, list[dict]]

    def positions_get(self, symbol: str, magic: int | None = None) -> list[object]:
        items = list(self.positions.get(symbol, []))
        if magic is None:
            return items
        return [item for item in items if int(getattr(item, "magic", -1)) == int(magic)]

    def copy_rates(self, symbol: str, timeframe: str, bars: int):
        return list(self.rates.get(symbol, []))


@dataclass
class SyncAdapter:
    positions: dict[str, list[object]]
    close_deal_by_ticket: dict[int, object]

    def positions_get(self, symbol: str, magic: int | None = None) -> list[object]:
        items = list(self.positions.get(symbol, []))
        if magic is None:
            return items
        return [item for item in items if int(getattr(item, "magic", -1)) == int(magic)]

    def latest_close_deal_for_position(self, ticket: int, now_utc: datetime, *, lookback_hours: int = 48):
        return self.close_deal_by_ticket.get(int(ticket))


@dataclass
class ProcessAdapter:
    rates: list[dict]

    def symbol_info(self, symbol: str):
        return SimpleNamespace(
            digits=5,
            point=0.00001,
            volume_min=0.01,
            volume_max=10.0,
            volume_step=0.01,
            trade_tick_value=1.0,
            trade_tick_size=0.00001,
            visible=True,
        )

    def pip_size(self, info: object) -> float:
        return 0.0001

    def copy_rates(self, symbol: str, timeframe: str, bars: int):
        return list(self.rates)

    def spread_pips(self, symbol: str, symbol_info: object | None = None) -> float:
        return 0.5

    def positions_get(self, symbol: str, magic: int | None = None) -> list[object]:
        return []

    def account_equity(self) -> float:
        return 10_000.0

    def quote_market_order(self, symbol: str, side: str, sl_pips: float, tp_pips: float):
        if side == "BUY":
            return 1.1000, 1.0990, 1.1020
        return 1.1000, 1.1010, 1.0980


def test_pending_setup_dedupe(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        expiry = compute_setup_expiry(candle_time=1_700_000_000, timeframe_seconds=300, expiry_bars=3)
        record_1 = build_pending_setup_record(
            symbol="EURUSD",
            timeframe="M5",
            side="BUY",
            level=1.1000,
            candle_time=1_700_000_000,
            signal_key="1700000000|BUY|1.10000",
            expires_at=expiry,
            context={"foo": "bar"},
            initial_status=PENDING_STATUS_PENDING,
        )
        first, created_first = repo.create_or_get_pending_setup(record_1)
        assert created_first is True

        record_2 = build_pending_setup_record(
            symbol="EURUSD",
            timeframe="M5",
            side="BUY",
            level=1.1000,
            candle_time=1_700_000_000,
            signal_key="1700000000|BUY|1.10000",
            expires_at=expiry,
            context={"foo": "bar"},
            initial_status=PENDING_STATUS_PENDING,
        )
        second, created_second = repo.create_or_get_pending_setup(record_2)
        assert created_second is False
        assert second.setup_id == first.setup_id
        assert second.dedupe_key == first.dedupe_key
    finally:
        repo.close()


def test_pending_setup_expiry_transition(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        record = build_pending_setup_record(
            symbol="EURUSD",
            timeframe="M5",
            side="SELL",
            level=1.0900,
            candle_time=1_700_000_100,
            signal_key="1700000100|SELL|1.09000",
            expires_at=10,
            context={"reason": "expiry-check"},
            initial_status=PENDING_STATUS_PENDING,
        )
        created, _ = repo.create_or_get_pending_setup(record)
        expired = repo.expire_pending_setups(now_ts=11)
        assert len(expired) == 1

        refreshed = repo.get_pending_setup_by_id(created.setup_id)
        assert refreshed is not None
        assert refreshed.status == "EXPIRED"
        assert refreshed.closed_reason == "expired"
    finally:
        repo.close()


def test_is_pending_expired_uses_bar_reference_time() -> None:
    pending = PendingSetup(
        setup_id="s1",
        dedupe_key="d1",
        signal_key="BUY|1.10000",
        side="BUY",
        level=1.1000,
        candle_time=1_700_000_000,
        expires_at=1_700_000_900,
    )

    assert is_pending_expired(pending, 1_700_000_899) is False
    assert is_pending_expired(pending, 1_700_000_900) is True


def test_bootstrap_recovery_expires_pending_by_latest_bar_time(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    app_config = _make_config(tmp_path / "state.db")
    try:
        pending_record = build_pending_setup_record(
            symbol="EURUSD",
            timeframe="M5",
            side="BUY",
            level=1.1000,
            candle_time=1_700_000_000,
            signal_key="BUY|1.10000",
            expires_at=1_700_000_900,
            context={},
            initial_status=PENDING_STATUS_PENDING,
        )
        created, _ = repo.create_or_get_pending_setup(pending_record)

        adapter = RecoveryBarAdapter(
            positions={"EURUSD": []},
            rates={
                "EURUSD": [
                    {"time": 1_700_001_200},
                    {"time": 1_700_001_500},
                    {"time": 1_700_001_800},
                ]
            },
        )
        pending_by_symbol, stats = bootstrap_recovery(adapter, app_config, repo, lambda _: None)

        assert pending_by_symbol == {}
        assert stats.expired_pending_count == 1
        refreshed = repo.get_pending_setup_by_id(created.setup_id)
        assert refreshed is not None
        assert refreshed.status == "EXPIRED"
    finally:
        repo.close()


def test_reconcile_broker_source_of_truth(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    logs: list[dict] = []
    try:
        repo.upsert_open_position(
            OpenPositionRecord(
                ticket=1001,
                symbol="EURUSD",
                magic=92001,
                setup_id=None,
                side="BUY",
                volume=0.10,
                open_price=1.1000,
                sl=1.0990,
                tp=1.1020,
                comment="SWEEP@1.10000",
                opened_at=1_700_000_001,
                status=POSITION_STATUS_OPEN,
            )
        )
        repo.upsert_open_position(
            OpenPositionRecord(
                ticket=1002,
                symbol="EURUSD",
                magic=92001,
                setup_id=None,
                side="SELL",
                volume=0.10,
                open_price=1.0900,
                sl=1.0910,
                tp=1.0880,
                comment="SWEEP@1.09000",
                opened_at=1_700_000_002,
                status=POSITION_STATUS_OPEN,
            )
        )

        broker_positions = [
            OpenPositionRecord(
                ticket=1002,
                symbol="EURUSD",
                magic=92001,
                setup_id=None,
                side="SELL",
                volume=0.10,
                open_price=1.0900,
                sl=1.0912,
                tp=1.0880,
                comment="SWEEP@1.09000",
                opened_at=1_700_000_002,
                status=POSITION_STATUS_OPEN,
            ),
            OpenPositionRecord(
                ticket=1003,
                symbol="EURUSD",
                magic=92001,
                setup_id=None,
                side="BUY",
                volume=0.10,
                open_price=1.1010,
                sl=1.1000,
                tp=1.1030,
                comment="SWEEP@1.10100",
                opened_at=1_700_000_003,
                status=POSITION_STATUS_OPEN,
            ),
        ]

        stats = reconcile_broker_positions(repo, broker_positions, logs.append)
        assert stats.broker_only_count == 1
        assert stats.local_only_closed_count == 1
        assert stats.mismatch_count == 1

        closed = repo.get_open_position(1001)
        assert closed is not None
        assert closed.status == POSITION_STATUS_CLOSED

        restored = repo.get_open_position(1003)
        assert restored is not None
        assert restored.status == POSITION_STATUS_OPEN
        assert restored.symbol == "EURUSD"

        events = {item["event"] for item in logs}
        assert "RECOVERY_BROKER_ONLY" in events
        assert "RECOVERY_LOCAL_ONLY_CLOSED" in events
        assert "RECOVERY_MISMATCH" in events
        assert "RECOVERY_ORPHAN_BROKER_POSITION" in events
    finally:
        repo.close()


def test_sync_open_positions_marks_unconfirmed_close_when_broker_missing_without_close_deal(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    repo = SQLiteRepository(str(db_path))
    app_config = _make_config(db_path)
    log_file = tmp_path / "events.csv"
    try:
        pending, _ = repo.create_or_get_pending_setup(
            build_pending_setup_record(
                symbol="EURUSD",
                timeframe="M5",
                side="BUY",
                level=1.1000,
                candle_time=1_700_000_000,
                signal_key="BUY|1.10000",
                expires_at=1_900_000_000,
                context={},
                initial_status=PENDING_STATUS_PENDING,
            )
        )
        repo.upsert_open_position(
            OpenPositionRecord(
                ticket=7001,
                symbol="EURUSD",
                magic=92001,
                setup_id=pending.setup_id,
                side="BUY",
                volume=0.10,
                open_price=1.1000,
                sl=1.0990,
                tp=1.1020,
                comment="SWEEP@1.10000|ab",
                opened_at=1_700_000_001,
                status=POSITION_STATUS_OPEN,
            )
        )
        adapter = SyncAdapter(positions={"EURUSD": []}, close_deal_by_ticket={})

        sync_open_positions_for_symbol(adapter, app_config.symbols[0], app_config, repo, log_file)

        closed = repo.get_open_position(7001)
        assert closed is not None
        assert closed.status == POSITION_STATUS_CLOSED
        assert closed.close_reason == "missing_on_broker_runtime_sync_unconfirmed"

        events = repo.list_events(event_type="POSITION_CLOSED_UNCONFIRMED")
        assert len(events) == 1
    finally:
        repo.close()


def test_restart_continuity_hydration(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    repo = SQLiteRepository(str(db_path))
    app_config = _make_config(db_path)
    logs: list[dict] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        repo.save_guard_state(
            GuardStateRecord(
                day_key=today,
                daily_realized_pnl=-12.34,
                daily_loss_reached=False,
                daily_loss_announced=False,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        cfg = app_config.symbols[0]
        runtime_key = branch_id(cfg)
        repo.save_symbol_runtime_state(
            SymbolRuntimeStateRecord(
                symbol=runtime_key,
                timeframe="M5",
                last_trade_ts=1234.0,
                cooldown_until=1567.0,
                entry_count=3,
                last_processed_bar_time=1_700_000_050,
                last_signal_key="1700000050|BUY|1.10050",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        repo.set_risk_retry(
            ticket=4444,
            symbol="EURUSD",
            retry_after=2222.0,
            reason="max_loss $5.00",
            last_error="retcode=10030",
        )

        pending_record = build_pending_setup_record(
            symbol="EURUSD",
            timeframe="M5",
            side="BUY",
            level=1.1005,
            candle_time=1_700_000_050,
            signal_key="1700000050|BUY|1.10050",
            expires_at=1_900_000_000,
            context={"ctx": "value", "magic": 92001, "branch_id": runtime_key},
            initial_status=PENDING_STATUS_PENDING,
        )
        saved_pending, _ = repo.create_or_get_pending_setup(pending_record)

        broker_pos = SimpleNamespace(
            ticket=5555,
            symbol="EURUSD",
            magic=92001,
            type=0,
            volume=0.10,
            price_open=1.1010,
            sl=1.1000,
            tp=1.1030,
            comment="SWEEP@1.10100",
            time=1_700_000_060,
        )
        adapter = FakeAdapter(positions={"EURUSD": [broker_pos]})

        pending_by_branch, stats = bootstrap_recovery(adapter, app_config, repo, logs.append)
        assert stats.broker_only_count == 1

        states = {runtime_key: SymbolState()}
        global_state = GlobalState()
        restore_runtime_state(repo, app_config, states, global_state, pending_by_branch)

        restored = states[runtime_key]
        assert global_state.day_key == today
        assert global_state.daily_realized_pnl == -12.34
        assert restored.last_trade_ts == 1234.0
        assert restored.cooldown_until == 1567.0
        assert restored.entry_count == 3
        assert restored.last_processed_bar_time == 1_700_000_050
        assert restored.last_signal_key == "1700000050|BUY|1.10050"
        assert restored.risk_close_retry_after[4444] == 2222.0
        assert restored.pending_setup is not None
        assert restored.pending_setup.setup_id == saved_pending.setup_id
        assert restored.pending_setup.requires_revalidation is True
    finally:
        repo.close()


def test_sync_open_positions_ignores_other_magic_same_symbol(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    repo = SQLiteRepository(str(db_path))
    app_config = AppConfig(
        runtime=_make_config(db_path).runtime,
        symbols=(
            SymbolConfig(
                **{**_make_config(db_path).symbols[0].__dict__},
            ),
            SymbolConfig(
                **{**_make_config(db_path).symbols[0].__dict__, "timeframe": "M30", "magic": 92008},
            ),
        ),
    )
    log_file = tmp_path / "events.csv"

    try:
        pending, _ = repo.create_or_get_pending_setup(
            build_pending_setup_record(
                symbol="EURUSD",
                timeframe="M5",
                side="BUY",
                level=1.1000,
                candle_time=1_700_000_000,
                signal_key="BUY|1.10000",
                expires_at=1_900_000_000,
                context={"magic": 92001},
                initial_status=PENDING_STATUS_PENDING,
            )
        )
        repo.upsert_open_position(
            OpenPositionRecord(
                ticket=7001,
                symbol="EURUSD",
                magic=92001,
                setup_id=pending.setup_id,
                side="BUY",
                volume=0.10,
                open_price=1.1000,
                sl=1.0990,
                tp=1.1020,
                comment="SWEEP@1.10000|ab",
                opened_at=1_700_000_001,
                status=POSITION_STATUS_OPEN,
            )
        )
        adapter = SyncAdapter(positions={"EURUSD": []}, close_deal_by_ticket={})

        sync_open_positions_for_symbol(adapter, app_config.symbols[1], app_config, repo, log_file)

        still_open = repo.get_open_position(7001)
        assert still_open is not None
        assert still_open.status == POSITION_STATUS_OPEN
        assert repo.list_events(event_type="POSITION_CLOSED_UNCONFIRMED") == []
    finally:
        repo.close()


def test_risk_retry_metadata_persisted(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        repo.set_risk_retry(
            ticket=9999,
            symbol="EURUSD",
            retry_after=10.0,
            reason="max_loss $5.00",
            last_error="retcode=1",
        )
        repo.set_risk_retry(
            ticket=9999,
            symbol="EURUSD",
            retry_after=20.0,
            reason="max_loss $5.00",
            last_error="retcode=2",
        )
        records = repo.list_risk_retries("EURUSD")
        assert len(records) == 1
        item = records[0]
        assert item.ticket == 9999
        assert item.retry_after == 20.0
        assert item.reason == "max_loss $5.00"
        assert item.last_error == "retcode=2"
        assert item.attempts == 2
    finally:
        repo.close()


def test_event_schema_persistence(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        repo.set_bot_instance_id("bot-test-1")
        event = repo.append_event(
            event_type="RISK_CLOSE_FAIL",
            trading_day="2026-03-12",
            symbol="EURUSD",
            setup_id="setup-x",
            ticket=555,
            payload={"reason": "max_loss", "retry_after": 123.0},
            created_at_utc="2026-03-12T10:00:00+00:00",
        )
        assert event.event_type == "RISK_CLOSE_FAIL"
        assert event.trading_day == "2026-03-12"
        assert event.symbol == "EURUSD"
        assert event.setup_id == "setup-x"
        assert event.ticket == 555
        assert event.bot_instance_id == "bot-test-1"
        parsed = json.loads(event.payload_json)
        assert parsed["reason"] == "max_loss"
    finally:
        repo.close()


def test_atomic_pending_trigger_transition_rolls_back_on_event_failure(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        pending, _ = repo.create_or_get_pending_setup(
            build_pending_setup_record(
                symbol="EURUSD",
                timeframe="M5",
                side="BUY",
                level=1.1000,
                candle_time=1_700_000_000,
                signal_key="1700000000|BUY|1.10000",
                expires_at=1_900_000_000,
                context={"ctx": "x"},
                initial_status=PENDING_STATUS_PENDING,
            )
        )
        try:
            with repo.transaction():
                repo.transition_pending_setup(
                    pending.setup_id,
                    status="EXECUTED",
                    executed_ticket=12345,
                    last_note="triggered",
                )
                repo.append_event(
                    event_type="TRADE_OK",
                    symbol="EURUSD",
                    setup_id=pending.setup_id,
                    ticket=12345,
                    payload={"bad": {1, 2, 3}},
                )
        except TypeError:
            pass

        refreshed = repo.get_pending_setup_by_id(pending.setup_id)
        assert refreshed is not None
        assert refreshed.status == PENDING_STATUS_PENDING
        assert repo.list_events(event_type="TRADE_OK") == []
    finally:
        repo.close()


def test_atomic_retry_and_event_rolls_back_on_failure(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        try:
            with repo.transaction():
                repo.set_risk_retry(
                    ticket=777,
                    symbol="EURUSD",
                    retry_after=100.0,
                    reason="max_loss",
                    last_error="retcode=x",
                )
                repo.append_event(
                    event_type="RISK_CLOSE_FAIL",
                    symbol="EURUSD",
                    ticket=777,
                    payload={"bad": {1}},
                )
        except TypeError:
            pass

        assert repo.list_risk_retries("EURUSD") == []
        assert repo.list_events(event_type="RISK_CLOSE_FAIL") == []
    finally:
        repo.close()


def test_reconcile_transaction_rolls_back_if_event_write_fails(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        repo.upsert_open_position(
            OpenPositionRecord(
                ticket=5001,
                symbol="EURUSD",
                magic=92001,
                setup_id=None,
                side="BUY",
                volume=0.10,
                open_price=1.1000,
                sl=1.0990,
                tp=1.1020,
                comment="SWEEP@1.10000",
                opened_at=1_700_000_001,
                status=POSITION_STATUS_OPEN,
            )
        )

        original = repo.append_event

        def broken_append(*args, **kwargs):
            raise RuntimeError("boom")

        repo.append_event = broken_append  # type: ignore[assignment]
        try:
            try:
                reconcile_broker_positions(repo, [], lambda _: None)
            except RuntimeError:
                pass
        finally:
            repo.append_event = original  # type: ignore[assignment]

        still_open = repo.get_open_position(5001)
        assert still_open is not None
        assert still_open.status == POSITION_STATUS_OPEN
    finally:
        repo.close()


def test_setup_link_mismatch_policy_keeps_local(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        pending_local, _ = repo.create_or_get_pending_setup(
            build_pending_setup_record(
                symbol="EURUSD",
                timeframe="M5",
                side="BUY",
                level=1.1000,
                candle_time=1_700_000_000,
                signal_key="1700000000|BUY|1.10000",
                expires_at=1_900_000_000,
                context={},
                initial_status=PENDING_STATUS_PENDING,
            )
        )
        pending_broker, _ = repo.create_or_get_pending_setup(
            build_pending_setup_record(
                symbol="EURUSD",
                timeframe="M5",
                side="BUY",
                level=1.1010,
                candle_time=1_700_000_010,
                signal_key="1700000010|BUY|1.10100",
                expires_at=1_900_000_000,
                context={},
                initial_status=PENDING_STATUS_PENDING,
            )
        )
        repo.upsert_open_position(
            OpenPositionRecord(
                ticket=6001,
                symbol="EURUSD",
                magic=92001,
                setup_id=pending_local.setup_id,
                side="BUY",
                volume=0.10,
                open_price=1.1000,
                sl=1.0990,
                tp=1.1020,
                comment="SWEEP@1.10000",
                opened_at=1_700_000_001,
                status=POSITION_STATUS_OPEN,
            )
        )
        broker_positions = [
            OpenPositionRecord(
                ticket=6001,
                symbol="EURUSD",
                magic=92001,
                setup_id=pending_broker.setup_id,
                side="BUY",
                volume=0.10,
                open_price=1.1000,
                sl=1.0995,
                tp=1.1020,
                comment="SWEEP@1.10000",
                opened_at=1_700_000_001,
                status=POSITION_STATUS_OPEN,
            )
        ]

        reconcile_broker_positions(repo, broker_positions, lambda _: None)
        merged = repo.get_open_position(6001)
        assert merged is not None
        assert merged.setup_id == pending_local.setup_id

        events = repo.list_events(event_type="RECOVERY_SETUP_LINK_MISMATCH")
        assert len(events) == 1
    finally:
        repo.close()


def test_portfolio_cap_continuity_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    base = _make_config(db_path)
    relaxed_runtime = RuntimeConfig(
        poll_seconds=base.runtime.poll_seconds,
        dry_run=base.runtime.dry_run,
        default_deviation=base.runtime.default_deviation,
        db_path=base.runtime.db_path,
        log_file=base.runtime.log_file,
        daily_loss_limit_usd=base.runtime.daily_loss_limit_usd,
        close_positions_on_daily_loss=base.runtime.close_positions_on_daily_loss,
        max_loss_per_trade_usd=base.runtime.max_loss_per_trade_usd,
        per_trade_loss_guard_mode=base.runtime.per_trade_loss_guard_mode,
        per_trade_loss_risk_multiple=base.runtime.per_trade_loss_risk_multiple,
        max_profit_per_trade_usd=base.runtime.max_profit_per_trade_usd,
        trailing_stop_mode=base.runtime.trailing_stop_mode,
        trailing_activation_r=base.runtime.trailing_activation_r,
        trailing_gap_r=base.runtime.trailing_gap_r,
        trailing_remove_tp_on_activation=base.runtime.trailing_remove_tp_on_activation,
        risk_close_retry_sec=base.runtime.risk_close_retry_sec,
        max_open_positions_total=5,
        max_total_open_risk_pct=0.0,
        checkpoint_interval_sec=base.runtime.checkpoint_interval_sec,
        maintenance_interval_sec=base.runtime.maintenance_interval_sec,
        event_retention_days=base.runtime.event_retention_days,
        event_retention_batch_size=base.runtime.event_retention_batch_size,
        event_archive_dir=base.runtime.event_archive_dir,
        push_notifications_enabled=base.runtime.push_notifications_enabled,
        push_notification_url=base.runtime.push_notification_url,
        push_notification_token=base.runtime.push_notification_token,
        push_notification_timeout_sec=base.runtime.push_notification_timeout_sec,
    )
    app_config = AppConfig(runtime=relaxed_runtime, symbols=base.symbols)
    adapter = CapOnlyAdapter(
        positions={
            "EURUSD": [SimpleNamespace(ticket=1, magic=92001)],
        }
    )
    cap_message = portfolio_caps_message(adapter, app_config, app_config.symbols[0], equity=10_000.0)
    # default cap is 5 positions, so no cap yet
    assert cap_message is None

    strict_runtime = RuntimeConfig(
        poll_seconds=5,
        dry_run=False,
        default_deviation=20,
        db_path=str(db_path),
        log_file="bot_events.csv",
        daily_loss_limit_usd=50.0,
        close_positions_on_daily_loss=True,
        max_loss_per_trade_usd=5.0,
        per_trade_loss_guard_mode="fixed_usd",
        per_trade_loss_risk_multiple=1.0,
        max_profit_per_trade_usd=6.0,
        trailing_stop_mode="off",
        trailing_activation_r=1.0,
        trailing_gap_r=1.0,
        trailing_remove_tp_on_activation=True,
        risk_close_retry_sec=20,
        max_open_positions_total=1,
        max_total_open_risk_pct=0.0,
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
    strict_cfg = AppConfig(runtime=strict_runtime, symbols=app_config.symbols)
    cap_hit = portfolio_caps_message(adapter, strict_cfg, strict_cfg.symbols[0], equity=10_000.0)
    assert cap_hit is not None


def test_restored_pending_requires_revalidation_semantic_key() -> None:
    pending = PendingSetup(
        setup_id="s1",
        dedupe_key="d1",
        signal_key="BUY|1.10000",
        side="BUY",
        level=1.1000,
        candle_time=1_700_000_000,
        expires_at=1_900_000_000,
        requires_revalidation=True,
    )
    rates = [
        {"time": 1_699_999_900},
        {"time": 1_700_000_000},
        {"time": 1_700_000_060},
    ]

    ok, note = _revalidate_restored_pending(
        pending=pending,
        mode="none",
        rates=rates,
        signal=SimpleNamespace(candle_time=1_700_000_000, side="BUY", level=1.1000),
    )
    assert ok is True
    assert note == "revalidated"

    fail_ok, fail_note = _revalidate_restored_pending(
        pending=pending,
        mode="none",
        rates=rates,
        signal=SimpleNamespace(candle_time=1_700_000_000, side="SELL", level=1.1000),
    )
    assert fail_ok is False
    assert "semantic_key_mismatch" in fail_note


def test_restored_pending_revalidation_accepts_legacy_signal_key() -> None:
    pending = PendingSetup(
        setup_id="s1",
        dedupe_key="d1",
        signal_key="1700000000|BUY|1.10000",
        side="BUY",
        level=1.1000,
        candle_time=1_700_000_000,
        expires_at=1_900_000_000,
        requires_revalidation=True,
    )
    rates = [
        {"time": 1_699_999_900},
        {"time": 1_700_000_000},
        {"time": 1_700_000_060},
    ]

    ok, note = _revalidate_restored_pending(
        pending=pending,
        mode="none",
        rates=rates,
        signal=SimpleNamespace(candle_time=1_700_000_000, side="BUY", level=1.1000),
    )

    assert ok is True
    assert note == "revalidated"


def test_stable_semantic_setup_key_blocks_duplicate_setup_across_bars() -> None:
    key_a = semantic_setup_key(1_700_000_000, "BUY", 1.1000)
    key_b = semantic_setup_key(1_700_000_300, "BUY", 1.1000)

    assert key_a == key_b
    assert matches_signal_key(key_a, 1_700_000_300, "BUY", 1.1000) is True


def test_event_retention_archives_then_prunes(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        repo.set_bot_instance_id("retention-test")
        repo.append_event(
            event_type="RECOVERY_MISMATCH",
            trading_day="2026-01-01",
            symbol="EURUSD",
            payload={"x": 1},
            created_at_utc="2026-01-01T10:00:00+00:00",
        )
        repo.append_event(
            event_type="RECOVERY_MISMATCH",
            trading_day="2026-03-12",
            symbol="EURUSD",
            payload={"x": 2},
            created_at_utc="2026-03-12T10:00:00+00:00",
        )

        result = archive_and_prune_events(
            repo=repo,
            now_utc=datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
            retention_days=30,
            archive_dir=str(tmp_path / "archives"),
            batch_size=100,
            dry_run=False,
        )
        assert result.archived_count == 1
        assert result.deleted_count == 1
        assert result.archive_file is not None
        assert Path(result.archive_file).exists()

        remaining = repo.list_events()
        assert len(remaining) == 1
        assert remaining[0].trading_day == "2026-03-12"
    finally:
        repo.close()


def test_checkpoint_snapshot_persists_guard_and_runtime(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    app_config = _make_config(db_path)
    repo = SQLiteRepository(str(db_path))
    try:
        cfg = app_config.symbols[0]
        runtime_key = branch_id(cfg)
        states = {
            runtime_key: SymbolState(
                last_trade_ts=100.0,
                cooldown_until=200.0,
                entry_count=4,
                last_processed_bar_time=123456,
                last_signal_key="123456|BUY|1.10000",
            )
        }
        global_state = GlobalState(
            day_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            daily_realized_pnl=-9.5,
            daily_loss_reached=False,
            daily_loss_announced=False,
        )

        checkpoint_state_snapshot(
            repo=repo,
            app_config=app_config,
            states=states,
            global_state=global_state,
            log_file=tmp_path / "events.csv",
        )

        guard = repo.get_guard_state()
        assert guard.daily_realized_pnl == -9.5
        sym = repo.get_symbol_runtime_state(runtime_key)
        assert sym is not None
        assert sym.entry_count == 4
        assert sym.last_processed_bar_time == 123456

        checkpoint_events = repo.list_events(event_type="CHECKPOINT_SNAPSHOT")
        assert len(checkpoint_events) == 1
    finally:
        repo.close()


def test_resolve_loss_guard_uses_position_risk_when_configured() -> None:
    runtime = SimpleNamespace(
        per_trade_loss_guard_mode="position_risk",
        per_trade_loss_risk_multiple=1.0,
        max_loss_per_trade_usd=3.0,
    )
    position = SimpleNamespace(price_open=1.15148, sl=1.15248, volume=0.10)
    symbol_info = SymbolTradeInfo(
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
    )

    limit_money, reason, mode = resolve_loss_guard(runtime, position, symbol_info)

    assert limit_money is not None
    assert math.isclose(limit_money, 10.0, rel_tol=0.0, abs_tol=1e-9)
    assert reason == "max_loss risk x1.00 ($10.00)"
    assert mode == "position_risk"


def test_restore_runtime_state_separates_branches_for_same_symbol(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    repo = SQLiteRepository(str(db_path))
    app_config = AppConfig(
        runtime=RuntimeConfig(
            poll_seconds=5,
            dry_run=False,
            default_deviation=20,
            db_path=str(db_path),
            log_file="bot_events.csv",
            daily_loss_limit_usd=50.0,
            close_positions_on_daily_loss=True,
            max_loss_per_trade_usd=5.0,
            per_trade_loss_guard_mode="position_risk",
            per_trade_loss_risk_multiple=1.0,
            max_profit_per_trade_usd=0.0,
            trailing_stop_mode="off",
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
        ),
        symbols=(
            SymbolConfig(
                symbol="EURUSD",
                timeframe="M5",
                bars=500,
                pivot_len=5,
                buffer_pips=0.3,
                sl_pips=10.0,
                rr=2.0,
                risk_pct=0.1,
                max_lot=0.1,
                max_spread_pips=1.8,
                cooldown_sec=300,
                magic=92001,
                confirmation_mode="sweep_displacement_mss",
            ),
            SymbolConfig(
                symbol="EURUSD",
                timeframe="M1",
                bars=500,
                pivot_len=5,
                buffer_pips=0.3,
                sl_pips=5.0,
                rr=1.5,
                risk_pct=0.03,
                max_lot=0.02,
                max_spread_pips=1.2,
                cooldown_sec=1800,
                magic=92009,
                confirmation_mode="session_open_scalp_c1",
                strategy_mode="session_open_scalp",
                use_bias_filter=False,
                use_order_block_filter=False,
            ),
        ),
    )

    try:
        primary = app_config.symbols[0]
        scalp = app_config.symbols[1]
        primary_key = branch_id(primary)
        scalp_key = branch_id(scalp)

        repo.save_symbol_runtime_state(
            SymbolRuntimeStateRecord(
                symbol=primary_key,
                timeframe=primary.timeframe,
                last_trade_ts=111.0,
                cooldown_until=222.0,
                entry_count=1,
                last_processed_bar_time=1_700_000_100,
                last_signal_key="primary-key",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        repo.save_symbol_runtime_state(
            SymbolRuntimeStateRecord(
                symbol=scalp_key,
                timeframe=scalp.timeframe,
                last_trade_ts=333.0,
                cooldown_until=444.0,
                entry_count=7,
                last_processed_bar_time=1_700_000_200,
                last_signal_key="scalp-key",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )

        pending_record = build_pending_setup_record(
            symbol=scalp.symbol,
            timeframe=scalp.timeframe,
            side="BUY",
            level=1.1050,
            candle_time=1_700_000_200,
            signal_key="1700000200|BUY|1.10500",
            expires_at=1_900_000_000,
            context={"magic": int(scalp.magic), "branch_id": scalp_key},
            initial_status=PENDING_STATUS_PENDING,
        )
        repo.create_or_get_pending_setup(pending_record)

        states = {primary_key: SymbolState(), scalp_key: SymbolState()}
        global_state = GlobalState()

        restore_runtime_state(
            repo=repo,
            app_config=app_config,
            states=states,
            global_state=global_state,
            pending_by_branch={scalp_key: repo.get_latest_active_pending_setup("EURUSD")},
        )

        assert states[primary_key].last_trade_ts == 111.0
        assert states[primary_key].entry_count == 1
        assert states[primary_key].pending_setup is None

        assert states[scalp_key].last_trade_ts == 333.0
        assert states[scalp_key].entry_count == 7
        assert states[scalp_key].pending_setup is not None
        assert states[scalp_key].pending_setup.requires_revalidation is True
    finally:
        repo.close()


def test_resolve_loss_guard_falls_back_to_fixed_usd_without_usable_sl() -> None:
    runtime = SimpleNamespace(
        per_trade_loss_guard_mode="position_risk",
        per_trade_loss_risk_multiple=1.0,
        max_loss_per_trade_usd=3.0,
    )
    position = SimpleNamespace(price_open=1.15148, sl=0.0, volume=0.10)
    symbol_info = SymbolTradeInfo(
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
    )

    limit_money, reason, mode = resolve_loss_guard(runtime, position, symbol_info)

    assert limit_money == 3.0
    assert reason == "max_loss $3.00"
    assert mode == "fixed_usd"


def test_default_config_uses_position_risk_guard() -> None:
    cfg = load_config(Path("nonexistent-settings.json"))

    assert cfg.runtime.per_trade_loss_guard_mode == "position_risk"
    assert cfg.runtime.per_trade_loss_risk_multiple == 1.0


def test_example_config_uses_position_risk_guard() -> None:
    example_path = Path(__file__).resolve().parents[1] / "config" / "settings.example.json"
    payload = json.loads(example_path.read_text(encoding="utf-8-sig"))

    assert payload["runtime"]["per_trade_loss_guard_mode"] == "position_risk"
    assert payload["runtime"]["per_trade_loss_risk_multiple"] == 1.0


def test_load_config_rejects_invalid_loss_guard_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "bad.json"
    config_path.write_text(
        json.dumps(
            {
                "runtime": {"per_trade_loss_guard_mode": "bad_mode"},
                "symbols": [{"symbol": "EURUSD", "magic": 92001}],
            }
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
        raise AssertionError("Expected ValueError for invalid per_trade_loss_guard_mode")
    except ValueError as exc:
        assert "Unsupported per_trade_loss_guard_mode" in str(exc)


def test_load_config_rejects_enabled_push_without_url(tmp_path: Path) -> None:
    config_path = tmp_path / "bad_push.json"
    config_path.write_text(
        json.dumps(
            {
                "runtime": {"push_notifications_enabled": True},
                "symbols": [{"symbol": "EURUSD", "magic": 92001}],
            }
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
        raise AssertionError("Expected ValueError for missing push_notification_url")
    except ValueError as exc:
        assert "push_notification_url is required" in str(exc)


def test_load_config_rejects_order_block_override_below_base(tmp_path: Path) -> None:
    config_path = tmp_path / "bad_ob_override.json"
    config_path.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "symbol": "EURUSD",
                        "magic": 92001,
                        "order_block_max_distance_pips": 8.0,
                        "order_block_strong_override_max_distance_pips": 7.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
        raise AssertionError("Expected ValueError for invalid order block override distance")
    except ValueError as exc:
        assert "order_block_strong_override_max_distance_pips must be >=" in str(exc)


def test_compute_r_multiple_trailing_stop_buy_moves_to_break_even_at_one_r() -> None:
    desired_sl = compute_r_multiple_trailing_stop(
        side="BUY",
        open_price=1.1000,
        current_exit_price_value=1.1010,
        current_sl=1.0990,
        risk_distance_price=0.0010,
        activation_r=1.0,
        gap_r=1.0,
    )
    assert desired_sl is not None
    assert math.isclose(desired_sl, 1.1000, rel_tol=0.0, abs_tol=1e-9)


def test_compute_r_multiple_trailing_stop_sell_locks_one_r_at_two_r_profit() -> None:
    desired_sl = compute_r_multiple_trailing_stop(
        side="SELL",
        open_price=1.2000,
        current_exit_price_value=1.1980,
        current_sl=1.2010,
        risk_distance_price=0.0010,
        activation_r=1.0,
        gap_r=1.0,
    )
    assert desired_sl is not None
    assert math.isclose(desired_sl, 1.1990, rel_tol=0.0, abs_tol=1e-9)


def test_compute_r_multiple_trailing_stop_does_not_loosen_existing_stop() -> None:
    desired_sl = compute_r_multiple_trailing_stop(
        side="BUY",
        open_price=1.1000,
        current_exit_price_value=1.1015,
        current_sl=1.1008,
        risk_distance_price=0.0010,
        activation_r=1.0,
        gap_r=1.0,
    )
    assert desired_sl is None


def test_has_active_pending_setup_blocks_new_confirmed_modes() -> None:
    state = SymbolState(
        pending_setup=PendingSetup(
            setup_id="s1",
            dedupe_key="d1",
            signal_key="k1",
            side="BUY",
            level=1.1000,
            candle_time=1,
            expires_at=9999999999,
            status="PENDING",
        )
    )
    assert has_active_pending_setup(state, "sweep_displacement_mss") is True
    assert has_active_pending_setup(state, "c3") is True
    assert has_active_pending_setup(state, "none") is False


def test_confirmed_setup_blocked_by_bias_is_canceled_not_left_confirmed(tmp_path: Path, monkeypatch) -> None:
    import src.engine.orchestrator as orch

    db_path = tmp_path / "state.db"
    repo = SQLiteRepository(str(db_path))
    app_config = _make_config(db_path)
    cfg = app_config.symbols[0]
    log_file = tmp_path / "events.csv"
    rates = [
        {"time": 100, "open": 1.1000, "high": 1.1005, "low": 1.0995, "close": 1.1001},
        {"time": 400, "open": 1.1001, "high": 1.1004, "low": 1.0997, "close": 1.1000},
        {"time": 700, "open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1001},
    ]
    adapter = ProcessAdapter(rates=rates)

    pending_record = build_pending_setup_record(
        symbol=cfg.symbol,
        timeframe=cfg.timeframe,
        side="SELL",
        level=1.1000,
        candle_time=100,
        signal_key="SELL|1.10000",
        expires_at=10_000,
        context={},
        initial_status=PENDING_STATUS_PENDING,
    )

    stored, _ = repo.create_or_get_pending_setup(pending_record)
    state = SymbolState(
        pending_setup=PendingSetup(
            setup_id=stored.setup_id,
            dedupe_key=stored.dedupe_key,
            signal_key=stored.signal_key,
            side=stored.side,
            level=stored.level,
            candle_time=stored.candle_time,
            expires_at=stored.expires_at,
            status=stored.status,
            context={},
        )
    )

    monkeypatch.setattr(
        orch,
        "evaluate_pending_confirmation",
        lambda adapter, cfg, pending, rates: ConfirmationResult(True, False, "sdmss_sell_confirmed"),
    )
    monkeypatch.setattr(
        orch,
        "evaluate_bias",
        lambda rates, period: {"ok_buy": False, "ok_sell": False, "note": "bias_blocked"},
    )

    try:
        process_symbol(adapter, cfg, app_config, state, log_file, repo)

        refreshed = repo.get_pending_setup_by_id(stored.setup_id)
        assert refreshed is not None
        assert refreshed.status == "CANCELED"
        assert refreshed.closed_reason == "entry_blocked:SKIP_BIAS"

        content = log_file.read_text(encoding="utf-8")
        assert "SETUP_CONFIRMED" in content
        assert "SKIP_BIAS" in content
        assert stored.setup_id in content
    finally:
        repo.close()
