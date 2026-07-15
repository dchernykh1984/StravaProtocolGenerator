"""Tests for the cookie-authenticated HTTP scraper, driven by a fake network opener."""

from __future__ import annotations

import email.message
import urllib.error
from typing import Any

import pytest

from app.http_browser import (
    HttpBrowser,
    StravaAuthError,
    StravaScrapeError,
    cookie_header,
    is_login_page,
)

_LEADERBOARD = (
    '<div id="results"><table><tbody>'
    '<tr><td>1</td><td><a href="/athletes/1">A</a></td><td>Aug 5, 2025</td>'
    "<td>5:00</td></tr>"
    "</tbody></table></div>"
    '<ul><li class="next_page"><a href="?page=2">Next</a></li></ul>'
)
_PAGE2 = '<div id="results"><table><tbody></tbody></table></div><ul></ul>'
_LOGIN = '<form action="/session"><input id="email"><input id="password"></form>'
_NO_TABLE = "<html><body><div>Loading...</div></body></html>"


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
    """Fake ``urlopen``: yields queued bodies/errors in order and records requests."""

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Resp(str(outcome))


def test_is_login_page_detects_the_login_form() -> None:
    assert is_login_page(_LOGIN) is True
    assert is_login_page(_LEADERBOARD) is False


def test_is_login_page_survives_field_id_changes() -> None:
    # No email/password ids -- only input types and the session form action.
    typed = '<form><input type="email"><input type="password"></form>'
    assert is_login_page(typed) is True
    session_form = '<form action="/session"><input type="password"></form>'
    assert is_login_page(session_form) is True
    # A results page has a password nowhere, so it is never a false positive.
    assert is_login_page("<table><tr><td>time</td></tr></table>") is False


def test_cookie_header_joins_named_cookies_and_skips_nameless() -> None:
    header = cookie_header(
        [{"name": "a", "value": "1"}, {"value": "skip"}, {"name": "b", "value": "2"}]
    )
    assert header == "a=1; b=2"


def test_get_returns_page_and_sends_cookie_and_user_agent() -> None:
    opener = _Opener(_LEADERBOARD)
    browser = HttpBrowser([{"name": "s", "value": "tok"}], opener=opener)
    browser.get("https://www.strava.com/segments/1?filter=overall")
    assert browser.page_source() == _LEADERBOARD
    request = opener.requests[0]
    assert request.headers.get("Cookie") == "s=tok"
    assert "Chrome" in request.headers.get("User-agent")


def test_get_on_login_page_raises_auth_error() -> None:
    browser = HttpBrowser([], opener=_Opener(_LOGIN))
    with pytest.raises(StravaAuthError):
        browser.get("https://www.strava.com/segments/1")


def test_get_without_results_table_raises_scrape_error() -> None:
    browser = HttpBrowser([], opener=_Opener(_NO_TABLE))
    with pytest.raises(StravaScrapeError, match="JavaScript"):
        browser.get("https://www.strava.com/segments/1")


def test_http_error_becomes_scrape_error_with_status() -> None:
    error = urllib.error.HTTPError("u", 403, "Forbidden", email.message.Message(), None)
    browser = HttpBrowser([], opener=_Opener(error))
    with pytest.raises(StravaScrapeError, match="403"):
        browser.get("https://www.strava.com/segments/1")


def test_url_error_becomes_scrape_error() -> None:
    browser = HttpBrowser([], opener=_Opener(urllib.error.URLError("down")))
    with pytest.raises(StravaScrapeError, match="Connection error"):
        browser.get("https://www.strava.com/segments/1")


def test_pagination_appends_page_with_ampersand_when_query_exists() -> None:
    opener = _Opener(_LEADERBOARD, _PAGE2)
    browser = HttpBrowser([], opener=opener)
    browser.get("https://www.strava.com/segments/1?filter=overall")
    assert browser.has_next_page() is True
    browser.go_next_page()
    assert browser.page_source() == _PAGE2
    assert browser.has_next_page() is False
    assert opener.requests[1].full_url.endswith("&page=2")


def test_pagination_uses_question_mark_without_existing_query() -> None:
    opener = _Opener(_LEADERBOARD, _PAGE2)
    browser = HttpBrowser([], opener=opener)
    browser.get("https://www.strava.com/segments/1")
    browser.go_next_page()
    assert opener.requests[1].full_url.endswith("?page=2")
