"""Tests for leaderboard HTML parsing, URL building, and date filtering."""

from datetime import date

from app.leaderboard import (
    build_segment_url,
    filter_by_date,
    has_next_page,
    has_results_table,
    parse_leaderboard_date,
    parse_leaderboard_html,
)

_LEADERBOARD = """
<div id="results">
  <table>
    <thead><tr><th>Rank</th><th>Name</th><th>Date</th><th>Time</th></tr></thead>
    <tbody>
      <tr>
        <td>1</td>
        <td class="athlete"><a href="/athletes/111">Ivan Petrov</a></td>
        <td><a href="/activities/900/segments/1">Aug 5, 2025</a></td>
        <td>250W</td>
        <td>5:23</td>
      </tr>
      <tr>
        <td>2</td>
        <td class="athlete">
          <a href="https://www.strava.com/athletes/222">Anna Ivanova</a>
        </td>
        <td><a href="/activities/901/segments/2">Aug 6, 2025</a></td>
        <td>230W</td>
        <td>5:40</td>
      </tr>
    </tbody>
  </table>
</div>
"""


def test_has_results_table_detects_the_table() -> None:
    assert has_results_table(_LEADERBOARD) is True
    assert has_results_table("<html><body>no table here</body></html>") is False


def test_has_next_page_reads_the_pagination_control() -> None:
    enabled = '<ul><li class="next_page"><a href="?page=2">Next</a></li></ul>'
    assert has_next_page(enabled)
    assert not has_next_page('<ul><li class="next_page disabled">Next</li></ul>')
    assert not has_next_page("<ul><li>1</li></ul>")


def test_build_segment_url_default_is_overall() -> None:
    assert (
        build_segment_url("123") == "https://www.strava.com/segments/123?filter=overall"
    )


def test_build_segment_url_with_filters() -> None:
    url = build_segment_url("123", {"filter": "club", "club_id": "731125"})
    assert url.startswith("https://www.strava.com/segments/123?")
    assert "filter=club" in url
    assert "club_id=731125" in url


def test_parse_leaderboard_extracts_rows() -> None:
    rows = parse_leaderboard_html(_LEADERBOARD)
    assert len(rows) == 2
    first = rows[0]
    assert first.rank == 1
    assert first.athlete_name == "Ivan Petrov"
    assert first.athlete_id == "111"
    assert first.athlete_url == "https://www.strava.com/athletes/111"
    assert first.result_seconds == 323.0
    assert first.date == "Aug 5, 2025"
    assert first.attempt_url == "https://www.strava.com/activities/900/segments/1"


def test_parse_leaderboard_handles_absolute_athlete_url() -> None:
    rows = parse_leaderboard_html(_LEADERBOARD)
    assert rows[1].athlete_url == "https://www.strava.com/athletes/222"


def test_parse_leaderboard_skips_short_rows() -> None:
    html = """
    <table><tbody>
      <tr><td>only</td><td>two</td></tr>
    </tbody></table>
    """
    assert parse_leaderboard_html(html) == []


def test_parse_leaderboard_no_table_returns_empty() -> None:
    assert parse_leaderboard_html("<div>nothing here</div>") == []


def test_parse_leaderboard_without_athlete_link() -> None:
    html = """
    <table><tbody>
      <tr><td>1</td><td>No Link Name</td><td>Aug 5, 2025</td><td>5:00</td></tr>
    </tbody></table>
    """
    row = parse_leaderboard_html(html)[0]
    assert row.athlete_name == "No Link Name"
    assert row.athlete_id == ""


def test_parse_leaderboard_date_absolute_and_relative() -> None:
    today = date(2025, 8, 10)
    assert parse_leaderboard_date("Aug 5, 2025") == date(2025, 8, 5)
    assert parse_leaderboard_date("2025-08-05") == date(2025, 8, 5)
    assert parse_leaderboard_date("Today at 7:45 AM", today) == today
    assert parse_leaderboard_date("Yesterday", today) == date(2025, 8, 9)
    assert parse_leaderboard_date("garbage") is None


def test_filter_by_date_window() -> None:
    rows = parse_leaderboard_html(_LEADERBOARD)
    kept = filter_by_date(rows, date(2025, 8, 5), date(2025, 8, 5))
    assert [r.athlete_id for r in kept] == ["111"]


def test_filter_by_date_excludes_before_from() -> None:
    rows = parse_leaderboard_html(_LEADERBOARD)
    assert filter_by_date(rows, date_from=date(2025, 8, 7)) == []


def test_filter_by_date_bounds_are_inclusive() -> None:
    rows = parse_leaderboard_html(_LEADERBOARD)
    # the Aug 5 row survives an upper bound sitting exactly on its date
    upper_edge = filter_by_date(rows, None, date(2025, 8, 5))
    assert [r.athlete_id for r in upper_edge] == ["111"]
    # the Aug 6 row survives a lower bound sitting exactly on its date
    lower_edge = filter_by_date(rows, date(2025, 8, 6))
    assert [r.athlete_id for r in lower_edge] == ["222"]


def test_filter_by_date_open_bounds_keeps_all() -> None:
    rows = parse_leaderboard_html(_LEADERBOARD)
    assert len(filter_by_date(rows)) == 2


def test_filter_by_date_keeps_unparsable_dates() -> None:
    rows = parse_leaderboard_html(
        "<table><tbody><tr><td>1</td><td>N</td><td>whenever</td><td>5:00</td></tr></tbody></table>"
    )
    assert len(filter_by_date(rows, date(2025, 1, 1), date(2025, 1, 2))) == 1
