"""Tests for the Strava JSON leaderboard client, driven by a fake network opener."""

from __future__ import annotations

import email.message
import json
import urllib.error
from typing import Any

import pytest

from app.leaderboard_api import (
    StravaAuthError,
    StravaLeaderboard,
    StravaScrapeError,
    cookie_header,
)

_JSON = json.dumps(
    {
        "leaderboard": [
            {
                "rank": 1,
                "displayName": "Ivan",
                "athleteId": 111,
                "activityId": 900,
                "startDateLocal": "2025-08-05T07:00:00Z",
                "elapsedTime": 300,
            },
            {
                "rank": 2,
                "displayName": "Anna",
                "athleteIdStr": "222",
                "activityIdStr": "901",
                "startDateLocal": "2025-08-06T07:00:00Z",
                "elapsedTime": None,
            },
        ],
        "totalCount": 2,
    }
)


class _Resp:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Opener:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return _Resp(str(self._outcome))


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "msg", email.message.Message(), None)


def test_cookie_header_joins_named_cookies_and_skips_nameless() -> None:
    header = cookie_header(
        [{"name": "a", "value": "1"}, {"value": "skip"}, {"name": "b", "value": "2"}]
    )
    assert header == "a=1; b=2"


def test_page_parses_json_into_rows_and_total() -> None:
    opener = _Opener(_JSON)
    board = StravaLeaderboard([{"name": "s", "value": "tok"}], opener=opener)
    rows, total = board.page("41792375", 1)
    assert total == 2
    first = rows[0]
    assert first.athlete_name == "Ivan"
    assert first.athlete_id == "111"
    assert first.result_seconds == 300.0
    assert first.date == "2025-08-05T07:00:00Z"
    assert first.athlete_url == "https://www.strava.com/athletes/111"
    assert first.attempt_url == "https://www.strava.com/activities/900"
    assert rows[1].athlete_id == "222"  # from the ...IdStr fallback
    assert rows[1].result_seconds is None
    request = opener.requests[0]
    assert "segments/41792375/leaderboard?filter_type=all&page=1" in request.full_url
    assert request.headers.get("Cookie") == "s=tok"


def test_unauthorized_raises_auth_error() -> None:
    board = StravaLeaderboard([], opener=_Opener(_http_error(401)))
    with pytest.raises(StravaAuthError):
        board.page("1", 1)


def test_html_body_raises_auth_error() -> None:
    board = StravaLeaderboard([], opener=_Opener("<html>login page</html>"))
    with pytest.raises(StravaAuthError):
        board.page("1", 1)


def test_server_error_raises_scrape_error() -> None:
    board = StravaLeaderboard([], opener=_Opener(_http_error(500)))
    with pytest.raises(StravaScrapeError, match="500"):
        board.page("1", 1)


def test_connection_error_raises_scrape_error() -> None:
    board = StravaLeaderboard([], opener=_Opener(urllib.error.URLError("down")))
    with pytest.raises(StravaScrapeError, match="Connection"):
        board.page("1", 1)
