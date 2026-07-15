"""Scrape Strava leaderboards over plain HTTP, reusing a saved browser session.

Instead of logging in every run, the worker logs in once with Selenium, saves the
session cookies, and hands them here. This ``Browser`` implementation then fetches the
same leaderboard pages with those cookies over ``urllib`` -- no browser, no re-login.

It only works if Strava serves the results table in the page HTML. If a fetched page is
the login form (session expired) it raises ``StravaAuthError`` so the worker can log in
again; if it is a page without any results table (Strava rendered it with JavaScript,
which plain HTTP cannot run) it raises ``StravaScrapeError`` with a clear explanation.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.leaderboard import has_next_page, has_results_table

Opener = Callable[..., Any]

# A desktop-Chrome UA so Strava serves the regular leaderboard page, not a bot variant.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class StravaAuthError(Exception):
    """The saved session is not valid: Strava returned its login page."""


class StravaScrapeError(Exception):
    """A page could not be scraped (transport error or no results table present)."""


def is_login_page(html: str) -> bool:
    """Whether ``html`` is Strava's login form rather than a signed-in page.

    An expired or missing session is answered with a redirect to the login page (HTTP
    200, not 401/403), so the signal is the page content: its email and password inputs.
    """
    return 'id="email"' in html and 'id="password"' in html


def cookie_header(cookies: list[dict[str, Any]]) -> str:
    """Render Selenium-style cookie dicts into a single ``Cookie`` header value."""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))


class HttpBrowser:
    """A scraper ``Browser`` backed by cookie-authenticated HTTP (no live browser)."""

    def __init__(
        self,
        cookies: list[dict[str, Any]],
        opener: Opener = urllib.request.urlopen,
        timeout: float = 30.0,
    ) -> None:
        self._cookie = cookie_header(cookies)
        self._opener = opener
        self._timeout = timeout
        self._html = ""
        self._base_url = ""
        self._page = 1

    def _fetch(self, url: str) -> str:
        request = urllib.request.Request(  # noqa: S310
            url, headers={"Cookie": self._cookie, "User-Agent": _USER_AGENT}
        )
        try:
            with self._opener(request, timeout=self._timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise StravaScrapeError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise StravaScrapeError(f"Connection error: {exc.reason}") from exc

    def get(self, url: str) -> None:
        self._base_url = url
        self._page = 1
        self._html = self._fetch(url)
        if is_login_page(self._html):
            raise StravaAuthError("Strava session is not valid (got the login page)")
        if not has_results_table(self._html):
            raise StravaScrapeError(
                "Fetched a Strava page without a results table -- Strava likely "
                "renders it with JavaScript, which plain HTTP cannot run. A browser "
                "fallback is needed for this segment."
            )

    def page_source(self) -> str:
        return self._html

    def has_next_page(self) -> bool:
        return has_next_page(self._html)

    def go_next_page(self) -> None:
        self._page += 1
        separator = "&" if "?" in self._base_url else "?"
        self._html = self._fetch(f"{self._base_url}{separator}page={self._page}")
