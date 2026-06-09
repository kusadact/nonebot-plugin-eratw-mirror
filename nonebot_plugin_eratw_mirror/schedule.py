from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")
_WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


@dataclass(frozen=True)
class ScheduleSpec:
    raw: str
    trigger: str
    trigger_kwargs: dict[str, Any]
    description: str


def parse_schedule(value: str, timezone_name: str = "Asia/Shanghai") -> ScheduleSpec | None:
    raw = value.strip()
    if not raw:
        return None

    timezone = _parse_timezone(timezone_name)
    parts = [part.strip().lower() for part in raw.split("@")]
    kind = parts[0]

    if kind == "daily" and len(parts) == 2:
        hour, minute = _parse_time(parts[1])
        return ScheduleSpec(
            raw=raw,
            trigger="cron",
            trigger_kwargs={"hour": hour, "minute": minute, "timezone": timezone},
            description=f"daily at {_format_time(hour, minute)} ({timezone_name})",
        )

    if kind == "weekly" and len(parts) == 3:
        weekdays = _parse_weekdays(parts[1])
        hour, minute = _parse_time(parts[2])
        return ScheduleSpec(
            raw=raw,
            trigger="cron",
            trigger_kwargs={
                "day_of_week": ",".join(weekdays),
                "hour": hour,
                "minute": minute,
                "timezone": timezone,
            },
            description=(
                f"weekly on {','.join(weekdays)} at {_format_time(hour, minute)} "
                f"({timezone_name})"
            ),
        )

    if kind == "interval_days" and len(parts) == 3:
        days = _parse_days(parts[1])
        hour, minute = _parse_time(parts[2])
        start_date = _next_start_date(hour, minute, timezone)
        return ScheduleSpec(
            raw=raw,
            trigger="interval",
            trigger_kwargs={
                "days": days,
                "start_date": start_date,
                "timezone": timezone,
            },
            description=(
                f"every {days} day(s) at {_format_time(hour, minute)} "
                f"starting {start_date.isoformat(timespec='minutes')}"
            ),
        )

    raise ValueError(
        "Invalid eratw_schedule. Use daily@HH:MM, weekly@mon,thu@HH:MM, "
        "or interval_days@N@HH:MM."
    )


def _parse_time(value: str) -> tuple[int, int]:
    match = _TIME_PATTERN.match(value)
    if not match:
        raise ValueError(f"Invalid schedule time: {value!r}. Use HH:MM.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid schedule time: {value!r}. Use 00:00-23:59.")
    return hour, minute


def _parse_weekdays(value: str) -> list[str]:
    weekdays = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not weekdays:
        raise ValueError("weekly schedule requires at least one weekday.")
    invalid = [item for item in weekdays if item not in _WEEKDAYS]
    if invalid:
        raise ValueError(f"Invalid weekday(s): {', '.join(invalid)}.")
    return weekdays


def _parse_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid interval day count: {value!r}.") from exc
    if days <= 0:
        raise ValueError("interval_days must be greater than 0.")
    return days


def _parse_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid eratw_schedule_timezone: {value!r}.") from exc


def _next_start_date(hour: int, minute: int, timezone: ZoneInfo) -> datetime:
    now = datetime.now(timezone)
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)
    return start


def _format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"
