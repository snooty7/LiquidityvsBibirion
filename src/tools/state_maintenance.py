from __future__ import annotations

import argparse
from datetime import datetime, timezone

from src.persistence.maintenance import archive_and_prune_events
from src.persistence.repository import SQLiteRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="State DB maintenance tool")
    parser.add_argument("--db-path", required=True, help="Path to bot SQLite DB")
    parser.add_argument("--retention-days", type=int, default=30, help="Event retention window in UTC trading days")
    parser.add_argument("--archive-dir", default="state_archives", help="Directory for archived event JSONL batches")
    parser.add_argument("--batch-size", type=int, default=5000, help="Max events per archival batch")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--vacuum", action="store_true", help="Run VACUUM after retention")
    args = parser.parse_args()

    repo = SQLiteRepository(args.db_path)
    repo.set_bot_instance_id("maintenance_cli")
    try:
        before = repo.count_events()
        result = archive_and_prune_events(
            repo=repo,
            now_utc=datetime.now(timezone.utc),
            retention_days=args.retention_days,
            archive_dir=args.archive_dir,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        after = repo.count_events()
        print(
            f"retention cutoff_day={result.cutoff_trading_day} archived={result.archived_count} "
            f"deleted={result.deleted_count} dry_run={result.dry_run}"
        )
        if result.archive_file:
            print(f"archive_file={result.archive_file}")
        print(f"events_before={before} events_after={after}")

        if args.vacuum and not args.dry_run:
            repo.vacuum()
            print("vacuum=done")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
