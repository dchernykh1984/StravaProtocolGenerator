"""Tests for the leaderboard date helpers and the athlete-URL builder."""

from datetime import date

from app.leaderboard import build_athlete_url, filter_by_date, parse_leaderboard_date
from app.models import LeaderboardRow


def _row(aid: str, when: str) -> LeaderboardRow:
    return LeaderboardRow(
        athlete_name=f"Rider {aid}", athlete_id=aid, raw_result="", date=when
    )


def test_build_athlete_url_from_id() -> None:
    assert build_athlete_url("12345") == "https://www.strava.com/athletes/12345"


def test_parse_leaderboard_date_absolute_and_relative() -> None:
    today = date(2025, 8, 10)
    assert parse_leaderboard_date("Aug 5, 2025") == date(2025, 8, 5)
    assert parse_leaderboard_date("2025-08-05") == date(2025, 8, 5)
    assert parse_leaderboard_date("Today at 7:45 AM", today) == today
    assert parse_leaderboard_date("Yesterday", today) == date(2025, 8, 9)
    assert parse_leaderboard_date("garbage") is None


def test_parse_leaderboard_date_iso_timestamp() -> None:
    # The JSON API returns ISO timestamps like "2026-07-15T00:00:00Z".
    assert parse_leaderboard_date("2026-07-15T00:00:00Z") == date(2026, 7, 15)
    assert parse_leaderboard_date("2021-04-16T10:53:08Z") == date(2021, 4, 16)


def test_filter_by_date_window() -> None:
    rows = [_row("111", "Aug 5, 2025"), _row("222", "Aug 6, 2025")]
    kept = filter_by_date(rows, date(2025, 8, 5), date(2025, 8, 5))
    assert [r.athlete_id for r in kept] == ["111"]


def test_filter_by_date_excludes_before_from() -> None:
    rows = [_row("111", "Aug 5, 2025"), _row("222", "Aug 6, 2025")]
    assert filter_by_date(rows, date_from=date(2025, 8, 7)) == []


def test_filter_by_date_bounds_are_inclusive() -> None:
    rows = [_row("111", "Aug 5, 2025"), _row("222", "Aug 6, 2025")]
    # the Aug 5 row survives an upper bound sitting exactly on its date
    upper = filter_by_date(rows, None, date(2025, 8, 5))
    assert [r.athlete_id for r in upper] == ["111"]
    # the Aug 6 row survives a lower bound sitting exactly on its date
    lower = filter_by_date(rows, date(2025, 8, 6))
    assert [r.athlete_id for r in lower] == ["222"]


def test_filter_by_date_open_bounds_keeps_all() -> None:
    rows = [_row("111", "Aug 5, 2025"), _row("222", "Aug 6, 2025")]
    assert len(filter_by_date(rows)) == 2


def test_filter_by_date_keeps_unparsable_dates() -> None:
    rows = [_row("1", "whenever")]
    assert len(filter_by_date(rows, date(2025, 1, 1), date(2025, 1, 2))) == 1
