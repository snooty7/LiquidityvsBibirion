from __future__ import annotations

from datetime import datetime, timezone

from dashboard.data import event_rows_for_symbol, timeframe_markers


def test_timeframe_markers_filters_symbol_and_builds_buy_marker() -> None:
    rows = [
        {
            "ts": "2026-04-06T05:20:00+00:00",
            "symbol": "EURUSD",
            "timeframe": "M5",
            "event": "LIQUIDITY_ALERT",
            "side": "BUY",
            "level": "1.1500",
            "message": "setup_id=abc",
        },
        {
            "ts": "2026-04-06T05:21:00+00:00",
            "symbol": "GBPUSD",
            "timeframe": "M5",
            "event": "LIQUIDITY_ALERT",
            "side": "SELL",
            "level": "1.2500",
            "message": "setup_id=def",
        },
    ]

    filtered = event_rows_for_symbol(rows, "EURUSD")
    markers = timeframe_markers(
        filtered,
        timeframe="M5",
        start_utc=datetime(2026, 4, 6, 5, 0, tzinfo=timezone.utc),
        end_utc=datetime(2026, 4, 6, 6, 0, tzinfo=timezone.utc),
    )

    assert len(markers) == 1
    assert markers[0]["position"] == "belowBar"
    assert markers[0]["shape"] == "circle"
    assert markers[0]["setupId"] == "abc"
