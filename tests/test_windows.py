"""Tests for the automatic leaderboard-window selection."""

from datetime import date

from app.config import DateRange, SegmentConfig
from app.windows import presets_for_segment, window_presets

# Anchor "today" to a known weekday: 2026-07-15 is a Wednesday.
_WED = date(2026, 7, 15)


def test_single_day_period_today_uses_only_today() -> None:
    assert window_presets(_WED, _WED, _WED) == [DateRange.TODAY]


def test_wide_period_stops_at_the_preset_that_covers_its_start() -> None:
    # Period starts July 1, today July 15: this_month's window starts July 1 and covers
    # the start, so it stops there without needing this_year.
    presets = window_presets(date(2026, 7, 1), date(2026, 8, 15), _WED)
    assert presets == [
        DateRange.TODAY,
        DateRange.THIS_WEEK,
        DateRange.THIS_MONTH,
    ]


def test_period_starting_before_this_month_climbs_to_this_year() -> None:
    # Start June 15 is before July 1, so this_month can't reach it: climb to this_year.
    presets = window_presets(date(2026, 6, 15), date(2026, 8, 15), _WED)
    assert presets == [
        DateRange.TODAY,
        DateRange.THIS_WEEK,
        DateRange.THIS_MONTH,
        DateRange.THIS_YEAR,
    ]


def test_finished_period_drops_today_but_keeps_reaching_windows() -> None:
    # Period ended last week; today is not in it, but this_month still reaches back.
    presets = window_presets(date(2026, 7, 1), date(2026, 7, 8), _WED)
    assert DateRange.TODAY not in presets
    assert DateRange.THIS_WEEK not in presets  # week starts Mon 13th, after the 8th
    assert presets == [DateRange.THIS_MONTH]


def test_period_in_the_future_scrapes_nothing() -> None:
    assert window_presets(date(2026, 8, 1), date(2026, 8, 5), _WED) == []


def test_no_bounds_scrapes_only_all_time() -> None:
    assert window_presets(None, None, _WED) == [DateRange.ALL_TIME]


def test_open_ended_period_still_narrows_from_today() -> None:
    # Open end, start today: only today's window is needed.
    assert window_presets(_WED, None, _WED) == [DateRange.TODAY]


def test_open_start_reaches_back_with_wider_windows() -> None:
    presets = window_presets(None, date(2026, 7, 8), _WED)
    # No today (period ended), climbs to all_time to cover the open start.
    assert presets[-1] == DateRange.ALL_TIME
    assert DateRange.TODAY not in presets


def test_explicit_preset_overrides_auto_selection() -> None:
    segment = SegmentConfig("1", date_range=DateRange.THIS_WEEK)
    assert presets_for_segment(segment, _WED, _WED, _WED) == [DateRange.THIS_WEEK]


def test_default_segment_uses_auto_selection() -> None:
    segment = SegmentConfig("1", date_range=DateRange.DEFAULT)
    assert presets_for_segment(segment, _WED, _WED, _WED) == [DateRange.TODAY]
