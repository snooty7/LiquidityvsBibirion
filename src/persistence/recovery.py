from __future__ import annotations

from hashlib import sha256
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from src.persistence.models import OpenPositionRecord, PendingSetupRecord, RecoveryStats, PENDING_STATUS_EXPIRED
from src.persistence.repository import SQLiteRepository


def make_setup_id() -> str:
    return str(uuid4())


def build_setup_dedupe_key(
    symbol: str,
    timeframe: str,
    side: str,
    level: float,
    candle_time: int,
    signal_key: str,
) -> str:
    payload = f"{symbol}|{timeframe}|{side}|{level:.8f}|{int(candle_time)}|{signal_key}"
    return sha256(payload.encode("utf-8")).hexdigest()


def compute_setup_expiry(candle_time: int, timeframe_seconds: int, expiry_bars: int) -> int:
    return int(candle_time) + max(1, int(expiry_bars)) * max(1, int(timeframe_seconds))


def latest_closed_bar_time(adapter, symbol: str, timeframe: str) -> int:
    try:
        rates = adapter.copy_rates(symbol, timeframe, 3)
    except Exception:
        return int(time.time())
    if len(rates) < 2:
        return int(time.time())
    return int(rates[-2]["time"])


def build_pending_setup_record(
    symbol: str,
    timeframe: str,
    side: str,
    level: float,
    candle_time: int,
    signal_key: str,
    expires_at: int,
    context: Dict,
    initial_status: str,
) -> PendingSetupRecord:
    dedupe_key = build_setup_dedupe_key(symbol, timeframe, side, level, candle_time, signal_key)
    return PendingSetupRecord(
        setup_id=make_setup_id(),
        dedupe_key=dedupe_key,
        symbol=symbol,
        timeframe=timeframe,
        side=side,
        level=float(level),
        candle_time=int(candle_time),
        signal_key=signal_key,
        status=initial_status,
        expires_at=int(expires_at),
        context=dict(context),
        last_note="created",
    )


def _same_position(local: OpenPositionRecord, broker: OpenPositionRecord) -> bool:
    if local.symbol != broker.symbol:
        return False
    if local.side != broker.side:
        return False
    if abs(local.volume - broker.volume) > 1e-10:
        return False
    if abs(local.open_price - broker.open_price) > 1e-10:
        return False
    if abs(local.sl - broker.sl) > 1e-10:
        return False
    if abs(local.tp - broker.tp) > 1e-10:
        return False
    return True


def _emit_recovery_event(
    repo: SQLiteRepository,
    log_event: Callable[[dict], None],
    event_type: str,
    symbol: str,
    message: str,
    *,
    side: Optional[str] = None,
    ticket: Optional[int] = None,
    setup_id: Optional[str] = None,
    level: Optional[float] = None,
    candle_time: Optional[int] = None,
    payload: Optional[dict] = None,
) -> None:
    payload_data = dict(payload or {})
    if message:
        payload_data.setdefault("message", message)
    if side is not None:
        payload_data.setdefault("side", side)
    if ticket is not None:
        payload_data.setdefault("ticket", int(ticket))
    if level is not None:
        payload_data.setdefault("level", float(level))
    if candle_time is not None:
        payload_data.setdefault("candle_time", int(candle_time))

    persisted = repo.append_event(
        event_type=event_type,
        symbol=symbol,
        setup_id=setup_id,
        ticket=ticket,
        payload=payload_data,
    )

    try:
        log_event(
            {
                "event": event_type,
                "event_type": event_type,
                "symbol": symbol,
                "side": side or "",
                "position": ticket or "",
                "setup_id": setup_id or "",
                "level": f"{level:.5f}" if level is not None else "",
                "candle_time": int(candle_time) if candle_time is not None else "",
                "message": message,
                "created_at_utc": persisted.created_at_utc,
                "trading_day": persisted.trading_day,
                "bot_instance_id": persisted.bot_instance_id,
                "payload_json": persisted.payload_json,
            }
        )
    except Exception:
        # CSV/console side channel should never break recovery persistence.
        pass


def _setup_hint_from_comment(comment: str) -> Optional[str]:
    raw = str(comment or "").strip()
    if "|" not in raw:
        return None
    hint = raw.split("|")[-1].strip()
    if len(hint) < 4:
        return None
    return hint


def _resolve_setup_link_from_comment(
    repo: SQLiteRepository,
    symbol: str,
    comment: str,
) -> tuple[Optional[str], str]:
    hint = _setup_hint_from_comment(comment)
    if hint is None:
        return None, "no_hint"

    match = repo.find_setup_by_id_prefix(hint, symbol=symbol)
    if match is None:
        return None, f"hint_unresolved:{hint}"
    return match.setup_id, f"hint_resolved:{hint}"


def _merged_setup_id(local: Optional[OpenPositionRecord], broker: OpenPositionRecord) -> tuple[Optional[str], str]:
    if local is not None and local.setup_id:
        return local.setup_id, "local"
    if broker.setup_id:
        return broker.setup_id, "broker"
    return None, "none"


def reconcile_broker_positions(
    repo: SQLiteRepository,
    broker_positions: Iterable[OpenPositionRecord],
    log_event: Callable[[dict], None],
) -> RecoveryStats:
    broker_map: Dict[int, OpenPositionRecord] = {int(pos.ticket): pos for pos in broker_positions}
    local_open = {int(pos.ticket): pos for pos in repo.list_open_positions(status="OPEN")}

    broker_only_count = 0
    local_only_closed_count = 0
    mismatch_count = 0

    for ticket, local in local_open.items():
        if ticket in broker_map:
            continue
        with repo.transaction():
            repo.mark_open_position_closed(ticket, "missing_on_broker_recovery")
            _emit_recovery_event(
                repo,
                log_event,
                "RECOVERY_LOCAL_ONLY_CLOSED",
                local.symbol,
                "local open position missing on broker; marked closed",
                side=local.side,
                ticket=ticket,
                setup_id=local.setup_id,
                payload={"policy": "mark_closed_missing_on_broker"},
            )
        local_only_closed_count += 1

    for ticket, broker in broker_map.items():
        local = local_open.get(ticket)
        setup_id, setup_link_source = _merged_setup_id(local, broker)

        with repo.transaction():
            if local is None:
                broker_only_count += 1
                _emit_recovery_event(
                    repo,
                    log_event,
                    "RECOVERY_BROKER_ONLY",
                    broker.symbol,
                    "broker open position not present locally; inserted",
                    side=broker.side,
                    ticket=ticket,
                    setup_id=setup_id,
                    payload={"policy": "insert_from_broker_snapshot"},
                )
            elif not _same_position(local, broker):
                mismatch_count += 1
                _emit_recovery_event(
                    repo,
                    log_event,
                    "RECOVERY_MISMATCH",
                    broker.symbol,
                    "broker/local position fields differed; broker snapshot persisted",
                    side=broker.side,
                    ticket=ticket,
                    setup_id=setup_id,
                    payload={
                        "policy": "broker_for_open_fields",
                        "local_open_price": local.open_price,
                        "local_sl": local.sl,
                        "local_tp": local.tp,
                        "local_volume": local.volume,
                        "broker_open_price": broker.open_price,
                        "broker_sl": broker.sl,
                        "broker_tp": broker.tp,
                        "broker_volume": broker.volume,
                    },
                )

            if local is not None and local.setup_id and broker.setup_id and local.setup_id != broker.setup_id:
                _emit_recovery_event(
                    repo,
                    log_event,
                    "RECOVERY_SETUP_LINK_MISMATCH",
                    broker.symbol,
                    "local/broker setup links differed; local link retained",
                    side=broker.side,
                    ticket=ticket,
                    setup_id=local.setup_id,
                    payload={
                        "policy": "keep_local_setup_link",
                        "local_setup_id": local.setup_id,
                        "broker_setup_id": broker.setup_id,
                    },
                )

            merged = OpenPositionRecord(
                ticket=broker.ticket,
                symbol=broker.symbol,
                magic=broker.magic,
                setup_id=setup_id,
                side=broker.side,
                volume=broker.volume,
                open_price=broker.open_price,
                sl=broker.sl,
                tp=broker.tp,
                comment=broker.comment,
                opened_at=broker.opened_at,
                status=broker.status,
                first_seen_at=broker.first_seen_at,
                last_seen_at=broker.last_seen_at,
                closed_at=broker.closed_at,
                close_reason=broker.close_reason,
            )
            repo.upsert_open_position(merged)

            _emit_recovery_event(
                repo,
                log_event,
                "RECOVERY_SETUP_LINK_POLICY",
                broker.symbol,
                "applied deterministic setup-link policy",
                side=broker.side,
                ticket=ticket,
                setup_id=setup_id,
                payload={"setup_link_source": setup_link_source},
            )

            if setup_id is None:
                _emit_recovery_event(
                    repo,
                    log_event,
                    "RECOVERY_ORPHAN_BROKER_POSITION",
                    broker.symbol,
                    "broker position tracked as orphan (no deterministic setup link)",
                    side=broker.side,
                    ticket=ticket,
                    payload={"policy": "track_orphan_position"},
                )

    return RecoveryStats(
        broker_only_count=broker_only_count,
        local_only_closed_count=local_only_closed_count,
        mismatch_count=mismatch_count,
        expired_pending_count=0,
    )


def bootstrap_recovery(
    adapter,
    app_config,
    repo: SQLiteRepository,
    log_event: Callable[[dict], None],
) -> Tuple[Dict[str, PendingSetupRecord], RecoveryStats]:
    with repo.transaction():
        latest_bar_by_symbol = {
            cfg.symbol: latest_closed_bar_time(adapter, cfg.symbol, cfg.timeframe) for cfg in app_config.symbols
        }
        expired = []
        for item in repo.list_active_pending_setups():
            latest_bar = int(latest_bar_by_symbol.get(item.symbol, int(time.time())))
            if int(item.expires_at) > latest_bar:
                continue
            repo.transition_pending_setup(
                item.setup_id,
                PENDING_STATUS_EXPIRED,
                last_note="expired_during_startup_recovery",
                closed_reason="expired_during_startup_recovery",
            )
            expired.append(item)
            _emit_recovery_event(
                repo,
                log_event,
                "RECOVERY_PENDING_EXPIRED",
                item.symbol,
                "expired during startup recovery",
                side=item.side,
                setup_id=item.setup_id,
                level=item.level,
                candle_time=item.candle_time,
                payload={"latest_closed_bar_time": latest_bar},
            )

    local_open_by_ticket = {int(pos.ticket): pos for pos in repo.list_open_positions(status="OPEN")}
    broker_positions: List[OpenPositionRecord] = []

    for cfg in app_config.symbols:
        for position in adapter.positions_get(cfg.symbol, magic=cfg.magic):
            ticket = int(position.ticket)
            side = "BUY" if int(position.type) == 0 else "SELL"
            comment = str(getattr(position, "comment", "") or "")

            local_setup_id = local_open_by_ticket.get(ticket).setup_id if ticket in local_open_by_ticket else None
            resolved_setup_id = local_setup_id
            resolution = "from_local_ticket"

            if resolved_setup_id is None:
                resolved_setup_id, resolution = _resolve_setup_link_from_comment(repo, cfg.symbol, comment)

            if comment and not (comment.startswith("SWEEP@") or comment.startswith("CLOSE:")):
                _emit_recovery_event(
                    repo,
                    log_event,
                    "RECOVERY_COMMENT_MISMATCH",
                    cfg.symbol,
                    f"unexpected position comment='{comment}' for bot magic={cfg.magic}",
                    side=side,
                    ticket=ticket,
                    payload={"policy": "still_track_by_magic"},
                )

            if resolved_setup_id is not None and resolution.startswith("hint_resolved"):
                _emit_recovery_event(
                    repo,
                    log_event,
                    "RECOVERY_SETUP_LINK_REBUILT",
                    cfg.symbol,
                    "recovered setup link from broker comment hint",
                    side=side,
                    ticket=ticket,
                    setup_id=resolved_setup_id,
                    payload={"resolution": resolution},
                )
            elif resolved_setup_id is None and resolution.startswith("hint_unresolved"):
                _emit_recovery_event(
                    repo,
                    log_event,
                    "RECOVERY_SETUP_LINK_UNRESOLVED",
                    cfg.symbol,
                    "comment hint did not resolve deterministically",
                    side=side,
                    ticket=ticket,
                    payload={"resolution": resolution},
                )

            broker_positions.append(
                OpenPositionRecord(
                    ticket=ticket,
                    symbol=cfg.symbol,
                    magic=cfg.magic,
                    setup_id=resolved_setup_id,
                    side=side,
                    volume=float(getattr(position, "volume", 0.0) or 0.0),
                    open_price=float(getattr(position, "price_open", 0.0) or 0.0),
                    sl=float(getattr(position, "sl", 0.0) or 0.0),
                    tp=float(getattr(position, "tp", 0.0) or 0.0),
                    comment=comment,
                    opened_at=int(getattr(position, "time", 0) or 0),
                    status="OPEN",
                )
            )

    stats = reconcile_broker_positions(repo, broker_positions, log_event)
    stats = RecoveryStats(
        broker_only_count=stats.broker_only_count,
        local_only_closed_count=stats.local_only_closed_count,
        mismatch_count=stats.mismatch_count,
        expired_pending_count=len(expired),
    )

    pending_by_symbol: Dict[str, PendingSetupRecord] = {}
    for cfg in app_config.symbols:
        pending = repo.get_latest_active_pending_setup(cfg.symbol)
        if pending is None:
            continue
        pending_by_symbol[cfg.symbol] = pending
        _emit_recovery_event(
            repo,
            log_event,
            "RECOVERY_PENDING_RESTORED",
            cfg.symbol,
            "pending setup restored into restart revalidation queue",
            side=pending.side,
            setup_id=pending.setup_id,
            level=pending.level,
            candle_time=pending.candle_time,
            payload={"requires_revalidation": True},
        )

    _emit_recovery_event(
        repo,
        log_event,
        "RECOVERY_SUMMARY",
        "ALL",
        (
            f"broker_only={stats.broker_only_count} "
            f"local_closed={stats.local_only_closed_count} "
            f"mismatch={stats.mismatch_count} "
            f"expired_pending={stats.expired_pending_count}"
        ),
        payload={
            "broker_only_count": stats.broker_only_count,
            "local_only_closed_count": stats.local_only_closed_count,
            "mismatch_count": stats.mismatch_count,
            "expired_pending_count": stats.expired_pending_count,
        },
    )

    return pending_by_symbol, stats
