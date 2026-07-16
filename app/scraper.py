"""Collect a segment's leaderboard rows, page by page, and narrow to a date window.

The leaderboard source is abstracted behind the ``Leaderboard`` protocol so pagination
is unit-testable with a fake; the real implementation is
``app.leaderboard_api.StravaLeaderboard`` (Strava's JSON endpoint). A page cap guards
against a bad total count looping forever.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.config import SegmentConfig
from app.leaderboard import filter_by_date
from app.models import LeaderboardRow

_MAX_PAGES = 50


class Leaderboard(Protocol):
    """Minimal leaderboard source the scraper needs; the API client implements it."""

    def page(self, segment_id: str, page: int) -> tuple[list[LeaderboardRow], int]:
        """Return one page of rows for ``segment_id`` and the board's total count."""


def collect_pages(leaderboard: Leaderboard, segment_id: str) -> list[LeaderboardRow]:
    """Gather a segment's leaderboard rows across every page (up to the cap)."""
    rows: list[LeaderboardRow] = []
    for page in range(1, _MAX_PAGES + 1):
        page_rows, total = leaderboard.page(segment_id, page)
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(rows) >= total:
            break
    return rows


def scrape_segment(
    leaderboard: Leaderboard,
    segment: SegmentConfig,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[LeaderboardRow]:
    """Scrape one segment's leaderboard and narrow it to the collection window."""
    rows = collect_pages(leaderboard, segment.segment_id)
    return filter_by_date(rows, date_from, date_to)
