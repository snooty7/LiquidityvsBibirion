from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from src.engine.orchestrator import (
    GlobalState,
    PendingSetup,
    SymbolState,
    checkpoint_state_snapshot,
    portfolio_caps_message,
    _revalidate_restored_pending,
    restore_runtime_state,
)
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
    reconcile_broker_positions,
)
from src.persistence.repository import SQLiteRepository
from src.services.config import AppConfig, RuntimeConfig, SymbolConfig


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
        max_profit_per_trade_usd=6.0,
        risk_close_retry_sec=20,
        max_open_positions_total=5,
        max_total_open_risk_pct=0.5,
        checkpoint_interval_sec=5,
        maintenance_interval_sec=3600,
        event_retention_days=30,
        event_retention_batch_size=5000,
        event_archive_dir="state_archives",
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
        repo.save_symbol_runtime_state(
            SymbolRuntimeStateRecord(
                symbol="EURUSD",
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
            context={"ctx": "value"},
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

        pending_by_symbol, stats = bootstrap_recovery(adapter, app_config, repo, logs.append)
        assert stats.broker_only_count == 1

        states = {"EURUSD": SymbolState()}
        global_state = GlobalState()
        restore_runtime_state(repo, app_config, states, global_state, pending_by_symbol)

        restored = states["EURUSD"]
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
        max_profit_per_trade_usd=base.runtime.max_profit_per_trade_usd,
        risk_close_retry_sec=base.runtime.risk_close_retry_sec,
        max_open_positions_total=5,
        max_total_open_risk_pct=0.0,
        checkpoint_interval_sec=base.runtime.checkpoint_interval_sec,
        maintenance_interval_sec=base.runtime.maintenance_interval_sec,
        event_retention_days=base.runtime.event_retention_days,
        event_retention_batch_size=base.runtime.event_retention_batch_size,
        event_archive_dir=base.runtime.event_archive_dir,
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
        max_profit_per_trade_usd=6.0,
        risk_close_retry_sec=20,
        max_open_positions_total=1,
        max_total_open_risk_pct=0.0,
        checkpoint_interval_sec=5,
        maintenance_interval_sec=3600,
        event_retention_days=30,
        event_retention_batch_size=5000,
        event_archive_dir="state_archives",
    )
    strict_cfg = AppConfig(runtime=strict_runtime, symbols=app_config.symbols)
    cap_hit = portfolio_caps_message(adapter, strict_cfg, strict_cfg.symbols[0], equity=10_000.0)
    assert cap_hit is not None


def test_restored_pending_requires_revalidation_semantic_key() -> None:
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

    fail_ok, fail_note = _revalidate_restored_pending(
        pending=pending,
        mode="none",
        rates=rates,
        signal=SimpleNamespace(candle_time=1_700_000_000, side="SELL", level=1.1000),
    )
    assert fail_ok is False
    assert "semantic_key_mismatch" in fail_note


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
        states = {
            "EURUSD": SymbolState(
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
        sym = repo.get_symbol_runtime_state("EURUSD")
        assert sym is not None
        assert sym.entry_count == 4
        assert sym.last_processed_bar_time == 123456

        checkpoint_events = repo.list_events(event_type="CHECKPOINT_SNAPSHOT")
        assert len(checkpoint_events) == 1
    finally:
        repo.close()
