"""Resolve Strava "share from app" deep links to athlete ids, with a persistent cache.

A link copied from the mobile app looks like ``https://strava.app.link/<key>`` -- a
Branch.io deep link whose ``<key>`` is an opaque database key, not an encoding of the
athlete id, so it can only be resolved online. One HTTP request is enough: the link
redirects to the canonical ``strava.com/athletes/<id>`` URL, from which the id is read.

The mapping never changes (a link always points to the same athlete), so a resolved id
is cached forever in ``data/applink_ids.json``; a normal run resolves only links not yet
in the cache, and the "Reload athletes ids" action forces every link to be re-resolved.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Opener = Callable[..., Any]

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_APP_LINK_RE = re.compile(r"https?://[A-Za-z0-9.-]*\.app\.link/\S+")
_ATHLETE_RE = re.compile(r"athletes/(\d+)")
_MAX_BODY = 65536


def find_app_link(text: str) -> str | None:
    """Return the first ``*.app.link`` URL found in ``text``, or ``None``."""
    match = _APP_LINK_RE.search(text or "")
    return match.group(0) if match else None


class AppLinkResolver:
    """Resolves one Branch app.link to a Strava athlete id via a single HTTP request."""

    def __init__(
        self,
        opener: Opener = urllib.request.urlopen,
        timeout: float = 15.0,
        on_request: Callable[[str], None] | None = None,
    ) -> None:
        self._opener = opener
        self._timeout = timeout
        self._on_request = on_request

    def resolve(self, link: str) -> str | None:
        """The athlete id behind ``link``, or ``None`` when it cannot be resolved.

        The link redirects to the athlete's canonical URL, so the id is taken from the
        final URL (or the page body as a fallback). Never raises: a transport error or
        an unrecognised response returns ``None``, so the caller falls back to the name.
        """
        if self._on_request is not None:
            self._on_request(link)
        request = urllib.request.Request(  # noqa: S310
            link, headers={"User-Agent": _USER_AGENT}
        )
        try:
            with self._opener(request, timeout=self._timeout) as resp:
                match = _ATHLETE_RE.search(resp.geturl() or "")
                if match:
                    return match.group(1)
                body = resp.read(_MAX_BODY).decode("utf-8", errors="replace")
        except urllib.error.URLError, OSError, ValueError:
            return None
        match = _ATHLETE_RE.search(body)
        return match.group(1) if match else None


@dataclass
class AppLinkCache:
    """Persistent ``app.link -> athlete id`` mappings (immutable once resolved)."""

    ids: dict[str, str] = field(default_factory=dict)

    def get(self, link: str) -> str | None:
        return self.ids.get(link)

    def put(self, link: str, athlete_id: str) -> None:
        self.ids[link] = athlete_id

    def to_dict(self) -> dict[str, Any]:
        return {"ids": dict(self.ids)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AppLinkCache:
        raw = (data or {}).get("ids")
        ids = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        return cls(ids=ids)


class CachingLinkResolver:
    """Resolves app.links through the cache, hitting the network only on a miss."""

    def __init__(self, resolver: AppLinkResolver, cache: AppLinkCache) -> None:
        self._resolver = resolver
        self.cache = cache

    def athlete_id(self, link: str, reload: bool) -> str | None:
        """Cached id for ``link`` (re-resolved when ``reload`` or not yet cached)."""
        if not reload:
            cached = self.cache.get(link)
            if cached is not None:
                return cached
        athlete_id = self._resolver.resolve(link)
        if athlete_id is not None:
            self.cache.put(link, athlete_id)
        return athlete_id
