from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Dict, Iterator, List, Optional, Tuple

from src.persistence.db import get_connection, init_schema, utc_now_iso
from src.persistence.models import (
    GuardStateRecord,
    OpenPositionRecord,
    PendingSetupRecord,
    PersistedEventRecord,
    POSITION_STATUS_CLOSED,
    POSITION_STATUS_OPEN,
    PENDING_ACTIVE_STATUSES,
    PENDING_STATUS_EXPIRED,
    RiskRetryRecord,
    SymbolRuntimeStateRecord,
)


class SQLiteRepository:
    def __init__(self, db_path: str) -> None:
        self.conn = get_connection(db_path)
        init_schema(self.conn)
        self._tx_depth = 0
        self._bot_instance_id = "unknown"

    def close(self) -> None:
        self.conn.close()

    def set_bot_instance_id(self, bot_instance_id: str) -> None:
        self._bot_instance_id = str(bot_instance_id or "unknown")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        started = self._tx_depth == 0
        if started:
            self.conn.execute("BEGIN IMMEDIATE")
        self._tx_depth += 1
        try:
            yield
        except Exception:
            self._tx_depth = max(0, self._tx_depth - 1)
            if started:
                self.conn.rollback()
            raise
        else:
            self._tx_depth = max(0, self._tx_depth - 1)
            if started:
                self.conn.commit()

    def _maybe_commit(self) -> None:
        if self._tx_depth == 0:
            self.conn.commit()

    @staticmethod
    def _coerce_utc_iso(value: Optional[str] = None) -> str:
        if not value:
            return utc_now_iso()
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware UTC ISO string.")
        return dt.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _trading_day_from_utc_iso(value: str) -> str:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            raise ValueError("created_at_utc must include timezone information.")
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _pending_from_row(row: sqlite3.Row) -> PendingSetupRecord:
        return PendingSetupRecord(
            setup_id=str(row["setup_id"]),
            dedupe_key=str(row["dedupe_key"]),
            symbol=str(row["symbol"]),
            timeframe=str(row["timeframe"]),
            side=str(row["side"]),
            level=float(row["level"]),
            candle_time=int(row["candle_time"]),
            signal_key=str(row["signal_key"]),
            status=str(row["status"]),
            expires_at=int(row["expires_at"]),
            context=json.loads(str(row["context_json"])),
            last_note=str(row["last_note"] or ""),
            executed_ticket=int(row["executed_ticket"]) if row["executed_ticket"] is not None else None,
            closed_reason=str(row["closed_reason"]) if row["closed_reason"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _position_from_row(row: sqlite3.Row) -> OpenPositionRecord:
        return OpenPositionRecord(
            ticket=int(row["ticket"]),
            symbol=str(row["symbol"]),
            magic=int(row["magic"]),
            setup_id=str(row["setup_id"]) if row["setup_id"] is not None else None,
            side=str(row["side"]),
            volume=float(row["volume"]),
            open_price=float(row["open_price"]),
            sl=float(row["sl"]),
            tp=float(row["tp"]),
            comment=str(row["comment"] or ""),
            opened_at=int(row["opened_at"]) if row["opened_at"] is not None else None,
            status=str(row["status"]),
            first_seen_at=str(row["first_seen_at"]),
            last_seen_at=str(row["last_seen_at"]),
            closed_at=str(row["closed_at"]) if row["closed_at"] is not None else None,
            close_reason=str(row["close_reason"]) if row["close_reason"] is not None else None,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> PersistedEventRecord:
        return PersistedEventRecord(
            event_type=str(row["event_type"]),
            trading_day=str(row["trading_day"]),
            symbol=str(row["symbol"]),
            setup_id=str(row["setup_id"]) if row["setup_id"] is not None else None,
            ticket=int(row["ticket"]) if row["ticket"] is not None else None,
            bot_instance_id=str(row["bot_instance_id"]),
            created_at_utc=str(row["created_at_utc"]),
            payload_json=str(row["payload_json"]),
            event_id=int(row["event_id"]) if row["event_id"] is not None else 0,
        )

    def create_or_get_pending_setup(self, record: PendingSetupRecord) -> Tuple[PendingSetupRecord, bool]:
        now = utc_now_iso()
        created_at = record.created_at or now
        updated_at = now
        context_json = json.dumps(record.context or {}, separators=(",", ":"), sort_keys=True)

        try:
            self.conn.execute(
                """
                INSERT INTO pending_setups (
                    setup_id, dedupe_key, symbol, timeframe, side, level, candle_time,
                    signal_key, status, expires_at, context_json, last_note,
                    executed_ticket, closed_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.setup_id,
                    record.dedupe_key,
                    record.symbol,
                    record.timeframe,
                    record.side,
                    record.level,
                    record.candle_time,
                    record.signal_key,
                    record.status,
                    record.expires_at,
                    context_json,
                    record.last_note,
                    record.executed_ticket,
                    record.closed_reason,
                    created_at,
                    updated_at,
                ),
            )
            self._maybe_commit()
            created = True
        except sqlite3.IntegrityError:
            created = False

        found = self.get_pending_setup_by_dedupe_key(record.dedupe_key)
        if found is None:
            raise RuntimeError("Failed to create or load pending setup by dedupe key.")
        return found, created

    def get_pending_setup_by_dedupe_key(self, dedupe_key: str) -> Optional[PendingSetupRecord]:
        row = self.conn.execute(
            "SELECT * FROM pending_setups WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()
        return self._pending_from_row(row) if row is not None else None

    def get_pending_setup_by_id(self, setup_id: str) -> Optional[PendingSetupRecord]:
        row = self.conn.execute(
            "SELECT * FROM pending_setups WHERE setup_id = ?",
            (setup_id,),
        ).fetchone()
        return self._pending_from_row(row) if row is not None else None

    def find_setup_by_id_prefix(self, setup_id_prefix: str, symbol: Optional[str] = None) -> Optional[PendingSetupRecord]:
        prefix = str(setup_id_prefix or "").strip()
        if not prefix:
            return None

        if symbol is None:
            rows = self.conn.execute(
                "SELECT * FROM pending_setups WHERE setup_id LIKE ? ORDER BY updated_at DESC",
                (f"{prefix}%",),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM pending_setups
                WHERE symbol = ? AND setup_id LIKE ?
                ORDER BY updated_at DESC
                """,
                (symbol, f"{prefix}%"),
            ).fetchall()

        if len(rows) != 1:
            return None
        return self._pending_from_row(rows[0])

    def list_active_pending_setups(self, symbol: Optional[str] = None) -> List[PendingSetupRecord]:
        if symbol is None:
            rows = self.conn.execute(
                "SELECT * FROM pending_setups WHERE status IN (?, ?) ORDER BY updated_at DESC",
                PENDING_ACTIVE_STATUSES,
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM pending_setups WHERE symbol = ? AND status IN (?, ?) ORDER BY updated_at DESC",
                (symbol, PENDING_ACTIVE_STATUSES[0], PENDING_ACTIVE_STATUSES[1]),
            ).fetchall()
        return [self._pending_from_row(row) for row in rows]

    def get_latest_active_pending_setup(self, symbol: str) -> Optional[PendingSetupRecord]:
        row = self.conn.execute(
            """
            SELECT * FROM pending_setups
            WHERE symbol = ? AND status IN (?, ?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (symbol, PENDING_ACTIVE_STATUSES[0], PENDING_ACTIVE_STATUSES[1]),
        ).fetchone()
        return self._pending_from_row(row) if row is not None else None

    def transition_pending_setup(
        self,
        setup_id: str,
        status: str,
        last_note: Optional[str] = None,
        executed_ticket: Optional[int] = None,
        closed_reason: Optional[str] = None,
    ) -> None:
        now = utc_now_iso()
        current = self.get_pending_setup_by_id(setup_id)
        if current is None:
            return

        note_value = current.last_note if last_note is None else last_note
        exec_value = current.executed_ticket if executed_ticket is None else executed_ticket
        reason_value = current.closed_reason if closed_reason is None else closed_reason

        self.conn.execute(
            """
            UPDATE pending_setups
            SET status = ?, last_note = ?, executed_ticket = ?, closed_reason = ?, updated_at = ?
            WHERE setup_id = ?
            """,
            (status, note_value, exec_value, reason_value, now, setup_id),
        )
        self._maybe_commit()

    def touch_pending_note(self, setup_id: str, last_note: str) -> None:
        now = utc_now_iso()
        self.conn.execute(
            "UPDATE pending_setups SET last_note = ?, updated_at = ? WHERE setup_id = ?",
            (last_note, now, setup_id),
        )
        self._maybe_commit()

    def expire_pending_setups(self, now_ts: int) -> List[PendingSetupRecord]:
        rows = self.conn.execute(
            """
            SELECT * FROM pending_setups
            WHERE status IN (?, ?) AND expires_at <= ?
            """,
            (PENDING_ACTIVE_STATUSES[0], PENDING_ACTIVE_STATUSES[1], int(now_ts)),
        ).fetchall()

        expired = [self._pending_from_row(row) for row in rows]
        if not expired:
            return []

        now = utc_now_iso()
        for item in expired:
            self.conn.execute(
                """
                UPDATE pending_setups
                SET status = ?, closed_reason = ?, updated_at = ?
                WHERE setup_id = ?
                """,
                (PENDING_STATUS_EXPIRED, "expired", now, item.setup_id),
            )
        self._maybe_commit()
        return expired

    def upsert_open_position(self, record: OpenPositionRecord) -> None:
        now = utc_now_iso()
        first_seen = record.first_seen_at or now
        last_seen = record.last_seen_at or now

        self.conn.execute(
            """
            INSERT INTO open_positions (
                ticket, symbol, magic, setup_id, side, volume, open_price, sl, tp,
                comment, opened_at, status, first_seen_at, last_seen_at, closed_at, close_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket) DO UPDATE SET
                symbol = excluded.symbol,
                magic = excluded.magic,
                setup_id = COALESCE(excluded.setup_id, open_positions.setup_id),
                side = excluded.side,
                volume = excluded.volume,
                open_price = excluded.open_price,
                sl = excluded.sl,
                tp = excluded.tp,
                comment = excluded.comment,
                opened_at = excluded.opened_at,
                status = ?,
                last_seen_at = excluded.last_seen_at,
                closed_at = NULL,
                close_reason = NULL
            """,
            (
                record.ticket,
                record.symbol,
                record.magic,
                record.setup_id,
                record.side,
                record.volume,
                record.open_price,
                record.sl,
                record.tp,
                record.comment,
                record.opened_at,
                POSITION_STATUS_OPEN,
                first_seen,
                last_seen,
                record.closed_at,
                record.close_reason,
                POSITION_STATUS_OPEN,
            ),
        )
        self._maybe_commit()

    def get_open_position(self, ticket: int) -> Optional[OpenPositionRecord]:
        row = self.conn.execute(
            "SELECT * FROM open_positions WHERE ticket = ?",
            (int(ticket),),
        ).fetchone()
        return self._position_from_row(row) if row is not None else None

    def list_open_positions(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = POSITION_STATUS_OPEN,
    ) -> List[OpenPositionRecord]:
        params = []
        where_parts = []
        if symbol is not None:
            where_parts.append("symbol = ?")
            params.append(symbol)
        if status is not None:
            where_parts.append("status = ?")
            params.append(status)

        query = "SELECT * FROM open_positions"
        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)
        query += " ORDER BY last_seen_at DESC"

        rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._position_from_row(row) for row in rows]

    def mark_open_position_closed(self, ticket: int, reason: str) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            UPDATE open_positions
            SET status = ?, closed_at = ?, close_reason = ?, last_seen_at = ?
            WHERE ticket = ?
            """,
            (POSITION_STATUS_CLOSED, now, reason, now, int(ticket)),
        )
        self._maybe_commit()

    def get_guard_state(self) -> GuardStateRecord:
        row = self.conn.execute("SELECT * FROM guard_state WHERE id = 1").fetchone()
        if row is None:
            return GuardStateRecord(
                day_key="",
                daily_realized_pnl=0.0,
                daily_loss_reached=False,
                daily_loss_announced=False,
                updated_at=utc_now_iso(),
            )
        return GuardStateRecord(
            day_key=str(row["day_key"]),
            daily_realized_pnl=float(row["daily_realized_pnl"]),
            daily_loss_reached=bool(int(row["daily_loss_reached"])),
            daily_loss_announced=bool(int(row["daily_loss_announced"])),
            updated_at=str(row["updated_at"]),
        )

    def save_guard_state(self, record: GuardStateRecord) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO guard_state (id, day_key, daily_realized_pnl, daily_loss_reached, daily_loss_announced, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                day_key = excluded.day_key,
                daily_realized_pnl = excluded.daily_realized_pnl,
                daily_loss_reached = excluded.daily_loss_reached,
                daily_loss_announced = excluded.daily_loss_announced,
                updated_at = excluded.updated_at
            """,
            (
                record.day_key,
                float(record.daily_realized_pnl),
                int(bool(record.daily_loss_reached)),
                int(bool(record.daily_loss_announced)),
                now,
            ),
        )
        self._maybe_commit()

    def get_symbol_runtime_state(self, symbol: str) -> Optional[SymbolRuntimeStateRecord]:
        row = self.conn.execute(
            "SELECT * FROM symbol_runtime_state WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if row is None:
            return None

        return SymbolRuntimeStateRecord(
            symbol=str(row["symbol"]),
            timeframe=str(row["timeframe"]),
            last_trade_ts=float(row["last_trade_ts"]),
            cooldown_until=float(row["cooldown_until"]),
            entry_count=int(row["entry_count"]),
            last_processed_bar_time=int(row["last_processed_bar_time"]),
            last_signal_key=str(row["last_signal_key"]) if row["last_signal_key"] is not None else None,
            updated_at=str(row["updated_at"]),
        )

    def save_symbol_runtime_state(self, record: SymbolRuntimeStateRecord) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO symbol_runtime_state (
                symbol, timeframe, last_trade_ts, cooldown_until, entry_count,
                last_processed_bar_time, last_signal_key, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                timeframe = excluded.timeframe,
                last_trade_ts = excluded.last_trade_ts,
                cooldown_until = excluded.cooldown_until,
                entry_count = excluded.entry_count,
                last_processed_bar_time = excluded.last_processed_bar_time,
                last_signal_key = excluded.last_signal_key,
                updated_at = excluded.updated_at
            """,
            (
                record.symbol,
                record.timeframe,
                float(record.last_trade_ts),
                float(record.cooldown_until),
                int(record.entry_count),
                int(record.last_processed_bar_time),
                record.last_signal_key,
                now,
            ),
        )
        self._maybe_commit()

    def list_symbol_runtime_states(self) -> List[SymbolRuntimeStateRecord]:
        rows = self.conn.execute("SELECT * FROM symbol_runtime_state").fetchall()
        result: List[SymbolRuntimeStateRecord] = []
        for row in rows:
            result.append(
                SymbolRuntimeStateRecord(
                    symbol=str(row["symbol"]),
                    timeframe=str(row["timeframe"]),
                    last_trade_ts=float(row["last_trade_ts"]),
                    cooldown_until=float(row["cooldown_until"]),
                    entry_count=int(row["entry_count"]),
                    last_processed_bar_time=int(row["last_processed_bar_time"]),
                    last_signal_key=str(row["last_signal_key"]) if row["last_signal_key"] is not None else None,
                    updated_at=str(row["updated_at"]),
                )
            )
        return result

    def set_risk_retry(
        self,
        ticket: int,
        symbol: str,
        retry_after: float,
        reason: str,
        last_error: str = "",
    ) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO risk_close_retry (ticket, symbol, retry_after, reason, attempts, last_error, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(ticket) DO UPDATE SET
                symbol = excluded.symbol,
                retry_after = excluded.retry_after,
                reason = excluded.reason,
                attempts = risk_close_retry.attempts + 1,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (int(ticket), symbol, float(retry_after), reason, last_error, now),
        )
        self._maybe_commit()

    def delete_risk_retry(self, ticket: int) -> None:
        self.conn.execute("DELETE FROM risk_close_retry WHERE ticket = ?", (int(ticket),))
        self._maybe_commit()

    def list_risk_retries(self, symbol: Optional[str] = None) -> List[RiskRetryRecord]:
        if symbol is None:
            rows = self.conn.execute("SELECT * FROM risk_close_retry").fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM risk_close_retry WHERE symbol = ?", (symbol,)).fetchall()

        result: List[RiskRetryRecord] = []
        for row in rows:
            result.append(
                RiskRetryRecord(
                    ticket=int(row["ticket"]),
                    symbol=str(row["symbol"]),
                    retry_after=float(row["retry_after"]),
                    reason=str(row["reason"] or ""),
                    attempts=int(row["attempts"] or 0),
                    last_error=str(row["last_error"] or ""),
                    updated_at=str(row["updated_at"]),
                )
            )
        return result

    def append_event(
        self,
        event_type: str,
        symbol: str,
        payload: Optional[Dict] = None,
        setup_id: Optional[str] = None,
        ticket: Optional[int] = None,
        trading_day: Optional[str] = None,
        bot_instance_id: Optional[str] = None,
        created_at_utc: Optional[str] = None,
    ) -> PersistedEventRecord:
        normalized_created = self._coerce_utc_iso(created_at_utc)
        normalized_day = str(trading_day or self._trading_day_from_utc_iso(normalized_created))
        normalized_payload = json.dumps(payload or {}, separators=(",", ":"), sort_keys=True)
        normalized_instance = str(bot_instance_id or self._bot_instance_id or "unknown")

        cursor = self.conn.execute(
            """
            INSERT INTO persisted_events (
                event_type, trading_day, symbol, setup_id, ticket, bot_instance_id, created_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event_type),
                normalized_day,
                str(symbol),
                str(setup_id) if setup_id is not None else None,
                int(ticket) if ticket is not None else None,
                normalized_instance,
                normalized_created,
                normalized_payload,
            ),
        )
        self._maybe_commit()

        return PersistedEventRecord(
            event_type=str(event_type),
            trading_day=normalized_day,
            symbol=str(symbol),
            setup_id=str(setup_id) if setup_id is not None else None,
            ticket=int(ticket) if ticket is not None else None,
            bot_instance_id=normalized_instance,
            created_at_utc=normalized_created,
            payload_json=normalized_payload,
            event_id=int(cursor.lastrowid or 0),
        )

    def list_events(
        self,
        event_type: Optional[str] = None,
        symbol: Optional[str] = None,
        trading_day: Optional[str] = None,
    ) -> List[PersistedEventRecord]:
        params = []
        where_parts = []
        if event_type is not None:
            where_parts.append("event_type = ?")
            params.append(event_type)
        if symbol is not None:
            where_parts.append("symbol = ?")
            params.append(symbol)
        if trading_day is not None:
            where_parts.append("trading_day = ?")
            params.append(trading_day)

        query = "SELECT * FROM persisted_events"
        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)
        query += " ORDER BY event_id ASC"

        rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_events_before_day(self, cutoff_trading_day: str, limit: int = 5000) -> List[PersistedEventRecord]:
        rows = self.conn.execute(
            """
            SELECT * FROM persisted_events
            WHERE trading_day < ?
            ORDER BY event_id ASC
            LIMIT ?
            """,
            (str(cutoff_trading_day), max(1, int(limit))),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def delete_events_by_ids(self, event_ids: List[int]) -> int:
        ids = [int(item) for item in event_ids if int(item) > 0]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        cursor = self.conn.execute(
            f"DELETE FROM persisted_events WHERE event_id IN ({placeholders})",
            tuple(ids),
        )
        self._maybe_commit()
        return int(cursor.rowcount or 0)

    def count_events(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS cnt FROM persisted_events").fetchone()
        return int(row["cnt"] if row is not None else 0)

    def vacuum(self) -> None:
        if self._tx_depth != 0:
            raise RuntimeError("VACUUM cannot run inside an active transaction.")
        self.conn.execute("VACUUM")
