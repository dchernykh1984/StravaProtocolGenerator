"""Tests for the leaderboard pagination scraper, driven by a fake browser."""

from datetime import date

from app.config import SegmentConfig
from app.scraper import collect_pages, scrape_segment

_PAGE_TMPL = """
<div id="results"><table><tbody>
  <tr><td>{rank}</td><td><a href="/athletes/{aid}">Rider {aid}</a></td>
      <td>Aug {day}, 2025</td><td>{time}</td></tr>
</tbody></table></div>
"""


class _FakeBrowser:
    def __init__(self, pages: list[str]) -> None:
        self._pages = pages
        self._index = 0
        self.visited: list[str] = []

    def get(self, url: str) -> None:
        self.visited.append(url)
        self._index = 0

    def page_source(self) -> str:
        return self._pages[self._index]

    def has_next_page(self) -> bool:
        return self._index < len(self._pages) - 1

    def go_next_page(self) -> None:
        self._index += 1


def test_collect_pages_gathers_all_pages() -> None:
    pages = [
        _PAGE_TMPL.format(rank=1, aid=1, day=5, time="5:00"),
        _PAGE_TMPL.format(rank=2, aid=2, day=5, time="5:10"),
    ]
    browser = _FakeBrowser(pages)
    rows = collect_pages(browser, "https://strava/seg")
    assert [r.athlete_id for r in rows] == ["1", "2"]
    assert browser.visited == ["https://strava/seg"]


def test_collect_pages_single_page() -> None:
    browser = _FakeBrowser([_PAGE_TMPL.format(rank=1, aid=9, day=5, time="4:00")])
    rows = collect_pages(browser, "u")
    assert len(rows) == 1


def test_collect_pages_caps_runaway_pagination() -> None:
    class _Endless:
        def get(self, url: str) -> None:
            pass

        def page_source(self) -> str:
            return _PAGE_TMPL.format(rank=1, aid=1, day=5, time="5:00")

        def has_next_page(self) -> bool:
            return True

        def go_next_page(self) -> None:
            pass

    rows = collect_pages(_Endless(), "u")
    assert len(rows) == 50  # _MAX_PAGES


def test_scrape_segment_builds_url_and_filters_dates() -> None:
    pages = [
        _PAGE_TMPL.format(rank=1, aid=1, day=5, time="5:00")
        + _PAGE_TMPL.format(rank=2, aid=2, day=9, time="5:10")
    ]
    browser = _FakeBrowser(pages)
    segment = SegmentConfig("41792375", {"filter": "club"})
    rows = scrape_segment(
        browser, segment, date_from=date(2025, 8, 5), date_to=date(2025, 8, 5)
    )
    assert "segments/41792375" in browser.visited[0]
    assert [r.athlete_id for r in rows] == ["1"]
