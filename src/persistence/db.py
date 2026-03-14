from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3


DEFAULT_DB_PATH = "bot_state.sqlite3"
CURRENT_SCHEMA_VERSION = 2
LEGACY_UNVERSIONED_BASELINE = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column_def: str) -> None:
    column_name = column_def.split()[0]
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _user_tables_exist(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
          AND name != 'schema_migrations'
        """
    ).fetchone()
    return bool(int(row["cnt"] or 0))


def _get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0] if row is not None else 0)


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at_utc TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _record_migration(conn: sqlite3.Connection, version: int, notes: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO schema_migrations (version, applied_at_utc, notes)
        VALUES (?, ?, ?)
        """,
        (int(version), utc_now_iso(), notes),
    )


def _create_core_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pending_setups (
            setup_id TEXT PRIMARY KEY,
            dedupe_key TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            level REAL NOT NULL,
            candle_time INTEGER NOT NULL,
            signal_key TEXT NOT NULL,
            status TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            context_json TEXT NOT NULL,
            last_note TEXT NOT NULL DEFAULT '',
            executed_ticket INTEGER,
            closed_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pending_symbol_status
            ON pending_setups(symbol, status, expires_at);

        CREATE TABLE IF NOT EXISTS open_positions (
            ticket INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            magic INTEGER NOT NULL,
            setup_id TEXT,
            side TEXT NOT NULL,
            volume REAL NOT NULL,
            open_price REAL NOT NULL,
            sl REAL NOT NULL,
            tp REAL NOT NULL,
            comment TEXT NOT NULL DEFAULT '',
            opened_at INTEGER,
            status TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            closed_at TEXT,
            close_reason TEXT,
            FOREIGN KEY(setup_id) REFERENCES pending_setups(setup_id)
        );

        CREATE INDEX IF NOT EXISTS idx_open_positions_symbol_status
            ON open_positions(symbol, status);

        CREATE TABLE IF NOT EXISTS guard_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            day_key TEXT NOT NULL DEFAULT '',
            daily_realized_pnl REAL NOT NULL DEFAULT 0,
            daily_loss_reached INTEGER NOT NULL DEFAULT 0,
            daily_loss_announced INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS symbol_runtime_state (
            symbol TEXT PRIMARY KEY,
            timeframe TEXT NOT NULL,
            last_trade_ts REAL NOT NULL DEFAULT 0,
            cooldown_until REAL NOT NULL DEFAULT 0,
            entry_count INTEGER NOT NULL DEFAULT 0,
            last_processed_bar_time INTEGER NOT NULL DEFAULT 0,
            last_signal_key TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_close_retry (
            ticket INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            retry_after REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS persisted_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            trading_day TEXT NOT NULL,
            symbol TEXT NOT NULL,
            setup_id TEXT,
            ticket INTEGER,
            bot_instance_id TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_day_type
            ON persisted_events(trading_day, event_type, symbol);
        """
    )

    _ensure_column(conn, "risk_close_retry", "reason TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "risk_close_retry", "attempts INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "risk_close_retry", "last_error TEXT NOT NULL DEFAULT ''")


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    # V2 introduces persisted_events and explicit retry metadata columns.
    _create_core_tables(conn)


def init_schema(conn: sqlite3.Connection) -> None:
    current = _get_user_version(conn)
    _ensure_migrations_table(conn)

    if current > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported DB schema version {current}; runtime supports up to {CURRENT_SCHEMA_VERSION}."
        )

    if current == 0:
        if not _user_tables_exist(conn):
            _create_core_tables(conn)
            _set_user_version(conn, CURRENT_SCHEMA_VERSION)
            _record_migration(conn, CURRENT_SCHEMA_VERSION, "fresh_init")
            conn.commit()
            return

        # Legacy unversioned DB from prior releases.
        current = LEGACY_UNVERSIONED_BASELINE

    while current < CURRENT_SCHEMA_VERSION:
        next_version = current + 1
        if next_version == 2:
            _migrate_v1_to_v2(conn)
        else:
            raise RuntimeError(
                f"Unsupported schema migration path {current} -> {next_version}. "
                "Upgrade requires an explicit migration implementation."
            )
        current = next_version
        _set_user_version(conn, current)
        _record_migration(conn, current, f"migrated_to_v{current}")

    _create_core_tables(conn)
    conn.commit()
