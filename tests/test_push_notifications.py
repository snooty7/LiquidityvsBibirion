from types import SimpleNamespace

from src.notifications.push import build_push_message, send_push_notification


def test_build_push_message_for_trade_open() -> None:
    title, body, tags = build_push_message(
        event_type="TRADE_OK",
        symbol="EURUSD",
        ticket=12345,
        setup_id="setup-1",
        created_at_utc="2026-03-26T06:00:00+00:00",
        payload={
            "side": "SELL",
            "volume": 0.05,
            "price": 1.15574,
            "sl": 1.15674,
            "tp": 1.15374,
            "trailing": "r_multiple/1.00R/1.00R/remove_tp=True",
            "retcode": 10009,
        },
    )

    assert title == "OPEN EURUSD SELL"
    assert "event: TRADE_OK" in body
    assert "time: 2026-03-26 08:00:00 EET" in body
    assert "entry: 1.15574" in body
    assert "sl: 1.15674" in body
    assert "tp: 1.15374" in body
    assert "trailing: r_multiple/1.00R/1.00R/remove_tp=True" in body
    assert "white_check_mark" in tags


def test_build_push_message_for_close() -> None:
    title, body, tags = build_push_message(
        event_type="POSITION_CLOSED_BROKER",
        symbol="EURUSD",
        ticket=12345,
        setup_id=None,
        created_at_utc="2026-03-26T08:59:48+00:00",
        payload={
            "side": "SELL",
            "close_price": 1.15674,
            "realized_pnl": -4.32,
            "close_reason": "broker_side_close_detected",
        },
    )

    assert title == "CLOSE EURUSD SELL"
    assert "event: POSITION_CLOSED_BROKER" in body
    assert "time: 2026-03-26 10:59:48 EET" in body
    assert "entry: -" in body
    assert "sl: -" in body
    assert "tp: -" in body


def test_build_push_message_for_liquidity_alert() -> None:
    title, body, tags = build_push_message(
        event_type="LIQUIDITY_ALERT",
        symbol="EURUSD",
        ticket=None,
        setup_id="abc12345",
        created_at_utc="2026-04-02T07:00:00+00:00",
        payload={
            "side": "BUY",
            "level": 1.15314,
            "stage": "post_sweep_pre_confirmation",
            "what_next": "wait for displacement, then structure confirmation",
            "plan": "observe displacement -> BOS -> final filters -> possible entry",
            "sweep_note": "sweep_significant",
            "range_note": "range_ok",
        },
    )

    assert title == "ALERT EURUSD BUY"
    assert "event: LIQUIDITY_ALERT" in body
    assert "time: 2026-04-02 10:00:00 EEST" in body
    assert "entry: 1.15314" in body
    assert "rotating_light" in tags


def test_send_push_notification_posts_message(monkeypatch) -> None:
    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return DummyResponse()

    runtime = SimpleNamespace(
        push_notifications_enabled=True,
        push_notification_url="https://ntfy.sh/test-topic",
        push_notification_token="",
        push_notification_timeout_sec=5,
    )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    sent = send_push_notification(
        runtime,
        event_type="TRADE_OK",
        symbol="EURUSD",
        ticket=12345,
        setup_id="setup-1",
        created_at_utc="2026-03-26T06:00:00+00:00",
        payload={"side": "SELL", "price": 1.15574, "sl": 1.15674, "tp": 1.15374, "volume": 0.05, "trailing": "r_multiple/1.00R/1.00R/remove_tp=True"},
    )

    assert sent is True
    assert captured["url"] == "https://ntfy.sh/test-topic"
    assert "OPEN EURUSD SELL" in captured["headers"]["Title"]
    assert "entry: 1.15574" in captured["body"]
    assert "trailing: r_multiple/1.00R/1.00R/remove_tp=True" in captured["body"]
