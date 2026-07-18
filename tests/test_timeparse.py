"""Tests for Strava time parsing and protocol time formatting."""

import pytest

from app.timeparse import format_time, parse_time


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("45", 45.0),
        ("5:23", 323.0),
        ("1:05:23", 3923.0),
        ("0:59", 59.0),
        ("  5:23  ", 323.0),
        ("5:23.4", 323.4),
        ("1:00:00.25", 3600.25),
    ],
)
def test_parse_time_valid(text: str, expected: float) -> None:
    assert parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "-", "n/a", "1:2:3:4", None])
def test_parse_time_invalid_returns_none(text: str | None) -> None:
    assert parse_time(text) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("seconds", "decimals", "expected"),
    [
        (323.0, 0, "5:23"),
        (3923.0, 0, "1:05:23"),
        (59.0, 0, "0:59"),
        (323.4, 1, "5:23.4"),
        (323.44, 2, "5:23.44"),
        (3600.0, 0, "1:00:00"),
        (5.0, 0, "0:05"),
    ],
)
def test_format_time(seconds: float, decimals: int, expected: str) -> None:
    assert format_time(seconds, decimals) == expected


def test_format_time_rounds_to_decimals() -> None:
    assert format_time(323.46, 1) == "5:23.5"


@pytest.mark.parametrize("seconds", [None, -1.0])
def test_format_time_missing_is_blank(seconds: float | None) -> None:
    assert format_time(seconds) == ""


def test_format_time_clamps_decimals() -> None:
    # More than four decimals is capped at four, like the generator.
    assert format_time(1.123456, 9) == "0:01.1235"


def test_parse_then_format_roundtrips() -> None:
    assert format_time(parse_time("1:05:23"), 0) == "1:05:23"


def test_format_time_force_hours_keeps_the_column_uniform() -> None:
    # Below an hour, force_hours still shows the (zero) hour field so a result column
    # does not mix "53:39" with "1:08:37".
    assert format_time(3219.0, force_hours=True) == "0:53:39"
    assert format_time(4117.0, force_hours=True) == "1:08:37"  # already past an hour
    assert format_time(40.0, force_hours=True) == "0:00:40"
    assert format_time(3219.5, 1, force_hours=True) == "0:53:39.5"
    # The default (used for gaps) stays compact.
    assert format_time(3219.0) == "53:39"
