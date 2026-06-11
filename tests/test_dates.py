"""The all-day date contract (DESIGN.md §3) — unit tests, no network.

The two cases that matter most: all-day encodes to UTC midnight, and all-day
*reads* convert through the stored timezone (so a zone east of UTC doesn't go
off-by-one).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from ticktick_mcp.client.dates import (
    decode_due,
    encode_all_day,
    encode_due,
    encode_timed,
    format_wire,
    parse_wire,
)


def test_all_day_encodes_to_utc_midnight() -> None:
    due_str, tz, is_all_day = encode_all_day(date(2026, 9, 15))
    assert due_str == "2026-09-15T00:00:00.000+0000"
    assert tz == "UTC"
    assert is_all_day is True


def test_encode_due_dispatches_on_type() -> None:
    # bare date -> all-day
    assert encode_due(date(2026, 9, 15), "America/Chicago")[2] is True
    # datetime -> timed (datetime is a subclass of date; order must be right)
    assert encode_due(datetime(2026, 9, 15, 9, 0), "America/Chicago")[2] is False


def test_timed_naive_is_interpreted_in_given_zone() -> None:
    # 14:30 Chicago (CDT, UTC-5) -> 19:30Z
    due_str, tz, is_all_day = encode_timed(datetime(2026, 9, 15, 14, 30), "America/Chicago")
    assert due_str == "2026-09-15T19:30:00.000+0000"
    assert tz == "America/Chicago"
    assert is_all_day is False


def test_timed_aware_is_converted_to_utc() -> None:
    dt = datetime(2026, 9, 15, 14, 30, tzinfo=ZoneInfo("America/Chicago"))
    due_str, _, _ = encode_timed(dt, "UTC")
    assert due_str == "2026-09-15T19:30:00.000+0000"


def test_all_day_round_trips_for_any_zone() -> None:
    d = date(2026, 9, 15)
    due_str, tz, _ = encode_all_day(d)
    assert decode_due(due_str, True, tz) == d


def test_all_day_read_uses_stored_zone_west_of_utc() -> None:
    # App-created Chicago all-day July 1 is stored as local-midnight-UTC.
    assert decode_due("2026-07-01T05:00:00.000+0000", True, "America/Chicago") == date(2026, 7, 1)


def test_all_day_read_uses_stored_zone_east_of_utc() -> None:
    # The off-by-one guard: Tokyo (UTC+9) all-day July 1 -> 2026-06-30T15:00Z.
    # Naive UTC-date would wrongly give June 30; converting via zone gives July 1.
    assert decode_due("2026-06-30T15:00:00.000+0000", True, "Asia/Tokyo") == date(2026, 7, 1)


def test_timed_read_returns_aware_datetime_in_zone() -> None:
    got = decode_due("2026-09-15T19:30:00.000+0000", False, "America/Chicago")
    assert isinstance(got, datetime)
    assert got == datetime(2026, 9, 15, 14, 30, tzinfo=ZoneInfo("America/Chicago"))


def test_format_parse_wire_round_trip() -> None:
    dt = datetime(2026, 9, 15, 19, 30, 0, tzinfo=timezone.utc)
    assert parse_wire(format_wire(dt)) == dt


def test_parse_wire_tolerates_missing_millis() -> None:
    assert parse_wire("2026-09-15T19:30:00+0000") == datetime(
        2026, 9, 15, 19, 30, tzinfo=timezone.utc
    )


def test_unknown_timezone_falls_back_to_utc_without_crashing() -> None:
    # A drifted/garbage zone name must not raise; date still recovers under UTC.
    assert decode_due("2026-09-15T00:00:00.000+0000", True, "Not/AZone") == date(2026, 9, 15)
