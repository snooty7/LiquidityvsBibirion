from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
from typing import Optional
from zoneinfo import ZoneInfo

try:
    import investpy
except Exception:  # pragma: no cover - optional dependency at runtime
    investpy = None


@dataclass(frozen=True)
class NewsEvent:
    starts_at_utc: str
    currency: str
    importance: str
    event: str
    source: str = "investpy"


def symbol_currencies(symbol: str) -> set[str]:
    normalized = str(symbol or "").upper()
    if len(normalized) >= 6 and normalized[:6].isalpha():
        return {normalized[:3], normalized[3:6]}
    if normalized in {"BTC", "ETH"}:
        return {"USD"}
    return set()


def _parse_calendar_time(date_raw: str, time_raw: str, local_tz: ZoneInfo) -> Optional[datetime]:
    date_text = str(date_raw or "").strip()
    time_text = str(time_raw or "").strip()
    if not date_text or not time_text or time_text.lower() in {"all day", "tentative"}:
        return None

    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M%p", "%d/%m/%Y %I:%M %p"):
        try:
            parsed = datetime.strptime(f"{date_text} {time_text}", fmt)
            return parsed.replace(tzinfo=local_tz)
        except ValueError:
            continue
    return None


class NewsCalendar:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.cache_path = Path(runtime.news_cache_path)
        self.local_tz = ZoneInfo(runtime.news_timezone)
        self.events: list[NewsEvent] = []
        self.last_refresh_utc: Optional[datetime] = None
        self.last_error: str = ""
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            raw_refresh = str(payload.get("last_refresh_utc") or "").strip()
            if raw_refresh:
                self.last_refresh_utc = datetime.fromisoformat(raw_refresh)
            self.events = [NewsEvent(**item) for item in payload.get("events", [])]
        except Exception as exc:
            print(f"[{datetime.now(timezone.utc).isoformat()}] NEWS_CACHE_LOAD_FAIL {exc}")

    def _write_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_refresh_utc": self.last_refresh_utc.isoformat() if self.last_refresh_utc else "",
            "events": [asdict(item) for item in self.events],
        }
        self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _fetch_events(self, now_utc: datetime) -> list[NewsEvent]:
        if investpy is None:
            raise RuntimeError("investpy is not installed")
        from_date = (now_utc.astimezone(self.local_tz).date() - timedelta(days=1)).strftime("%d/%m/%Y")
        to_date = (now_utc.astimezone(self.local_tz).date() + timedelta(days=7)).strftime("%d/%m/%Y")
        frame = investpy.news.economic_calendar(
            time_zone=None,
            importances=["high", "medium", "low"],
            from_date=from_date,
            to_date=to_date,
        )
        events: list[NewsEvent] = []
        for row in frame.to_dict("records"):
            importance = str(row.get("importance") or "").strip().lower()
            currency = str(row.get("currency") or "").strip().upper()
            if importance not in {"high", "medium", "low"} or len(currency) != 3:
                continue
            starts_local = _parse_calendar_time(str(row.get("date") or ""), str(row.get("time") or ""), self.local_tz)
            if starts_local is None:
                continue
            events.append(
                NewsEvent(
                    starts_at_utc=starts_local.astimezone(timezone.utc).isoformat(),
                    currency=currency,
                    importance=importance,
                    event=str(row.get("event") or "").strip(),
                )
            )
        return events

    def refresh_if_needed(self, now_utc: datetime) -> bool:
        if not self.runtime.news_filter_enabled:
            return False
        if self.last_refresh_utc is not None:
            age_sec = (now_utc - self.last_refresh_utc).total_seconds()
            if age_sec < float(self.runtime.news_refresh_interval_sec):
                return False
        try:
            self.events = self._fetch_events(now_utc)
            self.last_refresh_utc = now_utc
            self.last_error = ""
            self._write_cache()
            print(
                f"[{now_utc.isoformat()}] NEWS_REFRESH_OK provider={self.runtime.news_provider} "
                f"events={len(self.events)} cache={self.cache_path}"
            )
            return True
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[{now_utc.isoformat()}] NEWS_REFRESH_FAIL provider={self.runtime.news_provider} {exc}")
            return False

    def blackout_reason(self, symbol: str, now_utc: datetime) -> Optional[str]:
        if not self.runtime.news_filter_enabled:
            return None
        relevant = symbol_currencies(symbol)
        if not relevant:
            return None
        blocked = set(self.runtime.news_blocked_importances)
        before_min = int(self.runtime.news_block_minutes_before)
        after_min = int(self.runtime.news_block_minutes_after)
        matches: list[tuple[float, NewsEvent]] = []
        for item in self.events:
            if item.importance not in blocked or item.currency not in relevant:
                continue
            starts_at = datetime.fromisoformat(item.starts_at_utc)
            delta_min = (starts_at - now_utc).total_seconds() / 60.0
            if -after_min <= delta_min <= before_min:
                matches.append((abs(delta_min), item))
        if not matches:
            return None
        matches.sort(key=lambda pair: pair[0])
        event = matches[0][1]
        starts_local = datetime.fromisoformat(event.starts_at_utc).astimezone(self.local_tz)
        return (
            f"{event.importance}:{event.currency} {event.event} "
            f"at {starts_local.strftime('%Y-%m-%d %H:%M %Z')}"
        )
