"""Read a Strava segment leaderboard from its JSON frontend endpoint.

The segment page is a React app that loads the board via an authenticated XHR to
``/frontend/segments/<id>/leaderboard`` returning JSON, so hitting that directly with
the saved session cookies is the light, reliable way to read results -- no browser and
no HTML scraping (the page HTML carries no table at all). The ``filter_type``,
``date_range``, and ``gender`` query params select the board (all / today / overall by
default); ``elapsedTime`` is seconds and ``startDateLocal`` an ISO timestamp, so each
entry maps cleanly onto a row.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.models import LeaderboardRow

Opener = Callable[..., Any]

_BASE = "https://www.strava.com"
_ENDPOINT = _BASE + "/frontend/segments/{segment_id}/leaderboard"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class StravaAuthError(Exception):
    """The saved session is not valid: Strava did not return the leaderboard JSON."""


class StravaScrapeError(Exception):
    """The leaderboard could not be fetched (transport error or bad response)."""


def cookie_header(cookies: list[dict[str, Any]]) -> str:
    """Render Selenium-style cookie dicts into a single ``Cookie`` header value."""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))


def _opt_float(value: Any) -> float | None:
    """Coerce a JSON number to ``float``, mapping ``null`` / non-numeric to ``None``."""
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _row(entry: dict[str, Any]) -> LeaderboardRow:
    """Map one JSON leaderboard entry onto a ``LeaderboardRow``."""
    athlete_id = str(entry.get("athleteIdStr") or entry.get("athleteId") or "")
    activity = str(entry.get("activityIdStr") or entry.get("activityId") or "")
    elapsed = entry.get("elapsedTime")
    return LeaderboardRow(
        athlete_name=entry.get("displayName", ""),
        athlete_id=athlete_id,
        raw_result=str(elapsed) if elapsed is not None else "",
        result_seconds=float(elapsed) if elapsed is not None else None,
        rank=entry.get("rank"),
        date=entry.get("startDateLocal", ""),
        attempt_url=f"{_BASE}/activities/{activity}" if activity else "",
        athlete_url=f"{_BASE}/athletes/{athlete_id}" if athlete_id else "",
        avg_speed=_opt_float(entry.get("avgSpeed")),  # metres/second
        avg_hr=_opt_float(entry.get("avgHr")),
        avg_watts=_opt_float(entry.get("avgWatts")),
    )


class StravaLeaderboard:
    """Reads segment leaderboards from Strava's JSON endpoint using saved cookies."""

    def __init__(
        self,
        cookies: list[dict[str, Any]],
        opener: Opener = urllib.request.urlopen,
        timeout: float = 30.0,
        on_request: Callable[[str], None] | None = None,
    ) -> None:
        self._cookie = cookie_header(cookies)
        self._opener = opener
        self._timeout = timeout
        self._on_request = on_request

    def page(
        self,
        segment_id: str,
        page: int,
        date_range: str = "",
        gender: str = "overall",
        filter_type: str = "all",
    ) -> tuple[list[LeaderboardRow], int]:
        """One page of a segment's leaderboard: its rows and the total count.

        ``date_range`` is Strava's window preset (``today``, ``this_week``, ...); an
        empty value or ``all_time`` asks for the all-time board (the param is omitted).
        ``gender`` and ``filter_type`` select the cohort (``overall`` / ``all`` by
        default).
        """
        data = self._fetch(self._url(segment_id, page, date_range, gender, filter_type))
        entries = data.get("leaderboard") or []
        return [_row(e) for e in entries], int(data.get("totalCount", len(entries)))

    @staticmethod
    def _url(
        segment_id: str, page: int, date_range: str, gender: str, filter_type: str
    ) -> str:
        endpoint = _ENDPOINT.format(segment_id=segment_id)
        params = [f"filter_type={filter_type or 'all'}"]
        if date_range and date_range != "all_time":
            params.append(f"date_range={date_range}")
        params += [f"gender={gender or 'overall'}", f"page={page}"]
        return f"{endpoint}?{'&'.join(params)}"

    def _fetch(self, url: str) -> dict[str, Any]:
        if self._on_request is not None:
            self._on_request(url)
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={
                "Cookie": self._cookie,
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise StravaAuthError(
                    f"Strava rejected the session (HTTP {exc.code})"
                ) from exc
            raise StravaScrapeError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise StravaScrapeError(f"Connection error: {exc.reason}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            # A logged-out request is answered with the HTML login page, not JSON.
            raise StravaAuthError("Strava returned HTML, not JSON") from exc
