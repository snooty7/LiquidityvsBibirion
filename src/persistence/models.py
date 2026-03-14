from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


PENDING_STATUS_PENDING = "PENDING"
PENDING_STATUS_CONFIRMED = "CONFIRMED"
PENDING_STATUS_EXECUTED = "EXECUTED"
PENDING_STATUS_REJECTED = "REJECTED"
PENDING_STATUS_EXPIRED = "EXPIRED"
PENDING_STATUS_CANCELED = "CANCELED"
PENDING_STATUS_FAILED = "FAILED"

PENDING_ACTIVE_STATUSES = (PENDING_STATUS_PENDING, PENDING_STATUS_CONFIRMED)
PENDING_TERMINAL_STATUSES = (
    PENDING_STATUS_EXECUTED,
    PENDING_STATUS_REJECTED,
    PENDING_STATUS_EXPIRED,
    PENDING_STATUS_CANCELED,
    PENDING_STATUS_FAILED,
)

POSITION_STATUS_OPEN = "OPEN"
POSITION_STATUS_CLOSED = "CLOSED"


@dataclass(frozen=True)
class PendingSetupRecord:
    setup_id: str
    dedupe_key: str
    symbol: str
    timeframe: str
    side: str
    level: float
    candle_time: int
    signal_key: str
    status: str
    expires_at: int
    context: Dict[str, Any] = field(default_factory=dict)
    last_note: str = ""
    executed_ticket: Optional[int] = None
    closed_reason: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class OpenPositionRecord:
    ticket: int
    symbol: str
    magic: int
    setup_id: Optional[str]
    side: str
    volume: float
    open_price: float
    sl: float
    tp: float
    comment: str = ""
    opened_at: Optional[int] = None
    status: str = POSITION_STATUS_OPEN
    first_seen_at: str = ""
    last_seen_at: str = ""
    closed_at: Optional[str] = None
    close_reason: Optional[str] = None


@dataclass(frozen=True)
class GuardStateRecord:
    day_key: str
    daily_realized_pnl: float
    daily_loss_reached: bool
    daily_loss_announced: bool
    updated_at: str


@dataclass(frozen=True)
class SymbolRuntimeStateRecord:
    symbol: str
    timeframe: str
    last_trade_ts: float
    cooldown_until: float
    entry_count: int
    last_processed_bar_time: int
    last_signal_key: Optional[str]
    updated_at: str


@dataclass(frozen=True)
class RiskRetryRecord:
    ticket: int
    symbol: str
    retry_after: float
    reason: str
    attempts: int
    last_error: str
    updated_at: str


@dataclass(frozen=True)
class PersistedEventRecord:
    event_type: str
    trading_day: str
    symbol: str
    setup_id: Optional[str]
    ticket: Optional[int]
    bot_instance_id: str
    created_at_utc: str
    payload_json: str
    event_id: int = 0


@dataclass(frozen=True)
class RecoveryStats:
    broker_only_count: int
    local_only_closed_count: int
    mismatch_count: int
    expired_pending_count: int
