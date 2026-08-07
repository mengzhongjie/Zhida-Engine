from datetime import date, datetime, timezone

from app.core.time import as_beijing, utc_day_range, utc_day_start


def test_beijing_day_start_maps_to_previous_utc_afternoon():
    assert utc_day_start(date(2026, 8, 7)) == datetime(2026, 8, 6, 16, 0)


def test_beijing_date_range_is_a_full_utc_day_window():
    start, end = utc_day_range(date(2026, 8, 7), date(2026, 8, 7))
    assert start == datetime(2026, 8, 6, 16, 0)
    assert end == datetime(2026, 8, 7, 16, 0)


def test_legacy_naive_utc_timestamp_is_serialized_as_beijing_time():
    result = as_beijing(datetime(2026, 8, 7, 8, 9, 8))
    assert result == datetime(2026, 8, 7, 16, 9, 8, tzinfo=result.tzinfo)
    assert result.utcoffset().total_seconds() == 8 * 3600


def test_aware_utc_timestamp_is_serialized_as_beijing_time():
    result = as_beijing(datetime(2026, 8, 7, 8, 9, 8, tzinfo=timezone.utc))
    assert result.hour == 16
