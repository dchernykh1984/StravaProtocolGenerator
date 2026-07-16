"""Tests for Strava app.link resolution and its cache."""

from __future__ import annotations

import urllib.error
from typing import Any

from app.applink import (
    AppLinkCache,
    AppLinkResolver,
    CachingLinkResolver,
    find_app_link,
)


class _Resp:
    def __init__(self, final_url: str, body: str = "") -> None:
        self._final_url = final_url
        self._body = body.encode("utf-8")

    def geturl(self) -> str:
        return self._final_url

    def read(self, _n: int = -1) -> bytes:
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
        return self._outcome


def test_find_app_link_extracts_the_url() -> None:
    assert find_app_link("see https://strava.app.link/M8iCpTsoO4b ok") == (
        "https://strava.app.link/M8iCpTsoO4b"
    )
    assert find_app_link("athletes/111") is None
    assert find_app_link("") is None


def test_resolver_reads_the_id_from_the_redirect_url() -> None:
    opener = _Opener(_Resp("https://www.strava.com/athletes/16069938?utm=x"))
    resolver = AppLinkResolver(opener=opener)
    assert resolver.resolve("https://strava.app.link/M8iCpTsoO4b") == "16069938"


def test_resolver_falls_back_to_the_body() -> None:
    body = '<link rel="canonical" href="https://www.strava.com/athletes/42"/>'
    opener = _Opener(_Resp("https://strava.app.link/x", body=body))
    assert AppLinkResolver(opener=opener).resolve("https://strava.app.link/x") == "42"


def test_resolver_returns_none_on_error_or_no_id() -> None:
    down = AppLinkResolver(opener=_Opener(urllib.error.URLError("down")))
    assert down.resolve("https://strava.app.link/x") is None
    empty = AppLinkResolver(opener=_Opener(_Resp("https://strava.app.link/x", "no id")))
    assert empty.resolve("https://strava.app.link/x") is None


def test_resolver_logs_each_request() -> None:
    logged: list[str] = []
    opener = _Opener(_Resp("https://www.strava.com/athletes/7"))
    resolver = AppLinkResolver(opener=opener, on_request=logged.append)
    resolver.resolve("https://strava.app.link/x")
    assert logged == ["https://strava.app.link/x"]


def test_caching_resolver_hits_network_only_on_a_miss() -> None:
    opener = _Opener(_Resp("https://www.strava.com/athletes/16069938"))
    caching = CachingLinkResolver(AppLinkResolver(opener=opener), AppLinkCache())
    link = "https://strava.app.link/M8iCpTsoO4b"
    assert caching.athlete_id(link, reload=False) == "16069938"
    assert caching.athlete_id(link, reload=False) == "16069938"  # served from cache
    assert len(opener.requests) == 1  # only one network call


def test_caching_resolver_reloads_when_forced() -> None:
    opener = _Opener(_Resp("https://www.strava.com/athletes/16069938"))
    caching = CachingLinkResolver(AppLinkResolver(opener=opener), AppLinkCache())
    link = "https://strava.app.link/x"
    caching.athlete_id(link, reload=False)
    caching.athlete_id(link, reload=True)  # re-resolves despite the cache
    assert len(opener.requests) == 2


def test_cache_round_trips_and_tolerates_corruption() -> None:
    cache = AppLinkCache()
    cache.put("https://strava.app.link/x", "16069938")
    assert AppLinkCache.from_dict(cache.to_dict()) == cache
    assert AppLinkCache.from_dict(None).ids == {}
    assert AppLinkCache.from_dict({"ids": None}).ids == {}
