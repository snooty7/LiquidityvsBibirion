from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import json
import urllib.request
from zoneinfo import ZoneInfo


OPEN_EVENTS = {
    "TRADE_OK",
}

CLOSE_EVENTS = {
    "RISK_CLOSE_OK",
    "DAILY_LOSS_CLOSE_OK",
    "POSITION_CLOSED_BROKER",
    "POSITION_CLOSED_UNCONFIRMED",
}

NOTIFIABLE_EVENTS = OPEN_EVENTS | CLOSE_EVENTS


def should_notify(event_type: str) -> bool:
    return str(event_type) in NOTIFIABLE_EVENTS


def _fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{float(value):.5f}"


def _payload_value(payload: dict[str, Any], key: str) -> Optional[float]:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return float(value)


def _first_payload_value(payload: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = _payload_value(payload, key)
        if value is not None:
            return value
    return None


def _fmt_money(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):+.2f}"


def _fmt_local_time(value: str) -> str:
    ts = datetime.fromisoformat(str(value)).astimezone(ZoneInfo("Europe/Sofia"))
    return ts.strftime("%Y-%m-%d %H:%M:%S %Z")


def build_push_message(
    *,
    event_type: str,
    symbol: str,
    ticket: Optional[int],
    setup_id: Optional[str],
    created_at_utc: str,
    payload: Optional[dict[str, Any]],
) -> tuple[str, str, str]:
    data = dict(payload or {})
    side = str(data.get("side", "")).upper() or "-"
    title = f"{event_type} {symbol}".strip()
    tags = "chart_with_upwards_trend"
    entry_value = _first_payload_value(data, "price", "level")
    exit_value = _first_payload_value(data, "exit_price", "close_price", "price", "level")
    sl_value = _first_payload_value(data, "sl", "to_sl")
    tp_value = _first_payload_value(data, "tp", "to_tp")
    realized_pnl = _first_payload_value(data, "realized_pnl", "pnl", "profit")
    trailing_value = str(data.get("trailing", "") or "-")
    result_value = "-"
    if realized_pnl is not None:
        if realized_pnl > 0:
            result_value = "profit"
        elif realized_pnl < 0:
            result_value = "loss"
        else:
            result_value = "breakeven"

    lines = [
        f"event: {event_type}",
        f"symbol: {symbol}",
        f"side: {side}",
        f"time: {_fmt_local_time(created_at_utc)}",
        f"sl: {_fmt_price(sl_value)}",
        f"tp: {_fmt_price(tp_value)}",
        f"trailing: {trailing_value}",
    ]

    if event_type in OPEN_EVENTS:
        lines.insert(4, f"entry: {_fmt_price(entry_value)}")
        title = f"OPEN {symbol} {side}"
        tags = "white_check_mark,chart_with_downwards_trend" if side == "SELL" else "white_check_mark,chart_with_upwards_trend"
    elif event_type in CLOSE_EVENTS:
        lines.insert(4, f"exit: {_fmt_price(exit_value)}")
        lines.append(f"pnl: {_fmt_money(realized_pnl)}")
        lines.append(f"result: {result_value}")
        title = f"CLOSE {symbol} {side}"
        tags = "money_with_wings" if realized_pnl is None or realized_pnl >= 0 else "x"
    elif event_type == "LIQUIDITY_ALERT":
        lines.insert(4, f"entry: {_fmt_price(entry_value)}")
        title = f"ALERT {symbol} {side}"
        tags = "rotating_light"
    else:
        lines.insert(4, f"entry: {_fmt_price(entry_value)}")

    message = "\n".join(lines)
    return title, message, tags


def send_push_notification(
    runtime_config: Any,
    *,
    event_type: str,
    symbol: str,
    ticket: Optional[int],
    setup_id: Optional[str],
    created_at_utc: Optional[str],
    payload: Optional[dict[str, Any]],
) -> bool:
    if not bool(getattr(runtime_config, "push_notifications_enabled", False)):
        return False
    if not should_notify(event_type):
        return False

    push_url = str(getattr(runtime_config, "push_notification_url", "") or "").strip()
    if not push_url:
        return False

    ts = created_at_utc or datetime.now(timezone.utc).isoformat()
    title, message, tags = build_push_message(
        event_type=event_type,
        symbol=symbol,
        ticket=ticket,
        setup_id=setup_id,
        created_at_utc=ts,
        payload=payload,
    )

    headers = {
        "Title": title,
        "Tags": tags,
        "Content-Type": "text/plain; charset=utf-8",
        "X-Bot-Event": str(event_type),
        "X-Bot-Payload": json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=True),
    }
    token = str(getattr(runtime_config, "push_notification_token", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(
        push_url,
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = int(getattr(runtime_config, "push_notification_timeout_sec", 5))
    with urllib.request.urlopen(request, timeout=timeout):
        return True
