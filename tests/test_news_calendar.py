from datetime import datetime, timezone
from types import SimpleNamespace

from src.services.news_calendar import NewsCalendar, NewsEvent, symbol_currencies


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        news_filter_enabled=True,
        news_provider="investpy",
        news_cache_path="news_test_cache.json",
        news_refresh_interval_sec=1800,
        news_timezone="Europe/Sofia",
        news_block_minutes_before=30,
        news_block_minutes_after=15,
        news_blocked_importances=("high", "medium"),
    )


def test_symbol_currencies_for_fx_pair() -> None:
    assert symbol_currencies("GBPUSD") == {"GBP", "USD"}


def test_blackout_reason_matches_symbol_currency_and_window(tmp_path) -> None:
    runtime = _runtime()
    runtime.news_cache_path = str(tmp_path / "cache.json")
    calendar = NewsCalendar(runtime)
    calendar.events = [
        NewsEvent(
            starts_at_utc="2026-04-13T12:30:00+00:00",
            currency="USD",
            importance="high",
            event="CPI",
        )
    ]

    reason = calendar.blackout_reason("GBPUSD", datetime(2026, 4, 13, 12, 10, tzinfo=timezone.utc))

    assert reason is not None
    assert "USD" in reason
    assert "CPI" in reason


def test_blackout_reason_ignores_low_importance(tmp_path) -> None:
    runtime = _runtime()
    runtime.news_cache_path = str(tmp_path / "cache.json")
    calendar = NewsCalendar(runtime)
    calendar.events = [
        NewsEvent(
            starts_at_utc="2026-04-13T12:30:00+00:00",
            currency="USD",
            importance="low",
            event="Minor Release",
        )
    ]

    reason = calendar.blackout_reason("GBPUSD", datetime(2026, 4, 13, 12, 10, tzinfo=timezone.utc))

    assert reason is None
