from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import json
import urllib.request


NOTIFIABLE_EVENTS = {
    "TRADE_OK",
    "TRADE_FAIL",
    "RISK_CLOSE_OK",
    "RISK_CLOSE_FAIL",
    "POSITION_CLOSED_BROKER",
    "POSITION_CLOSED_UNCONFIRMED",
}


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

    lines = [
        f"event: {event_type}",
        f"symbol: {symbol}",
        f"side: {side}",
        f"time_utc: {created_at_utc}",
    ]
    if ticket is not None:
        lines.append(f"ticket: {ticket}")
    if setup_id:
        lines.append(f"setup_id: {setup_id}")

    if event_type == "TRADE_OK":
        title = f"OPEN {symbol} {side}"
        tags = "white_check_mark,chart_with_downwards_trend" if side == "SELL" else "white_check_mark,chart_with_upwards_trend"
        lines.extend(
            [
                f"volume: {data.get('volume', '-')}",
                f"entry: {_fmt_price(_payload_value(data, 'price'))}",
                f"sl: {_fmt_price(_payload_value(data, 'sl'))}",
                f"tp: {_fmt_price(_payload_value(data, 'tp'))}",
                f"retcode: {data.get('retcode', '-')}",
            ]
        )
    elif event_type in {"RISK_CLOSE_OK", "POSITION_CLOSED_BROKER", "POSITION_CLOSED_UNCONFIRMED"}:
        title = f"CLOSE {symbol} {side}"
        tags = "money_with_wings"
        lines.extend(
            [
                f"close: {_fmt_price(_payload_value(data, 'price') or _payload_value(data, 'close_price'))}",
                f"pnl: {data.get('realized_pnl', data.get('message', '-'))}",
                f"reason: {data.get('close_reason', data.get('message', '-'))}",
            ]
        )
    elif event_type in {"TRADE_FAIL", "RISK_CLOSE_FAIL"}:
        title = f"FAIL {symbol} {side}"
        tags = "warning"
        lines.extend(
            [
                f"price: {_fmt_price(_payload_value(data, 'price'))}",
                f"reason: {data.get('message', '-')}",
                f"retcode: {data.get('retcode', '-')}",
            ]
        )

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
