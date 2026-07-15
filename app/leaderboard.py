"""Turn a Strava segment leaderboard page into structured rows, plus URL/date helpers.

The parser reads the same table the ``strava_segment_table`` scraper walked with
Selenium (``#results table`` rows: rank, athlete, date, ..., result), but from page
HTML so it is unit-testable without a browser. ``build_segment_url`` reproduces that
project's filtered URL, and ``filter_by_date`` narrows a board to a collection window
(Strava offers only coarse ``date_range`` presets, so the exact window is applied here).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.models import LeaderboardRow

_BASE_URL = "https://www.strava.com"
_SEGMENT_URL = _BASE_URL + "/segments/{segment_id}"
_ATHLETE_ID_RE = re.compile(r"/athletes/(\d+)")
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d")


def build_segment_url(segment_id: str, filters: dict[str, str] | None = None) -> str:
    """Build a leaderboard URL with query filters (defaults to the overall board).

    ``filters`` mirrors the Strava leaderboard query (``filter``, ``club_id``,
    ``gender``, ``age_group``, ``weight_class``, ``date_range``); an empty mapping falls
    back to the overall leaderboard, as ``strava_segment_table`` did.
    """
    from urllib.parse import urlencode

    query = dict(filters) if filters else {"filter": "overall"}
    return _SEGMENT_URL.format(segment_id=segment_id) + "?" + urlencode(query)


def build_athlete_url(strava_id: str) -> str:
    """Return an athlete's Strava profile URL from their numeric id."""
    return f"{_BASE_URL}/athletes/{strava_id}"


def _abs_url(href: str) -> str:
    return _BASE_URL + href if href.startswith("/") else href


def _cell_text(cell: Tag) -> str:
    return cell.get_text(" ", strip=True)


def _athlete_from_row(cells: list[Tag]) -> tuple[str, str, str]:
    """Return ``(name, athlete_id, athlete_url)`` from a row's athlete link."""
    for cell in cells:
        link = cell.find("a", href=_ATHLETE_ID_RE)
        if isinstance(link, Tag):
            href = str(link.get("href", ""))
            match = _ATHLETE_ID_RE.search(href)
            athlete_id = match.group(1) if match else ""
            return link.get_text(" ", strip=True), athlete_id, _abs_url(href)
    # No athlete link: fall back to the second column's text, no id.
    name = _cell_text(cells[1]) if len(cells) > 1 else ""
    return name, "", ""


def _attempt_url_from_cell(cell: Tag) -> str:
    link = cell.find("a")
    if isinstance(link, Tag) and link.get("href"):
        return _abs_url(str(link.get("href")))
    return ""


def _parse_rank(text: str) -> int | None:
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def parse_leaderboard_html(html: str) -> list[LeaderboardRow]:
    """Parse a segment leaderboard page into rows (rank, athlete, date, result).

    Rows without at least rank/athlete/date/result cells are skipped, so header or
    filler rows produce no junk entries. The result is taken from the last cell, as in
    the leaderboard layout the Selenium scraper relied on.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="results") or soup
    table = container.find("table") if isinstance(container, Tag) else None
    if not isinstance(table, Tag):
        return []
    body = table.find("tbody")
    rows_scope = body if isinstance(body, Tag) else table
    result: list[LeaderboardRow] = []
    for tr in rows_scope.find_all("tr"):
        cells = [c for c in tr.find_all("td") if isinstance(c, Tag)]
        if len(cells) < 4:
            continue
        name, athlete_id, athlete_url = _athlete_from_row(cells)
        result.append(
            LeaderboardRow.from_scrape(
                athlete_name=name,
                athlete_id=athlete_id,
                raw_result=_cell_text(cells[-1]),
                rank=_parse_rank(_cell_text(cells[0])),
                date=_cell_text(cells[2]),
                attempt_url=_attempt_url_from_cell(cells[2]),
                athlete_url=athlete_url,
            )
        )
    return result


def has_results_table(html: str) -> bool:
    """Whether the page carries a leaderboard results table at all.

    Distinguishes a real leaderboard (server-rendered table, even when empty) from a
    page whose table would only appear after JavaScript runs, which plain HTTP cannot
    do -- the caller uses this to warn instead of silently scraping nothing.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="results") or soup
    return isinstance(container, Tag) and isinstance(container.find("table"), Tag)


def has_next_page(html: str) -> bool:
    """Whether an enabled 'next page' pagination control is present in ``html``."""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("li", class_="next_page")
    if not isinstance(link, Tag):
        return False
    classes = link.get("class") or []
    return "disabled" not in classes


def parse_leaderboard_date(text: str, today: date | None = None) -> date | None:
    """Parse a leaderboard date cell to a ``date``; ``None`` when it cannot be read.

    Handles the absolute formats Strava renders ("Aug 5, 2025", "2025-08-05", ...) and
    the relative "Today"/"Yesterday" labels resolved against ``today`` (default: the
    current date). Any trailing time-of-day after the date is ignored.
    """
    from datetime import datetime

    today = today or date.today()
    cleaned = text.strip()
    low = cleaned.lower()
    if low.startswith("today"):
        return today
    if low.startswith("yesterday"):
        return today - timedelta(days=1)
    for fmt in _DATE_FORMATS:
        head = cleaned.split(" at ")[0].strip()
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def filter_by_date(
    rows: list[LeaderboardRow],
    date_from: date | None = None,
    date_to: date | None = None,
    today: date | None = None,
) -> list[LeaderboardRow]:
    """Keep rows whose parsed date is within ``[date_from, date_to]`` (inclusive).

    Either bound may be ``None`` (open on that side); with both ``None`` every row is
    kept. A row whose date cannot be parsed is kept -- the coarse Strava ``date_range``
    preset is assumed to already bound the board, and dropping an unreadable date would
    lose a real result.
    """
    if date_from is None and date_to is None:
        return list(rows)
    kept: list[LeaderboardRow] = []
    for row in rows:
        parsed = parse_leaderboard_date(row.date, today)
        if parsed is None:
            kept.append(row)
            continue
        if date_from is not None and parsed < date_from:
            continue
        if date_to is not None and parsed > date_to:
            continue
        kept.append(row)
    return kept
