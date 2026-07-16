"""Core input data models: scraped Strava leaderboard rows and site registrations.

``LeaderboardRow`` is produced by the leaderboard parser from a Strava segment page.
``Participant`` and ``Category`` mirror the cycling-site ``/api/v1/participants/``
payload (the registered roster and its groups). All three are plain dataclasses so they
round-trip cleanly through the raw-data backups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.timeparse import parse_time


@dataclass
class LeaderboardRow:
    """One rider's best effort on a segment, as scraped from the leaderboard table."""

    athlete_name: str
    athlete_id: str
    raw_result: str
    result_seconds: float | None = None
    rank: int | None = None
    date: str = ""
    attempt_url: str = ""
    athlete_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_name": self.athlete_name,
            "athlete_id": self.athlete_id,
            "raw_result": self.raw_result,
            "result_seconds": self.result_seconds,
            "rank": self.rank,
            "date": self.date,
            "attempt_url": self.attempt_url,
            "athlete_url": self.athlete_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LeaderboardRow:
        return cls(
            athlete_name=data.get("athlete_name", ""),
            athlete_id=str(data.get("athlete_id", "")),
            raw_result=data.get("raw_result", ""),
            result_seconds=data.get("result_seconds"),
            rank=data.get("rank"),
            date=data.get("date", ""),
            attempt_url=data.get("attempt_url", ""),
            athlete_url=data.get("athlete_url", ""),
        )

    @classmethod
    def from_scrape(
        cls,
        *,
        athlete_name: str,
        athlete_id: str,
        raw_result: str,
        rank: int | None = None,
        date: str = "",
        attempt_url: str = "",
        athlete_url: str = "",
    ) -> LeaderboardRow:
        """Build a row from scraped cells, parsing the result string to seconds."""
        return cls(
            athlete_name=athlete_name.strip(),
            athlete_id=str(athlete_id).strip(),
            raw_result=raw_result.strip(),
            result_seconds=parse_time(raw_result),
            rank=rank,
            date=date.strip(),
            attempt_url=attempt_url.strip(),
            athlete_url=athlete_url.strip(),
        )


@dataclass
class Category:
    """A registration group (race category) of a competition."""

    id: int
    name: str
    male: bool = True
    female: bool = True
    bib_from: int = 1
    bib_to: int = 20000

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Category:
        return cls(
            id=int(data["id"]),
            name=data.get("name", ""),
            male=bool(data.get("male", True)),
            female=bool(data.get("female", True)),
            bib_from=int(data.get("bib_from") or 1),
            bib_to=int(data.get("bib_to") or 20000),
        )


@dataclass
class RaceInfo:
    """Event-wide header/footer text shown on every protocol (as in FPG's Race Info).

    Every ``*_label`` is the caption printed before its value, so the same fields serve
    a race in any language. ``sponsor`` and ``bottom_text`` are inserted as raw HTML
    (the user may paste a banner or a link there); other fields are escaped when shown.
    """

    date: str = ""
    place: str = ""
    weather_label: str = "Weather"
    weather: str = ""
    track_label: str = "Track"
    track_conditions: str = ""
    referee_label: str = "Referee"
    referee: str = ""
    secretary_label: str = "Secretary"
    secretary: str = ""
    organizer_label: str = "Organizer"
    organizer: str = ""
    sponsor: str = ""
    bottom_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "place": self.place,
            "weather_label": self.weather_label,
            "weather": self.weather,
            "track_label": self.track_label,
            "track_conditions": self.track_conditions,
            "referee_label": self.referee_label,
            "referee": self.referee,
            "secretary_label": self.secretary_label,
            "secretary": self.secretary,
            "organizer_label": self.organizer_label,
            "organizer": self.organizer,
            "sponsor": self.sponsor,
            "bottom_text": self.bottom_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RaceInfo:
        # Tolerate a missing or ``null`` block in a hand-edited config, like the rest of
        # the config loaders: fall back to defaults rather than raising.
        data = data or {}
        defaults = cls()
        return cls(
            **{key: data.get(key, getattr(defaults, key)) for key in defaults.to_dict()}
        )


@dataclass
class Participant:
    """One registered competitor, as returned by the site participants endpoint."""

    id: int
    first_name: str
    last_name: str
    participant_names: str
    category_id: int | None
    category_name: str
    additional_info: str
    birth_year: int = 0
    gender: str = ""
    team: str = ""
    city: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Best human-readable name: the site's combined name, else last + first."""
        if self.participant_names.strip():
            return self.participant_names.strip()
        return f"{self.last_name} {self.first_name}".strip()

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Participant:
        return cls(
            id=int(data["id"]),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            participant_names=data.get("participant_names", ""),
            category_id=data.get("category_id"),
            category_name=data.get("category_name", ""),
            additional_info=data.get("additional_info", ""),
            birth_year=int(data.get("birth_year") or 0),
            gender=data.get("gender", ""),
            team=data.get("team", ""),
            city=data.get("city", ""),
        )
