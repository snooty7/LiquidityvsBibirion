from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Optional

from src.persistence.models import PersistedEventRecord
from src.persistence.repository import SQLiteRepository


@dataclass(frozen=True)
class EventRetentionResult:
    cutoff_trading_day: str
    archived_count: int
    deleted_count: int
    archive_file: Optional[str]
    dry_run: bool


def compute_retention_cutoff_day(now_utc: datetime, retention_days: int) -> str:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware.")
    cutoff_dt = now_utc.astimezone(timezone.utc) - timedelta(days=max(1, int(retention_days)))
    return cutoff_dt.strftime("%Y-%m-%d")


def _archive_path(base_dir: str, cutoff_day: str, now_utc: datetime) -> Path:
    stamp = now_utc.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(base_dir)
    return base / cutoff_day / f"events_archive_{stamp}.jsonl"


def _write_archive_file(path: Path, events: list[PersistedEventRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(
                json.dumps(
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "trading_day": event.trading_day,
                        "symbol": event.symbol,
                        "setup_id": event.setup_id,
                        "ticket": event.ticket,
                        "bot_instance_id": event.bot_instance_id,
                        "created_at_utc": event.created_at_utc,
                        "payload_json": event.payload_json,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            handle.write("\n")


def archive_and_prune_events(
    repo: SQLiteRepository,
    now_utc: datetime,
    retention_days: int,
    archive_dir: str,
    *,
    batch_size: int = 5000,
    dry_run: bool = False,
) -> EventRetentionResult:
    cutoff_day = compute_retention_cutoff_day(now_utc, retention_days)
    events = repo.list_events_before_day(cutoff_day, limit=batch_size)
    if not events:
        return EventRetentionResult(
            cutoff_trading_day=cutoff_day,
            archived_count=0,
            deleted_count=0,
            archive_file=None,
            dry_run=dry_run,
        )

    archive_file = _archive_path(archive_dir, cutoff_day, now_utc)
    if dry_run:
        return EventRetentionResult(
            cutoff_trading_day=cutoff_day,
            archived_count=len(events),
            deleted_count=0,
            archive_file=str(archive_file),
            dry_run=True,
        )

    with repo.transaction():
        _write_archive_file(archive_file, events)
        deleted = repo.delete_events_by_ids([item.event_id for item in events])

    return EventRetentionResult(
        cutoff_trading_day=cutoff_day,
        archived_count=len(events),
        deleted_count=deleted,
        archive_file=str(archive_file),
        dry_run=False,
    )
