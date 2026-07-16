"""Tests for the leaderboard pagination scraper, driven by a fake leaderboard source."""

from datetime import date

from app.config import SegmentConfig
from app.models import LeaderboardRow
from app.scraper import collect_pages, scrape_segment


def _row(aid: int, day: int = 5, seconds: float = 300.0) -> LeaderboardRow:
    return LeaderboardRow(
        athlete_name=f"Rider {aid}",
        athlete_id=str(aid),
        raw_result="",
        result_seconds=seconds,
        date=f"2025-08-{day:02d}",
    )


class _FakeLeaderboard:
    """Serves preset pages of rows and records the (segment_id, page) requests."""

    def __init__(self, pages: list[list[LeaderboardRow]], total: int | None = None):
        self._pages = pages
        self._total = total if total is not None else sum(len(p) for p in pages)
        self.requested: list[tuple[str, int]] = []

    def page(self, segment_id: str, page: int) -> tuple[list[LeaderboardRow], int]:
        self.requested.append((segment_id, page))
        rows = self._pages[page - 1] if page - 1 < len(self._pages) else []
        return rows, self._total


def test_collect_pages_gathers_all_pages() -> None:
    board = _FakeLeaderboard([[_row(1)], [_row(2)]])
    rows = collect_pages(board, "seg")
    assert [r.athlete_id for r in rows] == ["1", "2"]
    assert board.requested == [("seg", 1), ("seg", 2)]


def test_collect_pages_stops_once_total_reached() -> None:
    board = _FakeLeaderboard([[_row(1)]], total=1)
    rows = collect_pages(board, "seg")
    assert len(rows) == 1
    assert board.requested == [("seg", 1)]  # no needless second request


def test_collect_pages_stops_on_empty_page() -> None:
    board = _FakeLeaderboard([[_row(1)], []], total=999)  # total lies; empty page halts
    assert len(collect_pages(board, "seg")) == 1


def test_collect_pages_caps_runaway_pagination() -> None:
    class _Endless:
        def page(self, segment_id: str, page: int) -> tuple[list[LeaderboardRow], int]:
            return [_row(page)], 10_000  # never reaches total

    assert len(collect_pages(_Endless(), "seg")) == 50  # _MAX_PAGES


def test_scrape_segment_filters_dates() -> None:
    board = _FakeLeaderboard([[_row(1, day=5), _row(2, day=9)]])
    rows = scrape_segment(
        board,
        SegmentConfig("41792375"),
        date_from=date(2025, 8, 5),
        date_to=date(2025, 8, 5),
    )
    assert [r.athlete_id for r in rows] == ["1"]
