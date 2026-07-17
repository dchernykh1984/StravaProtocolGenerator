"""Match scraped leaderboard rows to registered participants.

Two signals, in order of trust: the Strava athlete id parsed from a registration's
``additional_info`` (exact), then a swap-tolerant name key (the athlete's name tokens
sorted, so "Ivan Petrov" and "Petrov Ivan" collide). A row that matches no registration
is returned separately, to be shown in the configurable "not registered" group.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import LeaderboardRow, Participant

_ATHLETE_ID_RE = re.compile(r"athletes/(\d+)")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def extract_strava_id(text: str) -> str | None:
    """Return the Strava athlete id embedded in ``text`` (a profile URL), or ``None``.

    Looks for an ``athletes/<digits>`` fragment, so a full profile link, a bare path, or
    a link buried in other free text in ``additional_info`` all resolve to the id.
    """
    if not text:
        return None
    match = _ATHLETE_ID_RE.search(text)
    return match.group(1) if match else None


def duplicate_strava_id_warnings(participants: list[Participant]) -> list[str]:
    """Flag registrations that share a Strava athlete id (usually a double sign-up).

    ``ParticipantIndex.build`` keeps only the first registration per id, so a duplicate
    is otherwise dropped silently. Each returned line names the shared id and every
    registration under it, so the referee can fix the roster.
    """
    by_id: dict[str, list[str]] = {}
    for participant in participants:
        strava_id = extract_strava_id(participant.additional_info)
        if strava_id:
            by_id.setdefault(strava_id, []).append(participant.display_name)
    return [
        f"duplicate Strava id {strava_id}: " + ", ".join(f'"{name}"' for name in names)
        for strava_id, names in by_id.items()
        if len(names) > 1
    ]


def name_match_key(name: str) -> str:
    """Order-independent name key: lowercased word tokens, sorted and space-joined.

    Sorting the tokens makes the key invariant to first/last-name order (the allowed
    swap) and to extra spacing. Returns ``""`` for a name with no word characters, which
    the index treats as unmatchable.
    """
    tokens = _WORD_RE.findall(name.lower())
    return " ".join(sorted(tokens))


@dataclass
class ParticipantIndex:
    """Lookup of participants by Strava id and by swap-tolerant name key."""

    by_strava_id: dict[str, Participant] = field(default_factory=dict)
    by_name_key: dict[str, list[Participant]] = field(default_factory=dict)

    @classmethod
    def build(cls, participants: list[Participant]) -> ParticipantIndex:
        index = cls()
        for participant in participants:
            strava_id = extract_strava_id(participant.additional_info)
            if strava_id and strava_id not in index.by_strava_id:
                index.by_strava_id[strava_id] = participant
            key = name_match_key(participant.display_name)
            if key:
                index.by_name_key.setdefault(key, []).append(participant)
        return index

    def match(self, row: LeaderboardRow) -> Participant | None:
        """Find the registration for a row: by Strava id first, then unique name key.

        An ambiguous name key (shared by two registrations) is treated as no match, so
        a row is never assigned to the wrong person on a name collision -- the id signal
        or the "not registered" group handles it instead.
        """
        if row.athlete_id and row.athlete_id in self.by_strava_id:
            return self.by_strava_id[row.athlete_id]
        candidates = self.by_name_key.get(name_match_key(row.athlete_name), [])
        return candidates[0] if len(candidates) == 1 else None


@dataclass
class MatchResult:
    """Outcome of matching one segment's rows against the roster.

    ``results`` maps a participant id to their best (fastest) matching row;
    ``unregistered`` holds rows that matched nobody, keyed later by athlete id.
    """

    results: dict[int, LeaderboardRow] = field(default_factory=dict)
    unregistered: list[LeaderboardRow] = field(default_factory=list)


def _is_better(candidate: LeaderboardRow, current: LeaderboardRow) -> bool:
    """True when ``candidate`` is a strictly faster valid result than ``current``."""
    if candidate.result_seconds is None:
        return False
    if current.result_seconds is None:
        return True
    return candidate.result_seconds < current.result_seconds


def match_rows_to_participants(
    rows: list[LeaderboardRow], participants: list[Participant]
) -> MatchResult:
    """Assign each leaderboard row to a registration (best row wins) or to unregistered.

    When several rows map to the same participant (e.g. a name collision resolved to
    one person), the fastest valid result is kept. Rows matching no registration are
    collected in ``unregistered`` in leaderboard order.
    """
    index = ParticipantIndex.build(participants)
    result = MatchResult()
    for row in rows:
        participant = index.match(row)
        if participant is None:
            result.unregistered.append(row)
            continue
        existing = result.results.get(participant.id)
        if existing is None or _is_better(row, existing):
            result.results[participant.id] = row
    return result
