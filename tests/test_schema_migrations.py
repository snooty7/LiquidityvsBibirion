from __future__ import annotations

from pathlib import Path
import sqlite3

from src.persistence.db import CURRENT_SCHEMA_VERSION, get_connection, init_schema


def _user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0] if row is not None else 0)


def test_fresh_init_sets_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    conn = get_connection(str(db_path))
    try:
        init_schema(conn)
        assert _user_version(conn) == CURRENT_SCHEMA_VERSION
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "persisted_events" in tables
        assert "schema_migrations" in tables
    finally:
        conn.close()


def test_legacy_unversioned_db_migrates_to_current(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute(
            """
            CREATE TABLE risk_close_retry (
                ticket INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                retry_after REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        raw.commit()
    finally:
        raw.close()

    conn = get_connection(str(db_path))
    try:
        init_schema(conn)
        assert _user_version(conn) == CURRENT_SCHEMA_VERSION
        cols = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(risk_close_retry)").fetchall()
        }
        assert "reason" in cols
        assert "attempts" in cols
        assert "last_error" in cols
        migration_rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        assert int(migration_rows[-1]["version"]) == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


def test_unsupported_schema_version_fails_loudly(tmp_path: Path) -> None:
    db_path = tmp_path / "future.db"
    conn = get_connection(str(db_path))
    try:
        conn.execute("PRAGMA user_version = 999")
        conn.commit()
        try:
            init_schema(conn)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Expected RuntimeError for unsupported schema version.")
    finally:
        conn.close()
