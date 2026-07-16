"""Collect a segment's leaderboard rows, page by page, across one or more windows.

The leaderboard source is abstracted behind the ``Leaderboard`` protocol so pagination
is unit-testable with a fake; the real implementation is
``app.leaderboard_api.StravaLeaderboard`` (Strava's JSON endpoint). A page cap guards
against a bad total count looping forever. ``scrape_windows`` reads a segment across
several date-range presets (chosen by ``app.windows``) and returns every row; the caller
merges them into the segment store, where duplicates collapse and the date filter runs.
"""

from __future__ import annotations

from typing import Protocol

from app.config import DateRange, SegmentConfig
from app.models import LeaderboardRow

_MAX_PAGES = 50


class Leaderboard(Protocol):
    """Minimal leaderboard source the scraper needs; the API client implements it."""

    def page(
        self,
        segment_id: str,
        page: int,
        date_range: str = "",
        gender: str = "overall",
        filter_type: str = "all",
    ) -> tuple[list[LeaderboardRow], int]:
        """Return one page of rows for ``segment_id`` and the board's total count."""


def collect_pages(
    leaderboard: Leaderboard,
    segment_id: str,
    date_range: str = "",
    gender: str = "overall",
    filter_type: str = "all",
) -> list[LeaderboardRow]:
    """Gather a segment's leaderboard rows across every page (up to the cap).

    The filters select Strava's server-side board: ``date_range`` picks the window
    (``today``, ``this_week``, ...) so a popular segment returns that window's efforts
    rather than all-time PRs; ``gender`` and ``filter_type`` pick the cohort.
    """
    rows: list[LeaderboardRow] = []
    for page in range(1, _MAX_PAGES + 1):
        page_rows, total = leaderboard.page(
            segment_id, page, date_range, gender, filter_type
        )
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(rows) >= total:
            break
    return rows


def scrape_windows(
    leaderboard: Leaderboard,
    segment: SegmentConfig,
    presets: list[DateRange],
) -> list[LeaderboardRow]:
    """Scrape one segment across each date-range ``preset`` and return all rows.

    Rows from different windows overlap heavily; the segment store deduplicates them, so
    scraping several widths only widens coverage. The segment's own gender/filter cohort
    is used for every window.
    """
    rows: list[LeaderboardRow] = []
    for preset in presets:
        rows.extend(
            collect_pages(
                leaderboard,
                segment.segment_id,
                preset.value,
                segment.gender.value,
                segment.filter_type.value,
            )
        )
    return rows
