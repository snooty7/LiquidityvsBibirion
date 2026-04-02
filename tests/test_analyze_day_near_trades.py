from __future__ import annotations

from datetime import date

from src.tools.analyze_day_near_trades import _build_timeline, _local_day_bounds_utc


def _row(**kwargs) -> dict:
    return dict(kwargs)


def test_local_day_bounds_utc_handles_sofia_offset() -> None:
    start_utc, end_utc = _local_day_bounds_utc(date(2026, 4, 2), "Europe/Sofia")
    assert start_utc.isoformat() == "2026-04-01T21:00:00+00:00"
    assert end_utc.isoformat() == "2026-04-02T21:00:00+00:00"


def test_build_timeline_prefers_confirmed_anchor() -> None:
    setup_row = _row(
        setup_id="abc",
        status="CANCELED",
        created_at="2026-04-02T07:00:00+00:00",
        updated_at="2026-04-02T07:20:00+00:00",
        closed_reason="entry_blocked:SKIP_ORDER_BLOCK",
    )
    events = [
        _row(
            event_type="SETUP_PENDING",
            created_at_utc="2026-04-02T07:00:00+00:00",
        ),
        _row(
            event_type="SETUP_CONFIRMED",
            created_at_utc="2026-04-02T07:05:00+00:00",
        ),
    ]

    timeline = _build_timeline(setup_row, events)

    assert timeline.stage == "confirmed"
    assert timeline.anchor_reason == "confirmed"
    assert timeline.anchor_time_utc == "2026-04-02T07:05:00+00:00"
    assert timeline.canceled_reason == "entry_blocked:SKIP_ORDER_BLOCK"


def test_build_timeline_uses_pending_anchor_when_never_confirmed() -> None:
    setup_row = _row(
        setup_id="abc",
        status="EXPIRED",
        created_at="2026-04-02T08:00:00+00:00",
        updated_at="2026-04-02T08:15:00+00:00",
        closed_reason="expired_before_confirmation",
    )

    timeline = _build_timeline(setup_row, [])

    assert timeline.stage == "pending_only"
    assert timeline.anchor_reason == "pending_created"
    assert timeline.anchor_time_utc == "2026-04-02T08:00:00+00:00"
    assert timeline.canceled_reason == "expired_before_confirmation"
