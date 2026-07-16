"""Date helpers for a Strava segment leaderboard, plus an athlete-URL builder.

The leaderboard itself now comes as JSON (see ``app.leaderboard_api``); what remains
here is turning an effort's date string into a ``date`` and narrowing a board to a
collection window, plus building an athlete's profile URL from their id.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models import LeaderboardRow

_BASE_URL = "https://www.strava.com"
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d")


def build_athlete_url(strava_id: str) -> str:
    """Return an athlete's Strava profile URL from their numeric id."""
    return f"{_BASE_URL}/athletes/{strava_id}"


def parse_leaderboard_date(text: str, today: date | None = None) -> date | None:
    """Parse a leaderboard date cell to a ``date``; ``None`` when it cannot be read.

    Handles the ISO timestamps the JSON API returns ("2026-07-15T00:00:00Z"), the
    absolute formats Strava renders ("Aug 5, 2025", "2025-08-05", ...), and the relative
    "Today"/"Yesterday" labels resolved against ``today`` (default: the current date).
    Any trailing time-of-day after the date is ignored.
    """
    from datetime import datetime

    today = today or date.today()
    cleaned = text.strip()
    low = cleaned.lower()
    if low.startswith("today"):
        return today
    if low.startswith("yesterday"):
        return today - timedelta(days=1)
    try:  # ISO timestamps from the JSON API, e.g. "2026-07-15T00:00:00Z"
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
    except ValueError:
        pass
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
    kept. A row whose date cannot be parsed is kept, so an unreadable date never drops a
    real result.
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
