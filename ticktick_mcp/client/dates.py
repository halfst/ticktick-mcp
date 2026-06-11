"""The all-day date contract (DESIGN.md §3) — the reason this project exists.

This module owns every conversion between Python date/datetime values and the v2
wire format. Field names and formats are confirmed against live v2 data (2026-06):
``dueDate`` like ``2026-09-15T00:00:00.000+0000`` (millisecond ``.SSS`` + basic
``+0000`` offset), plus ``isAllDay`` and an IANA ``timeZone``.

Rules:
- **All-day** (a ``date`` with no time) → encoded at **UTC midnight**, ``timeZone``
  ``"UTC"``. The date is then literally in the string and DST-proof.
- **Timed** (a ``datetime``) → made aware in its zone, converted to UTC.
- **Reading all-day** → convert the instant into the task's stored ``timeZone``,
  THEN take the date. App-created tasks store local-midnight-UTC, so skipping the
  conversion is an off-by-one bug for zones east of UTC.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import PayloadError

__all__ = [
    "ALL_DAY_TIMEZONE",
    "encode_all_day",
    "encode_timed",
    "encode_due",
    "decode_due",
    "format_wire",
    "parse_wire",
]

ALL_DAY_TIMEZONE = "UTC"


def _safe_zone(name: str | None) -> ZoneInfo:
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def format_wire(dt: datetime) -> str:
    """Format an aware datetime as the v2 wire string (UTC, ``.SSS+0000``)."""
    if dt.tzinfo is None:
        raise ValueError("format_wire requires a timezone-aware datetime.")
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}+0000"


def parse_wire(value: str) -> datetime:
    """Parse a v2 wire date string into an aware (UTC-offset) datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise PayloadError(f"Could not parse a TickTick date string: {value!r}.")


def encode_all_day(d: date) -> tuple[str, str, bool]:
    """Encode a date-only value → (dueDate, timeZone, isAllDay=True) at UTC midnight."""
    midnight_utc = datetime.combine(d, time(0, 0, 0), tzinfo=timezone.utc)
    return format_wire(midnight_utc), ALL_DAY_TIMEZONE, True


def encode_timed(dt: datetime, tz_name: str) -> tuple[str, str, bool]:
    """Encode a timed value → (dueDate, timeZone, isAllDay=False).

    A naive ``dt`` is interpreted in ``tz_name``; an aware ``dt`` keeps its own zone
    but is still reported under ``tz_name`` as the task's display zone.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_safe_zone(tz_name))
    return format_wire(dt), tz_name, False


def encode_due(due: date | datetime, default_tz: str) -> tuple[str, str, bool]:
    """Dispatch on Python type: ``datetime`` ⇒ timed, bare ``date`` ⇒ all-day.

    ``datetime`` is a subclass of ``date``, so the order of these checks matters.
    """
    if isinstance(due, datetime):
        return encode_timed(due, default_tz)
    if isinstance(due, date):
        return encode_all_day(due)
    raise TypeError(f"due must be a date or datetime, got {type(due).__name__}.")


def decode_due(
    due_str: str | None, is_all_day: bool, tz_name: str | None
) -> date | datetime | None:
    """Decode a wire ``dueDate`` back to a ``date`` (all-day) or aware ``datetime``."""
    if not due_str:
        return None
    instant = parse_wire(due_str)
    if is_all_day:
        # Convert into the task's stored zone, THEN take the date (DESIGN.md §3).
        return instant.astimezone(_safe_zone(tz_name)).date()
    return instant.astimezone(_safe_zone(tz_name))
