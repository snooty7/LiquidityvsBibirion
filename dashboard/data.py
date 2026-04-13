from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import csv
from pathlib import Path
from typing import Iterable


TIMEFRAME_WINDOWS = {
    "M1": timedelta(hours=8),
    "M5": timedelta(days=2),
    "M15": timedelta(days=5),
    "M30": timedelta(days=10),
}

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
}


EVENT_STYLES = {
    "LIQUIDITY_ALERT": {"color": "#45d6ff", "label": "A", "line_color": "#45d6ff66"},
    "SETUP_PENDING": {"color": "#ffbd59", "label": "P", "line_color": "#ffbd5966"},
    "SETUP_WAIT": {"color": "#b38bff", "label": "W", "line_color": "#b38bff55"},
    "SETUP_CONFIRMED": {"color": "#59f2a7", "label": "C", "line_color": "#59f2a766"},
    "TRADE_OK": {"color": "#00e676", "label": "IN", "line_color": "#00e67688"},
    "RISK_CLOSE_OK": {"color": "#ffd166", "label": "OUT", "line_color": "#ffd16688"},
    "POSITION_CLOSED_BROKER": {"color": "#ffd166", "label": "OUT", "line_color": "#ffd16688"},
    "POSITION_CLOSED_UNCONFIRMED": {"color": "#ff8a80", "label": "U", "line_color": "#ff8a8088"},
    "STALE_PENDING_CANCELED": {"color": "#8d99ae", "label": "X", "line_color": "#8d99ae66"},
    "SKIP_BIAS": {"color": "#ef476f", "label": "B", "line_color": "#ef476f55"},
    "SKIP_SESSION": {"color": "#f78c6b", "label": "S", "line_color": "#f78c6b55"},
}


def _tail_lines(path: Path, limit: int) -> list[str]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        head = handle.readline()
        if not head:
            return []
        tail = deque(handle, maxlen=max(1, int(limit)))
    return [head.rstrip("\n")] + [line.rstrip("\n") for line in tail]


def load_recent_event_rows(csv_path: Path, limit: int = 4000) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    lines = _tail_lines(csv_path, limit)
    if len(lines) <= 1:
        return []
    reader = csv.DictReader(lines)
    return [dict(row) for row in reader]


def parse_ts(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def event_rows_for_symbol(rows: Iterable[dict[str, str]], symbol: str) -> list[dict[str, str]]:
    target = symbol.upper()
    result: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("symbol", "")).upper() != target:
            continue
        event_type = str(row.get("event", "")).strip()
        if event_type not in EVENT_STYLES:
            continue
        result.append(row)
    return result


def timeframe_markers(
    rows: Iterable[dict[str, str]],
    *,
    timeframe: str,
    start_utc: datetime,
    end_utc: datetime,
    match_timeframe_only: bool = True,
) -> list[dict]:
    markers: list[dict] = []
    tf = timeframe.upper()
    for row in rows:
        row_tf = str(row.get("timeframe", "")).upper()
        if match_timeframe_only and row_tf and row_tf != tf:
            continue

        event_type = str(row.get("event", "")).strip()
        style = EVENT_STYLES.get(event_type)
        if style is None:
            continue

        ts = parse_ts(row.get("ts", ""))
        if ts is None or ts < start_utc or ts > end_utc:
            continue

        side = str(row.get("side", "")).upper()
        price_raw = row.get("price") or row.get("level") or row.get("sl") or ""
        try:
            price = float(price_raw) if price_raw not in ("", None) else None
        except ValueError:
            price = None

        position = "belowBar" if side == "BUY" else "aboveBar"
        shape = "circle"

        markers.append(
            {
                "time": int(ts.timestamp()),
                "position": position,
                "shape": shape,
                "color": style["color"],
                "text": style["label"],
                "size": 0.7,
                "event": event_type,
                "price": price,
                "lineColor": style["line_color"],
                "message": str(row.get("message", "")).strip(),
                "setupId": _extract_token(str(row.get("message", "")), "setup_id="),
            }
        )
    return markers


def _extract_token(message: str, prefix: str) -> str | None:
    for part in str(message or "").split():
        if part.startswith(prefix):
            return part[len(prefix) :].strip()
    return None


def recent_signal_cards(rows: Iterable[dict[str, str]], limit: int = 12) -> list[dict]:
    cards: list[dict] = []
    for row in reversed(list(rows)):
        event_type = str(row.get("event", "")).strip()
        style = EVENT_STYLES.get(event_type)
        if style is None:
            continue
        ts = parse_ts(row.get("ts", ""))
        if ts is None:
            continue
        cards.append(
            {
                "ts": ts.isoformat(),
                "symbol": str(row.get("symbol", "")),
                "timeframe": str(row.get("timeframe", "")),
                "event": event_type,
                "side": str(row.get("side", "")),
                "level": str(row.get("level", "")),
                "message": str(row.get("message", "")).strip(),
                "color": style["color"],
            }
        )
        if len(cards) >= limit:
            break
    return cards


def bars_for_window(timeframe: str) -> int:
    tf = timeframe.upper()
    window = TIMEFRAME_WINDOWS[tf]
    seconds = TIMEFRAME_SECONDS[tf]
    return max(50, int(window.total_seconds() // seconds) + 2)
