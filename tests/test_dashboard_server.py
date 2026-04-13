from __future__ import annotations

from pathlib import Path

from dashboard.server import REPO_ROOT, resolve_runtime_path


def test_resolve_runtime_path_keeps_absolute_path() -> None:
    absolute = Path("I:/mt5_liquidity_codex_migration/live/combined_live_92001_92024/bot_events.csv").resolve()
    assert resolve_runtime_path(Path("I:/mt5_liquidity_codex_migration/config/settings.json"), str(absolute)) == absolute


def test_resolve_runtime_path_uses_repo_root_for_relative_runtime_path() -> None:
    config_path = Path("I:/mt5_liquidity_codex_migration/live/combined_live_92001_92024/settings.json")
    resolved = resolve_runtime_path(config_path, "live/combined_live_92001_92024/bot_events.csv")
    assert resolved == (REPO_ROOT / "live/combined_live_92001_92024/bot_events.csv").resolve()

