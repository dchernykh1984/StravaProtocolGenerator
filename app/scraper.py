"""Walk a segment leaderboard page by page and collect its rows.

The browser is abstracted behind the ``Browser`` protocol so the pagination logic is
unit-testable with a fake: the real Selenium implementation lives in
``app.selenium_driver`` (coverage-omitted, since it needs a live browser). A page cap
guards against a broken next-page control looping forever.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.config import SegmentConfig
from app.leaderboard import build_segment_url, filter_by_date, parse_leaderboard_html
from app.models import LeaderboardRow

_MAX_PAGES = 50


class Browser(Protocol):
    """Minimal browser surface the scraper needs; implemented by the Selenium driver."""

    def get(self, url: str) -> None:
        """Navigate to ``url`` and wait for the leaderboard to be present."""

    def page_source(self) -> str:
        """Return the current page's HTML."""

    def has_next_page(self) -> bool:
        """Whether an enabled 'next page' control is present."""

    def go_next_page(self) -> None:
        """Click 'next page' and wait for the new results to load."""


def collect_pages(browser: Browser, url: str) -> list[LeaderboardRow]:
    """Load ``url`` and gather leaderboard rows across every page (up to the cap)."""
    browser.get(url)
    rows: list[LeaderboardRow] = []
    for _ in range(_MAX_PAGES):
        rows.extend(parse_leaderboard_html(browser.page_source()))
        if not browser.has_next_page():
            break
        browser.go_next_page()
    return rows


def scrape_segment(
    browser: Browser,
    segment: SegmentConfig,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[LeaderboardRow]:
    """Scrape one segment's leaderboard and narrow it to the collection window."""
    url = build_segment_url(segment.segment_id, segment.filters)
    rows = collect_pages(browser, url)
    return filter_by_date(rows, date_from, date_to)
