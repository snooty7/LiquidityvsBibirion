from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
import csv
import math
import time
from uuid import uuid4

from src.execution.mt5_adapter import MT5Adapter
from src.notifications.push import send_push_notification
from src.persistence.maintenance import archive_and_prune_events
from src.persistence.models import (
    GuardStateRecord,
    OpenPositionRecord,
    PENDING_STATUS_CANCELED,
    PENDING_STATUS_CONFIRMED,
    PENDING_STATUS_EXECUTED,
    PENDING_STATUS_EXPIRED,
    PENDING_STATUS_FAILED,
    PENDING_STATUS_PENDING,
    PENDING_STATUS_REJECTED,
    PENDING_TERMINAL_STATUSES,
    POSITION_STATUS_OPEN,
    PendingSetupRecord,
    SymbolRuntimeStateRecord,
)
from src.persistence.recovery import bootstrap_recovery, build_pending_setup_record, compute_setup_expiry
from src.persistence.repository import SQLiteRepository
from src.risk.sizing import SymbolTradeInfo, calc_lot_by_risk, calc_position_risk_money
from src.services.config import AppConfig, SymbolConfig, load_config
from src.strategy.confirmations import (
    ConfirmationResult,
    evaluate_c3_c4_confirmation,
    evaluate_cisd_confirmation,
    evaluate_sweep_displacement_mss_confirmation,
)
from src.strategy.filters import (
    evaluate_bias,
    find_local_order_block,
    order_block_distance_pips,
    order_block_note,
    resolve_order_block_distance_limit_pips,
)
from src.strategy.liquidity import (
    detect_sweep_signal,
    evaluate_range_filter,
    evaluate_sweep_significance,
    extract_pivot_levels,
)


LOG_FIELDS = [
    "ts",
    "symbol",
    "timeframe",
    "strategy",
    "event",
    "position",
    "side",
    "level",
    "candle_time",
    "spread_pips",
    "volume",
    "price",
    "sl",
    "tp",
    "sl_pips",
    "tp_pips",
    "risk_pct",
    "retcode",
    "order",
    "deal",
    "message",
]


TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
}


@dataclass
class PendingSetup:
    setup_id: str
    dedupe_key: str
    signal_key: str
    side: str
    level: float
    candle_time: int
    expires_at: int
    status: str = PENDING_STATUS_PENDING
    context: dict[str, Any] = field(default_factory=dict)
    last_note: str = ""
    requires_revalidation: bool = False


@dataclass
class SymbolState:
    last_trade_ts: float = 0.0
    cooldown_until: float = 0.0
    entry_count: int = 0
    last_processed_bar_time: int = 0
    last_signal_key: Optional[str] = None
    pending_setup: Optional[PendingSetup] = None
    risk_close_retry_after: dict[int, float] = field(default_factory=dict)


@dataclass
class GlobalState:
    day_key: str = ""
    daily_realized_pnl: float = 0.0
    daily_loss_reached: bool = False
    daily_loss_announced: bool = False


def trading_day_key(now_utc: datetime) -> str:
    # Trading-day boundary is UTC midnight for deterministic daily continuity.
    return now_utc.strftime("%Y-%m-%d")


def parse_hhmm(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid time value: {value}")
    return hour * 60 + minute


def session_match(session_range: str, now_utc: datetime) -> bool:
    start_raw, end_raw = [part.strip() for part in session_range.split("-", 1)]
    start_min = parse_hhmm(start_raw)
    end_min = parse_hhmm(end_raw)
    current_min = now_utc.hour * 60 + now_utc.minute

    if start_min <= end_min:
        return start_min <= current_min < end_min
    return current_min >= start_min or current_min < end_min


def session_allowed(cfg: SymbolConfig, now_utc: datetime) -> bool:
    if not cfg.allowed_sessions_utc:
        return True
    return any(session_match(item, now_utc) for item in cfg.allowed_sessions_utc)


def bot_magics(app_config: AppConfig) -> set[int]:
    return {cfg.magic for cfg in app_config.symbols}


def log_event(log_file: Path, row: dict) -> None:
    file_exists = log_file.exists()
    with log_file.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in LOG_FIELDS})


def emit_event(
    log_file: Path,
    repo: SQLiteRepository,
    app_config: AppConfig,
    event_type: str,
    symbol: str,
    *,
    message: str = "",
    setup_id: Optional[str] = None,
    ticket: Optional[int] = None,
    payload: Optional[dict] = None,
    csv_row: Optional[dict] = None,
    created_at_utc: Optional[str] = None,
) -> None:
    timeframe_by_symbol = {cfg.symbol: cfg.timeframe for cfg in app_config.symbols}
    ts = created_at_utc or datetime.now(timezone.utc).isoformat()
    trading_day = trading_day_key(datetime.fromisoformat(ts))
    event_payload = dict(payload or {})
    event_payload.setdefault("message", message)

    persisted = repo.append_event(
        event_type=event_type,
        trading_day=trading_day,
        symbol=symbol,
        setup_id=setup_id,
        ticket=ticket,
        payload=event_payload,
        created_at_utc=ts,
    )

    row = dict(csv_row or {})
    row.setdefault("ts", persisted.created_at_utc)
    row.setdefault("symbol", symbol)
    row.setdefault("timeframe", timeframe_by_symbol.get(symbol, ""))
    row.setdefault("strategy", "SWEEP_V2")
    row["event"] = event_type
    if ticket is not None:
        row.setdefault("position", int(ticket))
    if setup_id is not None:
        row.setdefault("message", f"{message} setup_id={setup_id}".strip())
    else:
        row.setdefault("message", message)
    log_event(log_file, row)
    try:
        send_push_notification(
            app_config.runtime,
            event_type=event_type,
            symbol=symbol,
            ticket=ticket,
            setup_id=setup_id,
            created_at_utc=ts,
            payload=event_payload,
        )
    except Exception as exc:
        print(f"[{datetime.now(timezone.utc).isoformat()}] PUSH_NOTIFY_FAIL {event_type} {symbol} {exc}")


def recovery_event_logger(log_file: Path, app_config: AppConfig, repo: SQLiteRepository) -> Callable[[dict], None]:
    timeframe_by_symbol = {cfg.symbol: cfg.timeframe for cfg in app_config.symbols}

    def _logger(row: dict) -> None:
        payload = dict(row)
        # Recovery module may pass already-persisted event rows; avoid double insertion.
        if "payload_json" in payload and "created_at_utc" in payload:
            symbol = str(payload.get("symbol", ""))
            payload.setdefault("ts", payload.get("created_at_utc"))
            payload.setdefault("timeframe", timeframe_by_symbol.get(symbol, ""))
            payload.setdefault("strategy", "SWEEP_V2")
            log_event(log_file, payload)
            return

        event_type = str(payload.get("event_type") or payload.get("event") or "RECOVERY_EVENT")
        symbol = str(payload.get("symbol", ""))
        setup_id = str(payload["setup_id"]) if payload.get("setup_id") else None
        ticket = int(payload["ticket"]) if payload.get("ticket") is not None else None
        if ticket is None and payload.get("position") not in (None, ""):
            ticket = int(payload["position"])
        ts = str(payload.get("created_at_utc") or payload.get("ts") or datetime.now(timezone.utc).isoformat())
        payload.setdefault("timeframe", timeframe_by_symbol.get(symbol, ""))
        payload.setdefault("strategy", "SWEEP_V2")
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type=event_type,
            symbol=symbol,
            message=str(payload.get("message", "")),
            setup_id=setup_id,
            ticket=ticket,
            created_at_utc=ts,
            payload={
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "event",
                    "event_type",
                    "symbol",
                    "setup_id",
                    "ticket",
                    "position",
                    "message",
                    "created_at_utc",
                    "ts",
                    "timeframe",
                    "strategy",
                }
            },
            csv_row=payload,
        )

    return _logger


def pending_from_record(record: PendingSetupRecord, requires_revalidation: bool = False) -> PendingSetup:
    return PendingSetup(
        setup_id=record.setup_id,
        dedupe_key=record.dedupe_key,
        signal_key=record.signal_key,
        side=record.side,
        level=float(record.level),
        candle_time=int(record.candle_time),
        expires_at=int(record.expires_at),
        status=record.status,
        context=dict(record.context),
        last_note=record.last_note,
        requires_revalidation=requires_revalidation,
    )


def save_guard_state(repo: SQLiteRepository, global_state: GlobalState) -> None:
    repo.save_guard_state(
        GuardStateRecord(
            day_key=global_state.day_key,
            daily_realized_pnl=float(global_state.daily_realized_pnl),
            daily_loss_reached=bool(global_state.daily_loss_reached),
            daily_loss_announced=bool(global_state.daily_loss_announced),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def save_symbol_state(repo: SQLiteRepository, cfg: SymbolConfig, state: SymbolState) -> None:
    repo.save_symbol_runtime_state(
        SymbolRuntimeStateRecord(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            last_trade_ts=float(state.last_trade_ts),
            cooldown_until=float(state.cooldown_until),
            entry_count=int(state.entry_count),
            last_processed_bar_time=int(state.last_processed_bar_time),
            last_signal_key=state.last_signal_key,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def restore_runtime_state(
    repo: SQLiteRepository,
    app_config: AppConfig,
    states: dict[str, SymbolState],
    global_state: GlobalState,
    pending_by_symbol: dict[str, PendingSetupRecord],
) -> None:
    today_key = trading_day_key(datetime.now(timezone.utc))
    guard = repo.get_guard_state()
    if guard.day_key == today_key:
        global_state.day_key = guard.day_key
        global_state.daily_realized_pnl = float(guard.daily_realized_pnl)
        global_state.daily_loss_reached = bool(guard.daily_loss_reached)
        global_state.daily_loss_announced = bool(guard.daily_loss_announced)
    else:
        global_state.day_key = today_key
        global_state.daily_realized_pnl = 0.0
        global_state.daily_loss_reached = False
        global_state.daily_loss_announced = False

    for cfg in app_config.symbols:
        state = states[cfg.symbol]
        persisted = repo.get_symbol_runtime_state(cfg.symbol)
        if persisted is not None:
            state.last_trade_ts = float(persisted.last_trade_ts)
            state.cooldown_until = float(persisted.cooldown_until)
            state.entry_count = int(persisted.entry_count)
            state.last_processed_bar_time = int(persisted.last_processed_bar_time)
            state.last_signal_key = persisted.last_signal_key

        if state.cooldown_until <= 0 and state.last_trade_ts > 0:
            state.cooldown_until = state.last_trade_ts + max(0, cfg.cooldown_sec)

        state.risk_close_retry_after = {
            int(item.ticket): float(item.retry_after) for item in repo.list_risk_retries(cfg.symbol)
        }

        pending_record = pending_by_symbol.get(cfg.symbol)
        if pending_record is not None and pending_record.status not in PENDING_TERMINAL_STATUSES:
            state.pending_setup = pending_from_record(pending_record, requires_revalidation=True)


def cleanup_stale_retry_state(
    repo: SQLiteRepository,
    app_config: AppConfig,
    states: dict[str, SymbolState],
    log_file: Path,
) -> None:
    active_open_tickets = {int(pos.ticket) for pos in repo.list_open_positions(status=POSITION_STATUS_OPEN)}
    now_utc = datetime.now(timezone.utc).isoformat()

    for cfg in app_config.symbols:
        state = states[cfg.symbol]
        for ticket in list(state.risk_close_retry_after.keys()):
            if ticket in active_open_tickets:
                continue
            with repo.transaction():
                state.risk_close_retry_after.pop(ticket, None)
                repo.delete_risk_retry(ticket)
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="RECOVERY_STALE_RETRY_STATE_DROPPED",
                    symbol=cfg.symbol,
                    ticket=ticket,
                    message="removed stale retry state during startup recovery",
                    payload={"policy": "drop_retry_without_active_ticket"},
                    csv_row={
                        "ts": now_utc,
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "position": ticket,
                    },
                )


def checkpoint_state_snapshot(
    repo: SQLiteRepository,
    app_config: AppConfig,
    states: dict[str, SymbolState],
    global_state: GlobalState,
    log_file: Path,
) -> None:
    with repo.transaction():
        save_guard_state(repo, global_state)
        for cfg in app_config.symbols:
            save_symbol_state(repo, cfg, states[cfg.symbol])
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type="CHECKPOINT_SNAPSHOT",
            symbol="ALL",
            message="periodic runtime checkpoint persisted",
            payload={
                "symbols": len(app_config.symbols),
                "open_positions_cached": len(repo.list_open_positions(status=POSITION_STATUS_OPEN)),
            },
        )


def run_periodic_retention(
    repo: SQLiteRepository,
    app_config: AppConfig,
    log_file: Path,
    now_utc: datetime,
) -> None:
    retention_days = max(1, int(getattr(app_config.runtime, "event_retention_days", 30)))
    archive_dir = str(getattr(app_config.runtime, "event_archive_dir", "state_archives"))
    batch_size = int(getattr(app_config.runtime, "event_retention_batch_size", 5000))
    result = archive_and_prune_events(
        repo=repo,
        now_utc=now_utc,
        retention_days=retention_days,
        archive_dir=archive_dir,
        batch_size=batch_size,
        dry_run=False,
    )
    if result.archived_count <= 0:
        return
    emit_event(
        log_file=log_file,
        repo=repo,
        app_config=app_config,
        event_type="EVENT_RETENTION_APPLIED",
        symbol="ALL",
        message="archived and pruned old persisted events",
        payload={
            "cutoff_trading_day": result.cutoff_trading_day,
            "archived_count": result.archived_count,
            "deleted_count": result.deleted_count,
            "archive_file": result.archive_file,
        },
    )


def position_to_record(cfg: SymbolConfig, position: object, setup_id: Optional[str]) -> OpenPositionRecord:
    return OpenPositionRecord(
        ticket=int(position.ticket),
        symbol=cfg.symbol,
        magic=int(cfg.magic),
        setup_id=setup_id,
        side="BUY" if int(position.type) == 0 else "SELL",
        volume=float(getattr(position, "volume", 0.0) or 0.0),
        open_price=float(getattr(position, "price_open", 0.0) or 0.0),
        sl=float(getattr(position, "sl", 0.0) or 0.0),
        tp=float(getattr(position, "tp", 0.0) or 0.0),
        comment=str(getattr(position, "comment", "") or ""),
        opened_at=int(getattr(position, "time", 0) or 0),
        status=POSITION_STATUS_OPEN,
    )


def sync_open_positions_for_symbol(
    adapter: MT5Adapter,
    cfg: SymbolConfig,
    app_config: AppConfig,
    repo: SQLiteRepository,
    log_file: Path,
) -> None:
    now_utc = datetime.now(timezone.utc)
    broker_positions = adapter.positions_get(cfg.symbol, magic=cfg.magic)
    local_open = {int(pos.ticket): pos for pos in repo.list_open_positions(symbol=cfg.symbol, status=POSITION_STATUS_OPEN)}

    broker_tickets: set[int] = set()
    for position in broker_positions:
        ticket = int(position.ticket)
        broker_tickets.add(ticket)
        local = local_open.get(ticket)
        setup_id = local.setup_id if local is not None else None
        repo.upsert_open_position(position_to_record(cfg, position, setup_id))
        if local is None:
            emit_event(
                log_file=log_file,
                repo=repo,
                app_config=app_config,
                event_type="POSITION_SYNC_BROKER_ADDED",
                symbol=cfg.symbol,
                ticket=ticket,
                message="runtime sync inserted broker position",
                payload={"side": "BUY" if int(position.type) == 0 else "SELL"},
                csv_row={
                    "ts": now_utc.isoformat(),
                    "symbol": cfg.symbol,
                    "timeframe": cfg.timeframe,
                    "strategy": "SWEEP_V2",
                    "position": ticket,
                    "side": "BUY" if int(position.type) == 0 else "SELL",
                },
            )

    for ticket, local in local_open.items():
        if ticket in broker_tickets:
            continue
        close_deal = adapter.latest_close_deal_for_position(ticket, now_utc)
        close_payload = {"side": local.side}
        event_type = "POSITION_CLOSED_UNCONFIRMED"
        close_reason = "missing_on_broker_runtime_sync_unconfirmed"
        message = "broker no longer reports position; close deal not reconstructed"
        csv_row = {
            "ts": now_utc.isoformat(),
            "symbol": cfg.symbol,
            "timeframe": cfg.timeframe,
            "strategy": "SWEEP_V2",
            "position": ticket,
            "side": local.side,
        }
        if close_deal is not None:
            event_type = "POSITION_CLOSED_BROKER"
            close_reason = "broker_side_close_detected"
            profit = float(getattr(close_deal, "profit", 0.0) or 0.0)
            commission = float(getattr(close_deal, "commission", 0.0) or 0.0)
            swap = float(getattr(close_deal, "swap", 0.0) or 0.0)
            fee = float(getattr(close_deal, "fee", 0.0) or 0.0)
            realized_pnl = profit + commission + swap + fee
            close_price = float(getattr(close_deal, "price", 0.0) or 0.0)
            closed_at = int(getattr(close_deal, "time", 0) or 0)
            close_payload.update(
                {
                    "close_price": close_price,
                    "closed_at": closed_at,
                    "realized_pnl": round(realized_pnl, 2),
                    "close_reason": close_reason,
                }
            )
            message = f"broker close detected pnl={realized_pnl:.2f}"
            csv_row["price"] = close_price
        else:
            close_payload.update(
                {
                    "policy": "close_unconfirmed_missing_on_broker_runtime",
                    "close_reason": close_reason,
                }
            )
        repo.mark_open_position_closed(ticket, close_reason)
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type=event_type,
            symbol=cfg.symbol,
            setup_id=local.setup_id,
            ticket=ticket,
            message=message,
            payload=close_payload,
            csv_row=csv_row,
        )


def apply_daily_loss_guard(
    adapter: MT5Adapter,
    app_config: AppConfig,
    global_state: GlobalState,
    log_file: Path,
    repo: SQLiteRepository,
) -> bool:
    if app_config.runtime.dry_run:
        global_state.daily_realized_pnl = 0.0
        return False
    if app_config.runtime.daily_loss_limit_usd <= 0:
        global_state.daily_realized_pnl = 0.0
        return False

    now_utc = datetime.now(timezone.utc)
    day_key = trading_day_key(now_utc)

    if global_state.day_key != day_key:
        with repo.transaction():
            global_state.day_key = day_key
            global_state.daily_realized_pnl = 0.0
            global_state.daily_loss_reached = False
            global_state.daily_loss_announced = False
            save_guard_state(repo, global_state)
            emit_event(
                log_file=log_file,
                repo=repo,
                app_config=app_config,
                event_type="GUARD_DAY_ROLLOVER",
                symbol="ALL",
                message=f"rollover_to={day_key}",
                payload={"day_key": day_key},
            )

    if global_state.daily_loss_reached:
        return True

    realized = adapter.realized_pnl_today(bot_magics(app_config), now_utc)
    global_state.daily_realized_pnl = float(realized)
    save_guard_state(repo, global_state)

    trigger_level = -abs(app_config.runtime.daily_loss_limit_usd)
    if realized > trigger_level:
        return False

    global_state.daily_loss_reached = True
    save_guard_state(repo, global_state)
    if not global_state.daily_loss_announced:
        with repo.transaction():
            global_state.daily_loss_announced = True
            save_guard_state(repo, global_state)
            emit_event(
                log_file=log_file,
                repo=repo,
                app_config=app_config,
                event_type="DAILY_LOSS_HIT",
                symbol="ALL",
                message=f"realized=${realized:.2f} limit=${app_config.runtime.daily_loss_limit_usd:.2f}",
                payload={
                    "realized_pnl": float(realized),
                    "daily_loss_limit_usd": float(app_config.runtime.daily_loss_limit_usd),
                },
                csv_row={"ts": now_utc.isoformat(), "symbol": "ALL", "timeframe": "", "strategy": "SWEEP_V2"},
            )
        print(
            f"[{now_utc.isoformat()}] DAILY_LOSS_HIT realized=${realized:.2f} "
            f"limit=${app_config.runtime.daily_loss_limit_usd:.2f}"
        )

    if not app_config.runtime.close_positions_on_daily_loss:
        return True

    for cfg in app_config.symbols:
        for position in adapter.positions_get(cfg.symbol, magic=cfg.magic):
            result = adapter.close_position_market_with_fallback(
                symbol=cfg.symbol,
                position=position,
                magic=cfg.magic,
                reason="daily_loss",
                deviation=app_config.runtime.default_deviation,
            )
            ticket = int(position.ticket)
            with repo.transaction():
                if result.ok:
                    repo.mark_open_position_closed(ticket, "daily_loss_guard_close")
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="DAILY_LOSS_CLOSE_OK" if result.ok else "DAILY_LOSS_CLOSE_FAIL",
                    symbol=cfg.symbol,
                    ticket=ticket,
                    message="daily loss close" if result.ok else str(result.raw),
                    payload={
                        "side": "BUY" if int(position.type) == 0 else "SELL",
                        "volume": float(position.volume),
                        "price": result.price,
                        "retcode": result.retcode,
                        "order": result.order,
                        "deal": result.deal,
                    },
                    csv_row={
                        "ts": now_utc.isoformat(),
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "position": ticket,
                        "side": "BUY" if int(position.type) == 0 else "SELL",
                        "volume": float(position.volume),
                        "price": result.price,
                        "retcode": result.retcode,
                        "order": result.order,
                        "deal": result.deal,
                    },
                )

    return True


def manage_symbol_positions(
    adapter: MT5Adapter,
    cfg: SymbolConfig,
    app_config: AppConfig,
    state: SymbolState,
    log_file: Path,
    repo: SQLiteRepository,
) -> None:
    runtime = app_config.runtime
    if runtime.dry_run:
        return

    positions = adapter.positions_get(cfg.symbol, magic=cfg.magic)
    open_tickets = {int(pos.ticket) for pos in positions}
    for ticket in list(state.risk_close_retry_after.keys()):
        if ticket not in open_tickets:
            state.risk_close_retry_after.pop(ticket, None)
            with repo.transaction():
                repo.delete_risk_retry(ticket)
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="RETRY_STATE_DROPPED_INACTIVE_TICKET",
                    symbol=cfg.symbol,
                    ticket=ticket,
                    message="retry state removed because ticket is no longer active",
                    payload={"policy": "drop_stale_retry_runtime"},
                    csv_row={
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "position": ticket,
                    },
                )

    now_utc = datetime.now(timezone.utc)
    now_ts = time.time()
    info = SymbolTradeInfo.from_mt5(adapter.symbol_info(cfg.symbol))
    point = float(info.point)
    stops_level_price = float((getattr(adapter.symbol_info(cfg.symbol), "trade_stops_level", 0) or 0) * point)

    for position in positions:
        ticket = int(position.ticket)
        side = "BUY" if int(position.type) == 0 else "SELL"
        tick = adapter.symbol_tick(cfg.symbol)
        current_price = current_exit_price(position, tick)
        current_sl = float(getattr(position, "sl", 0.0) or 0.0)
        current_tp = float(getattr(position, "tp", 0.0) or 0.0)

        if runtime.trailing_stop_mode == "r_multiple":
            desired_sl = compute_r_multiple_trailing_stop(
                side=side,
                open_price=float(getattr(position, "price_open", 0.0) or 0.0),
                current_exit_price_value=current_price,
                current_sl=current_sl,
                risk_distance_price=position_risk_distance_price(cfg, info),
                activation_r=float(runtime.trailing_activation_r),
                gap_r=float(runtime.trailing_gap_r),
            )
            if desired_sl is not None:
                if side == "BUY":
                    desired_sl = min(desired_sl, current_price - stops_level_price)
                    valid_trail = desired_sl > max(current_sl, 0.0) + point and desired_sl < current_price
                else:
                    desired_sl = max(desired_sl, current_price + stops_level_price)
                    valid_trail = (current_sl <= 0 or desired_sl < current_sl - point) and desired_sl > current_price

                if valid_trail:
                    target_tp = 0.0 if runtime.trailing_remove_tp_on_activation else current_tp
                    modify = adapter.modify_position_protection(
                        cfg.symbol,
                        position,
                        sl=desired_sl,
                        tp=target_tp,
                    )
                    with repo.transaction():
                        emit_event(
                            log_file=log_file,
                            repo=repo,
                            app_config=app_config,
                            event_type="TRAILING_STOP_OK" if modify.ok else "TRAILING_STOP_FAIL",
                            symbol=cfg.symbol,
                            ticket=ticket,
                            message=(
                                f"trail sl->{desired_sl:.5f} tp->{target_tp:.5f} "
                                f"mode=r_multiple"
                            ),
                            payload={
                                "side": side,
                                "from_sl": current_sl,
                                "to_sl": desired_sl,
                                "from_tp": current_tp,
                                "to_tp": target_tp,
                                "current_price": current_price,
                                "activation_r": float(runtime.trailing_activation_r),
                                "gap_r": float(runtime.trailing_gap_r),
                                "retcode": modify.retcode,
                            },
                            csv_row={
                                "ts": now_utc.isoformat(),
                                "symbol": cfg.symbol,
                                "timeframe": cfg.timeframe,
                                "strategy": "SWEEP_V2",
                                "event": "TRAILING_STOP_OK" if modify.ok else "TRAILING_STOP_FAIL",
                                "position": ticket,
                                "side": side,
                                "price": current_price,
                                "sl": desired_sl,
                                "tp": target_tp,
                                "retcode": modify.retcode,
                            },
                        )

        pnl_money = float(getattr(position, "profit", 0.0) or 0.0)
        reason: Optional[str] = None
        loss_limit_money: Optional[float] = None
        loss_guard_mode: Optional[str] = None

        loss_limit_money, loss_reason, loss_guard_mode = resolve_loss_guard(runtime, position, info)
        if loss_limit_money is not None and pnl_money <= -loss_limit_money:
            reason = loss_reason
        if runtime.max_profit_per_trade_usd > 0 and pnl_money >= runtime.max_profit_per_trade_usd:
            reason = f"max_profit ${runtime.max_profit_per_trade_usd:.2f}"

        if reason is None:
            continue

        retry_after = float(state.risk_close_retry_after.get(ticket, 0.0))
        if now_ts < retry_after:
            continue

        result = adapter.close_position_market_with_fallback(
            symbol=cfg.symbol,
            position=position,
            magic=cfg.magic,
            reason=reason,
            deviation=runtime.default_deviation,
        )

        with repo.transaction():
            if result.ok:
                state.risk_close_retry_after.pop(ticket, None)
                repo.delete_risk_retry(ticket)
                repo.mark_open_position_closed(ticket, "risk_guard_close")
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="RISK_CLOSE_OK",
                    symbol=cfg.symbol,
                    ticket=ticket,
                    message=f"{reason} pnl=${pnl_money:.2f}",
                    payload={
                        "side": side,
                        "volume": float(position.volume),
                        "price": result.price,
                        "loss_limit_money": loss_limit_money,
                        "loss_guard_mode": loss_guard_mode,
                        "retcode": result.retcode,
                        "order": result.order,
                        "deal": result.deal,
                    },
                    csv_row={
                        "ts": now_utc.isoformat(),
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "position": ticket,
                        "side": side,
                        "volume": float(position.volume),
                        "price": result.price,
                        "retcode": result.retcode,
                        "order": result.order,
                        "deal": result.deal,
                    },
                )
            else:
                retry_ts = now_ts + max(1, int(runtime.risk_close_retry_sec))
                state.risk_close_retry_after[ticket] = retry_ts
                repo.set_risk_retry(
                    ticket=ticket,
                    symbol=cfg.symbol,
                    retry_after=retry_ts,
                    reason=reason,
                    last_error=str(result.raw),
                )
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="RISK_CLOSE_FAIL",
                    symbol=cfg.symbol,
                    ticket=ticket,
                    message=f"{reason} pnl=${pnl_money:.2f} {result.raw}",
                    payload={
                        "side": side,
                        "volume": float(position.volume),
                        "price": result.price,
                        "loss_limit_money": loss_limit_money,
                        "loss_guard_mode": loss_guard_mode,
                        "retcode": result.retcode,
                        "order": result.order,
                        "deal": result.deal,
                        "retry_after": retry_ts,
                    },
                    csv_row={
                        "ts": now_utc.isoformat(),
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "position": ticket,
                        "side": side,
                        "volume": float(position.volume),
                        "price": result.price,
                        "retcode": result.retcode,
                        "order": result.order,
                        "deal": result.deal,
                    },
                )


def total_open_risk_money(adapter: MT5Adapter, app_config: AppConfig) -> float:
    total = 0.0
    for cfg in app_config.symbols:
        info = SymbolTradeInfo.from_mt5(adapter.symbol_info(cfg.symbol))
        for position in adapter.positions_get(cfg.symbol, magic=cfg.magic):
            stop_price = float(getattr(position, "sl", 0.0) or 0.0)
            risk_money = calc_position_risk_money(
                entry_price=float(getattr(position, "price_open", 0.0) or 0.0),
                stop_price=stop_price,
                volume=float(getattr(position, "volume", 0.0) or 0.0),
                symbol_info=info,
            )
            if math.isinf(risk_money):
                return float("inf")
            total += float(risk_money)
    return float(total)


def total_open_positions_count(adapter: MT5Adapter, app_config: AppConfig) -> int:
    total = 0
    for cfg in app_config.symbols:
        total += len(adapter.positions_get(cfg.symbol, magic=cfg.magic))
    return total


def resolve_loss_guard(
    runtime: Any,
    position: object,
    symbol_info: SymbolTradeInfo,
) -> tuple[Optional[float], Optional[str], Optional[str]]:
    mode = str(getattr(runtime, "per_trade_loss_guard_mode", "fixed_usd") or "fixed_usd").lower()

    if mode == "position_risk":
        risk_multiple = max(0.0, float(getattr(runtime, "per_trade_loss_risk_multiple", 1.0) or 0.0))
        risk_money = calc_position_risk_money(
            entry_price=float(getattr(position, "price_open", 0.0) or 0.0),
            stop_price=float(getattr(position, "sl", 0.0) or 0.0),
            volume=float(getattr(position, "volume", 0.0) or 0.0),
            symbol_info=symbol_info,
        )
        if math.isfinite(risk_money) and risk_money > 0 and risk_multiple > 0:
            threshold = float(risk_money * risk_multiple)
            return threshold, f"max_loss risk x{risk_multiple:.2f} (${threshold:.2f})", mode

    fixed_limit = float(getattr(runtime, "max_loss_per_trade_usd", 0.0) or 0.0)
    if fixed_limit > 0:
        return fixed_limit, f"max_loss ${fixed_limit:.2f}", "fixed_usd"

    return None, None, None


def position_risk_distance_price(cfg: SymbolConfig, symbol_info: SymbolTradeInfo) -> float:
    return float(cfg.sl_pips * MT5Adapter.pip_size(symbol_info))


def current_exit_price(position: object, tick: object) -> float:
    if int(position.type) == 0:
        return float(getattr(tick, "bid", 0.0) or 0.0)
    return float(getattr(tick, "ask", 0.0) or 0.0)


def compute_r_multiple_trailing_stop(
    *,
    side: str,
    open_price: float,
    current_exit_price_value: float,
    current_sl: float,
    risk_distance_price: float,
    activation_r: float,
    gap_r: float,
) -> Optional[float]:
    if risk_distance_price <= 0 or activation_r <= 0 or gap_r < 0:
        return None

    normalized_side = side.upper()
    if normalized_side == "BUY":
        favorable_move = current_exit_price_value - open_price
    else:
        favorable_move = open_price - current_exit_price_value

    current_r = favorable_move / risk_distance_price
    if current_r + 1e-9 < activation_r:
        return None

    locked_r = current_r - gap_r
    if locked_r <= 0:
        desired_sl = open_price
    elif normalized_side == "BUY":
        desired_sl = open_price + (locked_r * risk_distance_price)
    else:
        desired_sl = open_price - (locked_r * risk_distance_price)

    if normalized_side == "BUY":
        if current_sl > 0 and desired_sl <= current_sl:
            return None
    else:
        if current_sl > 0 and desired_sl >= current_sl:
            return None

    return float(desired_sl)


def portfolio_caps_message(adapter: MT5Adapter, app_config: AppConfig, cfg: SymbolConfig, equity: float) -> Optional[str]:
    runtime = app_config.runtime

    if runtime.max_open_positions_total > 0:
        open_positions = total_open_positions_count(adapter, app_config)
        if open_positions >= runtime.max_open_positions_total:
            return f"open_positions={open_positions} cap={runtime.max_open_positions_total}"

    if runtime.max_total_open_risk_pct > 0:
        open_risk_money = total_open_risk_money(adapter, app_config)
        if math.isinf(open_risk_money):
            return "open position without stop-loss"
        if equity <= 0:
            return "invalid equity for portfolio cap"

        open_risk_pct = (open_risk_money / equity) * 100.0
        projected_risk_pct = open_risk_pct + cfg.risk_pct
        if projected_risk_pct > runtime.max_total_open_risk_pct:
            return (
                f"projected_risk_pct={projected_risk_pct:.2f} "
                f"cap={runtime.max_total_open_risk_pct:.2f}"
            )

    return None


def is_pending_expired(pending: PendingSetup, reference_bar_time: Optional[int] = None) -> bool:
    if reference_bar_time is not None:
        return int(reference_bar_time) >= int(pending.expires_at)
    return time.time() > float(pending.expires_at)


def cancel_stale_pending_setup(
    *,
    repo: SQLiteRepository,
    app_config: AppConfig,
    log_file: Path,
    cfg: SymbolConfig,
    pending: PendingSetup,
    reference_bar_time: int,
    reason: str,
) -> None:
    now_utc = datetime.now(timezone.utc)
    with repo.transaction():
        repo.transition_pending_setup(
            pending.setup_id,
            PENDING_STATUS_EXPIRED,
            last_note=reason,
            closed_reason=reason,
        )
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type="STALE_PENDING_CANCELED",
            symbol=cfg.symbol,
            setup_id=pending.setup_id,
            message=reason,
            payload={
                "side": pending.side,
                "level": pending.level,
                "candle_time": pending.candle_time,
                "expires_at": pending.expires_at,
                "reference_bar_time": int(reference_bar_time),
            },
            csv_row={
                "ts": now_utc.isoformat(),
                "symbol": cfg.symbol,
                "timeframe": cfg.timeframe,
                "strategy": "SWEEP_V2",
                "side": pending.side,
                "level": f"{pending.level:.5f}",
                "candle_time": pending.candle_time,
            },
        )


def cancel_entry_setup(
    *,
    repo: SQLiteRepository,
    app_config: AppConfig,
    log_file: Path,
    cfg: SymbolConfig,
    setup: PendingSetup,
    event_type: str,
    message: str,
    csv_row: dict,
) -> None:
    reason = f"entry_blocked:{event_type}"
    with repo.transaction():
        repo.transition_pending_setup(
            setup.setup_id,
            PENDING_STATUS_CANCELED,
            last_note=reason,
            closed_reason=reason,
        )
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type=event_type,
            symbol=cfg.symbol,
            setup_id=setup.setup_id,
            message=message,
            payload={
                "side": setup.side,
                "level": setup.level,
                "candle_time": setup.candle_time,
                "skip_event": event_type,
            },
            csv_row=csv_row,
        )


def has_active_pending_setup(state: SymbolState, mode: str) -> bool:
    if mode == "none":
        return False
    if state.pending_setup is None:
        return False
    return state.pending_setup.status not in PENDING_TERMINAL_STATUSES


def evaluate_pending_confirmation(
    adapter: MT5Adapter,
    cfg: SymbolConfig,
    pending: PendingSetup,
    rates,
) -> ConfirmationResult:
    mode = cfg.confirmation_mode.lower()
    if mode in ("c3", "c4"):
        return evaluate_c3_c4_confirmation(rates, pending.side, pending.candle_time, mode)

    if mode == "cisd":
        cisd_rates = adapter.copy_rates(cfg.symbol, cfg.cisd_timeframe, cfg.cisd_lookback_bars)
        return evaluate_cisd_confirmation(cisd_rates, pending.side, pending.candle_time, cfg.cisd_structure_bars)

    if mode == "sweep_displacement_mss":
        confirm_rates = adapter.copy_rates(cfg.symbol, cfg.cisd_timeframe, cfg.cisd_lookback_bars)
        return evaluate_sweep_displacement_mss_confirmation(
            confirm_rates,
            pending.side,
            pending.candle_time,
            cfg.cisd_structure_bars,
            displacement_body_ratio_min=cfg.confirmation_displacement_body_ratio_min,
            displacement_range_multiple=cfg.confirmation_displacement_range_multiple,
        )

    return ConfirmationResult(False, False, f"unknown_confirmation_mode={mode}")


def _build_setup_context(
    cfg: SymbolConfig,
    mode: str,
    levels: list[float],
    signal_side: str,
    signal_level: float,
    signal_candle_time: int,
    *,
    signal_key: str,
    sweep_note: str = "",
    range_note: str = "",
) -> dict[str, Any]:
    return {
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe,
        "confirmation_mode": mode,
        "confirm_expiry_bars": int(cfg.confirm_expiry_bars),
        "signal_key": signal_key,
        "signal": {
            "side": signal_side,
            "level": float(signal_level),
            "candle_time": int(signal_candle_time),
        },
        "filters": {
            "sweep_note": sweep_note,
            "range_note": range_note,
        },
        "levels": [float(item) for item in levels],
        "risk": {
            "sl_pips": float(cfg.sl_pips),
            "tp_pips": float(cfg.tp_pips),
            "risk_pct": float(cfg.risk_pct),
        },
    }


def semantic_setup_key(candle_time: int, side: str, level: float) -> str:
    return f"{side}|{float(level):.5f}"


def legacy_semantic_setup_key(candle_time: int, side: str, level: float) -> str:
    return f"{int(candle_time)}|{side}|{float(level):.5f}"


def signal_key_variants(candle_time: int, side: str, level: float) -> set[str]:
    return {
        semantic_setup_key(candle_time, side, level),
        legacy_semantic_setup_key(candle_time, side, level),
    }


def matches_signal_key(existing_key: Optional[str], candle_time: int, side: str, level: float) -> bool:
    if not existing_key:
        return False
    return existing_key in signal_key_variants(candle_time, side, level)


def _revalidate_restored_pending(
    pending: PendingSetup,
    mode: str,
    rates,
    signal,
) -> tuple[bool, str]:
    has_signal_bar = any(int(row["time"]) == int(pending.candle_time) for row in rates)
    if not has_signal_bar:
        return False, "signal_bar_missing"

    if mode == "none":
        if signal is None:
            return False, "no_current_signal"
        current_key = semantic_setup_key(signal.candle_time, signal.side, signal.level)
        if not matches_signal_key(pending.signal_key, signal.candle_time, signal.side, signal.level):
            return False, f"semantic_key_mismatch expected={pending.signal_key} got={current_key}"

    return True, "revalidated"


def _resolve_recent_position(
    adapter: MT5Adapter,
    cfg: SymbolConfig,
    expected_side: str,
    expected_comment: str,
) -> Optional[object]:
    positions = adapter.positions_get(cfg.symbol, magic=cfg.magic)
    side_value = 0 if expected_side == "BUY" else 1

    exact = [
        item
        for item in positions
        if int(getattr(item, "type", -1)) == side_value and str(getattr(item, "comment", "") or "") == expected_comment
    ]
    candidates = exact or [item for item in positions if int(getattr(item, "type", -1)) == side_value]
    if not candidates:
        return None

    candidates.sort(key=lambda item: int(getattr(item, "time", 0) or 0), reverse=True)
    return candidates[0]


def process_symbol(
    adapter: MT5Adapter,
    cfg: SymbolConfig,
    app_config: AppConfig,
    state: SymbolState,
    log_file: Path,
    repo: SQLiteRepository,
) -> None:
    mode = cfg.confirmation_mode.lower()
    if mode not in ("none", "c3", "c4", "cisd", "sweep_displacement_mss"):
        raise ValueError(f"Unsupported confirmation_mode={cfg.confirmation_mode}")

    info = adapter.symbol_info(cfg.symbol)
    pip = adapter.pip_size(info)
    rates = adapter.copy_rates(cfg.symbol, cfg.timeframe, cfg.bars)
    if len(rates) < 3:
        return

    closed_bar_time = int(rates[-2]["time"])
    if closed_bar_time <= int(state.last_processed_bar_time):
        return
    state.last_processed_bar_time = closed_bar_time

    if state.pending_setup is not None and is_pending_expired(state.pending_setup, closed_bar_time):
        cancel_stale_pending_setup(
            repo=repo,
            app_config=app_config,
            log_file=log_file,
            cfg=cfg,
            pending=state.pending_setup,
            reference_bar_time=closed_bar_time,
            reason="expired_before_confirmation",
        )
        state.pending_setup = None

    levels = extract_pivot_levels(rates, cfg.pivot_len, cfg.max_levels)
    signal = detect_sweep_signal(rates, levels, cfg.buffer_pips * pip)

    entry_setup: Optional[PendingSetup] = None
    entry_side: Optional[str] = None
    entry_level: float = 0.0
    entry_candle_time: int = 0
    confirm_note: str = ""

    if signal is not None and not has_active_pending_setup(state, mode):
        signal_key = semantic_setup_key(signal.candle_time, signal.side, signal.level)
        prior_closed = rates[:-2]
        chop_result = evaluate_range_filter(
            prior_closed,
            lookback_bars=cfg.range_filter_lookback_bars,
            max_compression_ratio=cfg.range_filter_max_compression_ratio,
            min_overlap_ratio=cfg.range_filter_min_overlap_ratio,
        )
        if chop_result.blocked:
            now_utc = datetime.now(timezone.utc)
            log_event(
                log_file,
                {
                    "ts": now_utc.isoformat(),
                    "symbol": cfg.symbol,
                    "timeframe": cfg.timeframe,
                    "strategy": "SWEEP_V2",
                    "event": "SKIP_RANGE_CHOP",
                    "side": signal.side,
                    "level": f"{signal.level:.5f}",
                    "candle_time": int(signal.candle_time),
                    "message": (
                        f"{chop_result.note} compression={chop_result.compression_ratio:.2f} "
                        f"overlap={chop_result.overlap_ratio:.2f}"
                    ),
                },
            )
            return

        sweep_quality = evaluate_sweep_significance(
            rates,
            signal,
            lookback_bars=cfg.sweep_significance_lookback_bars,
            min_range_multiple=cfg.sweep_significance_range_multiple,
            min_penetration_price=cfg.sweep_min_penetration_pips * pip,
        )
        if not sweep_quality.valid:
            now_utc = datetime.now(timezone.utc)
            log_event(
                log_file,
                {
                    "ts": now_utc.isoformat(),
                    "symbol": cfg.symbol,
                    "timeframe": cfg.timeframe,
                    "strategy": "SWEEP_V2",
                    "event": "SKIP_SWEEP_WEAK",
                    "side": signal.side,
                    "level": f"{signal.level:.5f}",
                    "candle_time": int(signal.candle_time),
                    "message": (
                        f"{sweep_quality.note} sweep_range={sweep_quality.sweep_range:.5f} "
                        f"avg_range={sweep_quality.avg_range:.5f} penetration={sweep_quality.penetration_price:.5f}"
                    ),
                },
            )
            return

        if not matches_signal_key(state.last_signal_key, signal.candle_time, signal.side, signal.level):
            state.last_signal_key = signal_key
            tf_seconds = TIMEFRAME_SECONDS.get(cfg.timeframe, 300)
            expires_at = compute_setup_expiry(signal.candle_time, tf_seconds, cfg.confirm_expiry_bars)
            initial_status = PENDING_STATUS_CONFIRMED if mode == "none" else PENDING_STATUS_PENDING

            setup_record = build_pending_setup_record(
                symbol=cfg.symbol,
                timeframe=cfg.timeframe,
                side=signal.side,
                level=float(signal.level),
                candle_time=int(signal.candle_time),
                signal_key=signal_key,
                expires_at=expires_at,
                context=_build_setup_context(
                    cfg=cfg,
                    mode=mode,
                    levels=levels,
                    signal_side=signal.side,
                    signal_level=float(signal.level),
                    signal_candle_time=int(signal.candle_time),
                    signal_key=signal_key,
                    sweep_note=sweep_quality.note,
                    range_note=chop_result.note,
                ),
                initial_status=initial_status,
            )
            stored_setup, created = repo.create_or_get_pending_setup(setup_record)

            if stored_setup.status not in PENDING_TERMINAL_STATUSES:
                state.pending_setup = pending_from_record(stored_setup)
                if created:
                    now_utc = datetime.now(timezone.utc)
                    log_event(
                        log_file,
                        {
                            "ts": now_utc.isoformat(),
                            "symbol": cfg.symbol,
                            "timeframe": cfg.timeframe,
                            "strategy": "SWEEP_V2",
                            "event": "SETUP_PENDING" if mode != "none" else "SETUP_CONFIRMED",
                            "side": signal.side,
                            "level": f"{signal.level:.5f}",
                            "candle_time": int(signal.candle_time),
                            "message": f"setup_id={stored_setup.setup_id} confirmation_mode={mode}",
                        },
                    )
        else:
            now_utc = datetime.now(timezone.utc)
            log_event(
                log_file,
                {
                    "ts": now_utc.isoformat(),
                    "symbol": cfg.symbol,
                    "timeframe": cfg.timeframe,
                    "strategy": "SWEEP_V2",
                    "event": "SKIP_DUPLICATE_SETUP",
                    "side": signal.side,
                    "level": f"{signal.level:.5f}",
                    "candle_time": int(signal.candle_time),
                    "message": f"signal_key={signal_key}",
                },
            )
    elif signal is not None and has_active_pending_setup(state, mode):
        now_utc = datetime.now(timezone.utc)
        log_event(
            log_file,
            {
                "ts": now_utc.isoformat(),
                "symbol": cfg.symbol,
                "timeframe": cfg.timeframe,
                "strategy": "SWEEP_V2",
                "event": "SKIP_NEW_SETUP_PENDING_EXISTS",
                "side": signal.side,
                "level": f"{signal.level:.5f}",
                "candle_time": int(signal.candle_time),
                "message": (
                    f"active_setup_id={state.pending_setup.setup_id if state.pending_setup is not None else ''} "
                    f"mode={mode}"
                ).strip(),
            },
        )

    if state.pending_setup is not None and state.pending_setup.requires_revalidation:
        pending = state.pending_setup
        now_utc = datetime.now(timezone.utc)
        revalidation_note = ""
        ok, note = _revalidate_restored_pending(pending, mode, rates, signal)
        if not ok:
            revalidation_note = note
        elif is_pending_expired(pending, closed_bar_time):
            ok = False
            revalidation_note = "expired_on_restart_revalidation"
        elif cfg.one_position_per_symbol and adapter.positions_get(cfg.symbol, magic=cfg.magic):
            ok = False
            revalidation_note = "conflicts_with_open_broker_position"
        elif cfg.use_bias_filter:
            needed = max(cfg.bias_lookback_bars, cfg.bias_ema_period + 3)
            bias_rates = adapter.copy_rates(cfg.symbol, cfg.bias_timeframe, needed)
            closed_bias_rates = bias_rates[:-1]
            bias_info = evaluate_bias(closed_bias_rates, cfg.bias_ema_period)
            bias_ok = bias_info["ok_buy"] if pending.side == "BUY" else bias_info["ok_sell"]
            if not bias_ok:
                ok = False
                revalidation_note = f"bias_invalid:{bias_info['note']}"
        if ok and mode != "none":
            pending_check = evaluate_pending_confirmation(adapter, cfg, pending, rates)
            if not pending_check.confirmed and not pending_check.pending:
                ok = False
                revalidation_note = f"regime_invalid:{pending_check.note}"

        if not ok:
            with repo.transaction():
                repo.transition_pending_setup(
                    pending.setup_id,
                    PENDING_STATUS_REJECTED,
                    last_note=f"restart_revalidation_failed:{revalidation_note}",
                    closed_reason=f"restart_revalidation_failed:{revalidation_note}",
                )
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="SKIP_RESTORED_SETUP_REVALIDATION",
                    symbol=cfg.symbol,
                    setup_id=pending.setup_id,
                    message=revalidation_note,
                    payload={
                        "side": pending.side,
                        "level": pending.level,
                        "candle_time": pending.candle_time,
                    },
                    csv_row={
                        "ts": now_utc.isoformat(),
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "side": pending.side,
                        "level": f"{pending.level:.5f}",
                        "candle_time": pending.candle_time,
                    },
                )
            state.pending_setup = None
            return

        with repo.transaction():
            repo.touch_pending_note(pending.setup_id, f"restart_revalidated:{note}")
            pending.requires_revalidation = False
            state.pending_setup = pending
            emit_event(
                log_file=log_file,
                repo=repo,
                app_config=app_config,
                event_type="SETUP_REVALIDATED",
                symbol=cfg.symbol,
                setup_id=pending.setup_id,
                message=note,
                payload={"side": pending.side, "level": pending.level, "candle_time": pending.candle_time},
                csv_row={
                    "ts": now_utc.isoformat(),
                    "symbol": cfg.symbol,
                    "timeframe": cfg.timeframe,
                    "strategy": "SWEEP_V2",
                    "side": pending.side,
                    "level": f"{pending.level:.5f}",
                    "candle_time": pending.candle_time,
                },
            )

    if mode == "none":
        if state.pending_setup is None:
            return
        pending = state.pending_setup
        if pending.status in PENDING_TERMINAL_STATUSES:
            state.pending_setup = None
            return
        entry_setup = pending
        entry_side = pending.side
        entry_level = float(pending.level)
        entry_candle_time = int(pending.candle_time)
        confirm_note = "confirm=none"
        state.pending_setup = None

    if mode != "none":
        if state.pending_setup is None:
            return

        pending = state.pending_setup
        now_utc = datetime.now(timezone.utc)

        if is_pending_expired(pending, closed_bar_time):
            cancel_stale_pending_setup(
                repo=repo,
                app_config=app_config,
                log_file=log_file,
                cfg=cfg,
                pending=pending,
                reference_bar_time=closed_bar_time,
                reason="expired_before_confirmation",
            )
            state.pending_setup = None
            return

        confirm_result = evaluate_pending_confirmation(adapter, cfg, pending, rates)
        if confirm_result.confirmed:
            with repo.transaction():
                repo.transition_pending_setup(
                    pending.setup_id,
                    PENDING_STATUS_CONFIRMED,
                    last_note=str(confirm_result.note),
                )
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="SETUP_CONFIRMED",
                    symbol=cfg.symbol,
                    setup_id=pending.setup_id,
                    message=str(confirm_result.note),
                    payload={"side": pending.side, "level": pending.level, "candle_time": pending.candle_time},
                    csv_row={
                        "ts": now_utc.isoformat(),
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "side": pending.side,
                        "level": f"{pending.level:.5f}",
                        "candle_time": pending.candle_time,
                    },
                )
            entry_setup = pending
            entry_side = pending.side
            entry_level = float(pending.level)
            entry_candle_time = int(pending.candle_time)
            confirm_note = str(confirm_result.note)
            state.pending_setup = None
        elif confirm_result.pending:
            if pending.last_note != confirm_result.note:
                repo.touch_pending_note(pending.setup_id, str(confirm_result.note))
                pending.last_note = confirm_result.note
                log_event(
                    log_file,
                    {
                        "ts": now_utc.isoformat(),
                        "symbol": cfg.symbol,
                        "timeframe": cfg.timeframe,
                        "strategy": "SWEEP_V2",
                        "event": "SETUP_WAIT",
                        "side": pending.side,
                        "level": f"{pending.level:.5f}",
                        "candle_time": pending.candle_time,
                        "message": f"mode={mode} {confirm_result.note} setup_id={pending.setup_id}",
                    },
                )
            state.pending_setup = pending
            return
        else:
            reject_note = str(confirm_result.note)
            repo.transition_pending_setup(
                pending.setup_id,
                PENDING_STATUS_REJECTED,
                last_note=reject_note,
                closed_reason=reject_note,
            )
            log_event(
                log_file,
                {
                    "ts": now_utc.isoformat(),
                    "symbol": cfg.symbol,
                    "timeframe": cfg.timeframe,
                    "strategy": "SWEEP_V2",
                    "event": "SKIP_CONFIRM_REJECTED",
                    "side": pending.side,
                    "level": f"{pending.level:.5f}",
                    "candle_time": pending.candle_time,
                    "message": f"mode={mode} {confirm_result.note} setup_id={pending.setup_id}",
                },
            )
            state.pending_setup = None
            return

    if entry_side is None:
        return

    now_utc = datetime.now(timezone.utc)
    now_ts = time.time()

    spread = adapter.spread_pips(cfg.symbol, info)
    base_row = {
        "ts": now_utc.isoformat(),
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe,
        "strategy": "SWEEP_V2",
        "side": entry_side,
        "level": f"{entry_level:.5f}",
        "candle_time": entry_candle_time,
        "spread_pips": round(spread, 5),
        "sl_pips": cfg.sl_pips,
        "tp_pips": cfg.tp_pips,
        "risk_pct": cfg.risk_pct,
    }

    if not session_allowed(cfg, now_utc):
        message = ",".join(cfg.allowed_sessions_utc)
        if entry_setup is not None:
            cancel_entry_setup(
                repo=repo,
                app_config=app_config,
                log_file=log_file,
                cfg=cfg,
                setup=entry_setup,
                event_type="SKIP_SESSION",
                message=message,
                csv_row=base_row,
            )
        else:
            log_event(log_file, {**base_row, "event": "SKIP_SESSION", "message": message})
        return

    if now_ts < float(state.cooldown_until):
        remaining = float(state.cooldown_until) - now_ts
        message = f"remaining={remaining:.0f}s"
        if entry_setup is not None:
            cancel_entry_setup(
                repo=repo,
                app_config=app_config,
                log_file=log_file,
                cfg=cfg,
                setup=entry_setup,
                event_type="SKIP_COOLDOWN",
                message=message,
                csv_row=base_row,
            )
        else:
            log_event(log_file, {**base_row, "event": "SKIP_COOLDOWN", "message": message})
        return

    if spread > cfg.max_spread_pips:
        message = f"spread={spread:.2f}>{cfg.max_spread_pips:.2f}"
        if entry_setup is not None:
            cancel_entry_setup(
                repo=repo,
                app_config=app_config,
                log_file=log_file,
                cfg=cfg,
                setup=entry_setup,
                event_type="SKIP_SPREAD",
                message=message,
                csv_row=base_row,
            )
        else:
            log_event(log_file, {**base_row, "event": "SKIP_SPREAD", "message": message})
        return

    if cfg.one_position_per_symbol and adapter.positions_get(cfg.symbol, magic=cfg.magic):
        message = "position already open"
        if entry_setup is not None:
            cancel_entry_setup(
                repo=repo,
                app_config=app_config,
                log_file=log_file,
                cfg=cfg,
                setup=entry_setup,
                event_type="SKIP_POSITION_EXISTS",
                message=message,
                csv_row=base_row,
            )
        else:
            log_event(log_file, {**base_row, "event": "SKIP_POSITION_EXISTS", "message": message})
        return

    bias_note = ""
    if cfg.use_bias_filter:
        needed = max(cfg.bias_lookback_bars, cfg.bias_ema_period + 3)
        bias_rates = adapter.copy_rates(cfg.symbol, cfg.bias_timeframe, needed)
        closed_bias_rates = bias_rates[:-1]
        bias_info = evaluate_bias(closed_bias_rates, cfg.bias_ema_period)
        bias_ok = bias_info["ok_buy"] if entry_side == "BUY" else bias_info["ok_sell"]
        bias_note = str(bias_info["note"])
        if not bias_ok:
            if entry_setup is not None:
                cancel_entry_setup(
                    repo=repo,
                    app_config=app_config,
                    log_file=log_file,
                    cfg=cfg,
                    setup=entry_setup,
                    event_type="SKIP_BIAS",
                    message=bias_note,
                    csv_row=base_row,
                )
            else:
                log_event(log_file, {**base_row, "event": "SKIP_BIAS", "message": bias_note})
            return

    price, sl, tp = adapter.quote_market_order(cfg.symbol, entry_side, cfg.sl_pips, cfg.tp_pips)

    ob_note = ""
    if cfg.use_order_block_filter:
        signal_index = len(rates) - 2
        order_block = find_local_order_block(
            rates=rates,
            signal_index=signal_index,
            side=entry_side,
            pip=pip,
            lookback_bars=cfg.order_block_lookback_bars,
            max_age_bars=cfg.order_block_max_age_bars,
            zone_mode=cfg.order_block_zone_mode,
            min_impulse_pips=cfg.order_block_min_impulse_pips,
        )

        if order_block is None:
            message = "no local order block"
            if entry_setup is not None:
                cancel_entry_setup(
                    repo=repo,
                    app_config=app_config,
                    log_file=log_file,
                    cfg=cfg,
                    setup=entry_setup,
                    event_type="SKIP_ORDER_BLOCK",
                    message=message,
                    csv_row=base_row,
                )
            else:
                log_event(log_file, {**base_row, "event": "SKIP_ORDER_BLOCK", "message": message})
            return

        ob_distance = order_block_distance_pips(price, order_block["low"], order_block["high"], pip)
        ob_note = order_block_note(order_block, ob_distance)
        range_note = ""
        if entry_setup is not None:
            range_note = str(entry_setup.context.get("filters", {}).get("range_note", ""))
        allowed_ob_distance, ob_override_note = resolve_order_block_distance_limit_pips(
            cfg.order_block_max_distance_pips,
            order_block,
            confirmation_mode=cfg.confirmation_mode,
            range_note=range_note,
            strong_override_max_distance_pips=cfg.order_block_strong_override_max_distance_pips,
            strong_override_min_impulse_pips=cfg.order_block_strong_override_min_impulse_pips,
        )
        if ob_override_note:
            ob_note = f"{ob_note} {ob_override_note}".strip()
        if ob_distance > allowed_ob_distance:
            message = f"{ob_note} max_ob_dist={allowed_ob_distance:.2f}p"
            if entry_setup is not None:
                cancel_entry_setup(
                    repo=repo,
                    app_config=app_config,
                    log_file=log_file,
                    cfg=cfg,
                    setup=entry_setup,
                    event_type="SKIP_ORDER_BLOCK",
                    message=message,
                    csv_row=base_row,
                )
            else:
                log_event(
                    log_file,
                    {
                        **base_row,
                        "event": "SKIP_ORDER_BLOCK",
                        "message": message,
                    },
                )
            return

    equity = adapter.account_equity()
    cap_message = portfolio_caps_message(adapter, app_config, cfg, equity)
    if cap_message:
        if entry_setup is not None:
            with repo.transaction():
                repo.transition_pending_setup(
                    entry_setup.setup_id,
                    PENDING_STATUS_CANCELED,
                    last_note="entry_blocked:SKIP_PORTFOLIO_CAP",
                    closed_reason="entry_blocked:SKIP_PORTFOLIO_CAP",
                )
                emit_event(
                    log_file=log_file,
                    repo=repo,
                    app_config=app_config,
                    event_type="SKIP_PORTFOLIO_CAP",
                    symbol=cfg.symbol,
                    setup_id=entry_setup.setup_id,
                    message=cap_message,
                    payload={"equity": float(equity)},
                    csv_row=base_row,
                )
        else:
            emit_event(
                log_file=log_file,
                repo=repo,
                app_config=app_config,
                event_type="SKIP_PORTFOLIO_CAP",
                symbol=cfg.symbol,
                message=cap_message,
                payload={"equity": float(equity)},
                csv_row=base_row,
            )
        return

    trade_info = SymbolTradeInfo.from_mt5(info)
    volume = calc_lot_by_risk(equity, cfg.sl_pips, cfg.risk_pct, trade_info, cfg.max_lot)

    context_message = " ".join(part for part in [f"confirm={confirm_note}", bias_note, ob_note] if part).strip()

    if app_config.runtime.dry_run:
        state.last_trade_ts = now_ts
        state.cooldown_until = now_ts + max(0, cfg.cooldown_sec)
        state.entry_count += 1
        if entry_setup is not None:
            repo.transition_pending_setup(
                entry_setup.setup_id,
                PENDING_STATUS_CANCELED,
                last_note="dry_run_no_execution",
                closed_reason="dry_run_no_execution",
            )

        log_event(
            log_file,
            {
                **base_row,
                "event": "DRY_RUN_SIGNAL",
                "volume": volume,
                "price": price,
                "sl": sl,
                "tp": tp,
                "message": f"dry_run=true {context_message}".strip(),
            },
        )
        print(
            f"[{now_utc.isoformat()}] DRY_RUN {cfg.symbol} {entry_side} level={entry_level:.5f} "
            f"entry={price:.5f} sl={sl:.5f} tp={tp:.5f} vol={volume:.2f} {context_message}"
        )
        return

    comment = f"SWEEP@{entry_level:.5f}"
    if entry_setup is not None:
        comment = f"{comment}|{entry_setup.setup_id[:8]}"
    comment = comment[:31]

    result = adapter.send_market_order_with_fallback(
        symbol=cfg.symbol,
        side=entry_side,
        volume=volume,
        sl_pips=cfg.sl_pips,
        tp_pips=cfg.tp_pips,
        magic=cfg.magic,
        comment=comment,
        deviation=app_config.runtime.default_deviation,
    )

    ticket: Optional[int] = None
    if result.ok:
        with repo.transaction():
            state.last_trade_ts = now_ts
            state.cooldown_until = now_ts + max(0, cfg.cooldown_sec)
            state.entry_count += 1

            resolved = _resolve_recent_position(adapter, cfg, entry_side, comment)
            if resolved is not None:
                ticket = int(getattr(resolved, "ticket", 0) or 0)
                if ticket > 0:
                    linked_setup_id = entry_setup.setup_id if entry_setup is not None else None
                    repo.upsert_open_position(position_to_record(cfg, resolved, linked_setup_id))
            if entry_setup is not None:
                repo.transition_pending_setup(
                    entry_setup.setup_id,
                    PENDING_STATUS_EXECUTED,
                    last_note=context_message or "executed",
                    executed_ticket=ticket or (int(result.order) if result.order is not None else None),
                )
            emit_event(
                log_file=log_file,
                repo=repo,
                app_config=app_config,
                event_type="TRADE_OK",
                symbol=cfg.symbol,
                setup_id=entry_setup.setup_id if entry_setup is not None else None,
                ticket=ticket,
                message=context_message,
                payload={
                    "side": entry_side,
                    "volume": volume,
                    "price": result.price,
                    "sl": result.sl,
                    "tp": result.tp,
                    "retcode": result.retcode,
                    "order": result.order,
                    "deal": result.deal,
                },
                csv_row={
                    **base_row,
                    "position": ticket or "",
                    "volume": volume,
                    "price": result.price,
                    "sl": result.sl,
                    "tp": result.tp,
                    "retcode": result.retcode,
                    "order": result.order,
                    "deal": result.deal,
                },
            )
    else:
        with repo.transaction():
            if entry_setup is not None:
                fail_note = str(result.raw) if result.raw is not None else "trade_send_failed"
                repo.transition_pending_setup(
                    entry_setup.setup_id,
                    PENDING_STATUS_FAILED,
                    last_note=fail_note,
                    closed_reason=fail_note,
                )
            emit_event(
                log_file=log_file,
                repo=repo,
                app_config=app_config,
                event_type="TRADE_FAIL",
                symbol=cfg.symbol,
                setup_id=entry_setup.setup_id if entry_setup is not None else None,
                ticket=ticket,
                message=f"{context_message} {result.raw}".strip(),
                payload={
                    "side": entry_side,
                    "volume": volume,
                    "price": result.price,
                    "sl": result.sl,
                    "tp": result.tp,
                    "retcode": result.retcode,
                    "order": result.order,
                    "deal": result.deal,
                },
                csv_row={
                    **base_row,
                    "position": ticket or "",
                    "volume": volume,
                    "price": result.price,
                    "sl": result.sl,
                    "tp": result.tp,
                    "retcode": result.retcode,
                    "order": result.order,
                    "deal": result.deal,
                },
            )


def run(config_path: str = "config/settings.json") -> None:
    app_config = load_config(config_path)
    adapter = MT5Adapter(default_deviation=app_config.runtime.default_deviation)
    log_file = Path(app_config.runtime.log_file)
    repo = SQLiteRepository(app_config.runtime.db_path)
    bot_instance_id = uuid4().hex
    repo.set_bot_instance_id(bot_instance_id)

    states = {cfg.symbol: SymbolState() for cfg in app_config.symbols}
    global_state = GlobalState()

    try:
        adapter.initialize()
        for cfg in app_config.symbols:
            adapter.ensure_symbol(cfg.symbol)

        recovery_logger = recovery_event_logger(log_file, app_config, repo)
        local_open_count = len(repo.list_open_positions(status=POSITION_STATUS_OPEN))
        local_pending_count = len(repo.list_active_pending_setups())
        local_runtime_count = len(repo.list_symbol_runtime_states())
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type="RECOVERY_PHASE",
            symbol="ALL",
            message=(
                f"1_load_local_state open={local_open_count} "
                f"pending={local_pending_count} runtime={local_runtime_count}"
            ),
            payload={"phase": 1},
        )
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type="RECOVERY_PHASE",
            symbol="ALL",
            message="2_load_broker_snapshot_and_reconcile",
            payload={"phase": 2},
        )
        pending_by_symbol, recovery_stats = bootstrap_recovery(adapter, app_config, repo, recovery_logger)
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type="RECOVERY_PHASE",
            symbol="ALL",
            message="3_rebuild_memory_state",
            payload={"phase": 3},
        )
        restore_runtime_state(repo, app_config, states, global_state, pending_by_symbol)
        cleanup_stale_retry_state(repo, app_config, states, log_file)
        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type="RECOVERY_PHASE",
            symbol="ALL",
            message="4_start_loop",
            payload={"phase": 4},
        )

        emit_event(
            log_file=log_file,
            repo=repo,
            app_config=app_config,
            event_type="RECOVERY_PORTFOLIO_BASELINE",
            symbol="ALL",
            message="portfolio snapshot after startup reconciliation",
            payload={
                "open_positions": total_open_positions_count(adapter, app_config),
                "open_risk_money": total_open_risk_money(adapter, app_config),
            },
        )

        print(
            f"SWEEP_V2 START dry_run={app_config.runtime.dry_run} poll={app_config.runtime.poll_seconds}s "
            f"log={log_file} db={app_config.runtime.db_path} "
            f"bot_instance_id={bot_instance_id} "
            f"daily_loss=${app_config.runtime.daily_loss_limit_usd:.2f} "
            f"close_on_loss={app_config.runtime.close_positions_on_daily_loss} "
            f"per_trade_loss_mode={app_config.runtime.per_trade_loss_guard_mode} "
            f"per_trade_loss_fixed=${app_config.runtime.max_loss_per_trade_usd:.2f} "
            f"per_trade_loss_risk_mult={app_config.runtime.per_trade_loss_risk_multiple:.2f} "
            f"per_trade_profit=${app_config.runtime.max_profit_per_trade_usd:.2f} "
            f"trailing={app_config.runtime.trailing_stop_mode}/"
            f"{app_config.runtime.trailing_activation_r:.2f}R/"
            f"{app_config.runtime.trailing_gap_r:.2f}R/"
            f"remove_tp={app_config.runtime.trailing_remove_tp_on_activation} "
            f"cap_positions={app_config.runtime.max_open_positions_total} "
            f"cap_open_risk_pct={app_config.runtime.max_total_open_risk_pct:.2f}"
        )
        print(
            "RECOVERY "
            f"broker_only={recovery_stats.broker_only_count} "
            f"local_closed={recovery_stats.local_only_closed_count} "
            f"mismatch={recovery_stats.mismatch_count} "
            f"expired_pending={recovery_stats.expired_pending_count}"
        )

        for cfg in app_config.symbols:
            print(
                f"{cfg.symbol} tf={cfg.timeframe} confirm={cfg.confirmation_mode}/{cfg.confirm_expiry_bars} "
                f"cisd={cfg.cisd_timeframe}/{cfg.cisd_structure_bars}/{cfg.cisd_lookback_bars} "
                f"bias={cfg.use_bias_filter}/{cfg.bias_timeframe}/{cfg.bias_ema_period} "
                f"ob={cfg.use_order_block_filter}/{cfg.order_block_zone_mode}/{cfg.order_block_lookback_bars}/"
                f"{cfg.order_block_max_distance_pips}/{cfg.order_block_min_impulse_pips}/{cfg.order_block_max_age_bars}"
            )

        checkpoint_interval_sec = max(1, int(getattr(app_config.runtime, "checkpoint_interval_sec", 5)))
        maintenance_interval_sec = max(30, int(getattr(app_config.runtime, "maintenance_interval_sec", 3600)))
        next_checkpoint_ts = time.time() + checkpoint_interval_sec
        next_maintenance_ts = time.time() + maintenance_interval_sec

        while True:
            daily_loss_reached = apply_daily_loss_guard(adapter, app_config, global_state, log_file, repo)
            for cfg in app_config.symbols:
                state = states[cfg.symbol]
                try:
                    sync_open_positions_for_symbol(adapter, cfg, app_config, repo, log_file)
                    manage_symbol_positions(adapter, cfg, app_config, state, log_file, repo)
                    if not daily_loss_reached:
                        process_symbol(adapter, cfg, app_config, state, log_file, repo)
                except Exception as exc:
                    now_utc = datetime.now(timezone.utc)
                    print(f"[{now_utc.isoformat()}] {cfg.symbol} ERROR {exc}")
                    log_event(
                        log_file,
                        {
                            "ts": now_utc.isoformat(),
                            "symbol": cfg.symbol,
                            "timeframe": cfg.timeframe,
                            "strategy": "SWEEP_V2",
                            "event": "ERROR",
                            "message": str(exc),
                        },
                    )

            now_ts = time.time()
            if now_ts >= next_checkpoint_ts:
                checkpoint_state_snapshot(repo, app_config, states, global_state, log_file)
                next_checkpoint_ts = now_ts + checkpoint_interval_sec

            now_utc = datetime.now(timezone.utc)
            if now_ts >= next_maintenance_ts:
                run_periodic_retention(repo, app_config, log_file, now_utc)
                next_maintenance_ts = now_ts + maintenance_interval_sec

            time.sleep(app_config.runtime.poll_seconds)
    finally:
        repo.close()
        adapter.shutdown()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
