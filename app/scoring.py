"""Aggregate matched leaderboard data into stage standings and an overall cup.

A stage owns one or more segments; a competitor's stage value combines their segment
times (currently the sum, requiring a time on every segment). The cup combines each
competitor's stage values across stages (currently the sum of times, requiring a value
in every stage). Registered competitors are grouped by their registration category;
everyone who rode but did not register is collected under one configurable group name.

``StageRule`` / ``CupRule`` are enums today with one implemented member each, but the
seam is deliberate: new stage contributions (place, an integral score) and new cup
combinations plug in via ``stage_contribution`` / ``combine_cup`` without touching
callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.leaderboard import build_athlete_url
from app.matching import MatchResult, extract_strava_id
from app.models import LeaderboardRow, Participant


class StageRule(StrEnum):
    """What a stage contributes to the cup. Only ``TIME`` is implemented so far."""

    TIME = "time"


class CupRule(StrEnum):
    """How stage contributions combine into a cup total (only ``SUM_OF_TIMES``)."""

    SUM_OF_TIMES = "sum_of_times"


@dataclass(frozen=True)
class Competitor:
    """Stable identity of a competitor across segments and stages."""

    key: str
    name: str
    group_name: str
    is_registered: bool
    athlete_url: str = ""


@dataclass
class StageEntry:
    """One competitor's result on one stage: per-segment times and their combination."""

    competitor: Competitor
    segment_values: list[float | None]
    value: float | None
    result_url: str = ""


@dataclass
class CupEntry:
    """One competitor's cup result: their value on each stage and the combined total."""

    competitor: Competitor
    stage_values: list[float | None]
    total: float | None
    stage_urls: list[str] = field(default_factory=list)


@dataclass
class Ranked:
    """A stage or cup entry with the place assigned within its ranking scope."""

    place: int | None
    entry: StageEntry | CupEntry


def combine_times(values: list[float | None]) -> float | None:
    """Sum the times, or ``None`` if the list is empty or any time is missing.

    A missing component (a segment or stage the competitor did not complete) makes the
    combined result undefined, so they rank after everyone with a full result.
    """
    if not values or any(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


def _athlete_url(participant: Participant, rows: list[LeaderboardRow]) -> str:
    """A registered rider's profile URL: from a scraped row, else their registration."""
    for row in rows:
        if row.athlete_url:
            return row.athlete_url
    strava_id = extract_strava_id(participant.additional_info)
    return build_athlete_url(strava_id) if strava_id else ""


def _result_url(rows: list[LeaderboardRow | None]) -> str:
    """The first available effort (activity) link across a stage's segment rows."""
    for row in rows:
        if row is not None and row.attempt_url:
            return row.attempt_url
    return ""


def build_stage_entries(
    segment_matches: list[MatchResult],
    participants: list[Participant],
    unregistered_group_name: str = "Not registered",
) -> list[StageEntry]:
    """Build a stage's entries from its per-segment match results.

    Every registered participant appears (even with no time, per the requirement that
    the protocol lists all registered riders). Riders who matched no registration are
    grouped by Strava athlete id into the ``unregistered_group_name`` group. Each entry
    carries the rider's profile link and the effort link behind their stage result.
    """
    n = len(segment_matches)
    entries: list[StageEntry] = []

    for participant in participants:
        seg_rows = [m.results.get(participant.id) for m in segment_matches]
        seg_values = [row.result_seconds if row else None for row in seg_rows]
        matched = [row for row in seg_rows if row is not None]
        entries.append(
            StageEntry(
                competitor=Competitor(
                    key=f"p:{participant.id}",
                    name=participant.display_name,
                    group_name=participant.category_name,
                    is_registered=True,
                    athlete_url=_athlete_url(participant, matched),
                ),
                segment_values=seg_values,
                value=combine_times(seg_values),
                result_url=_result_url(seg_rows),
            )
        )

    order: list[str] = []
    per_segment: dict[str, dict[int, LeaderboardRow]] = {}
    names: dict[str, str] = {}
    for i, match in enumerate(segment_matches):
        for row in match.unregistered:
            aid = row.athlete_id or f"anon:{i}:{row.athlete_name}"
            if aid not in per_segment:
                per_segment[aid] = {}
                names[aid] = row.athlete_name
                order.append(aid)
            per_segment[aid].setdefault(i, row)
    for aid in order:
        seg_rows = [per_segment[aid].get(i) for i in range(n)]
        seg_values = [row.result_seconds if row else None for row in seg_rows]
        matched = [row for row in seg_rows if row is not None]
        entries.append(
            StageEntry(
                competitor=Competitor(
                    key=f"s:{aid}",
                    name=names[aid],
                    group_name=unregistered_group_name,
                    is_registered=False,
                    athlete_url=matched[0].athlete_url if matched else "",
                ),
                segment_values=seg_values,
                value=combine_times(seg_values),
                result_url=_result_url(seg_rows),
            )
        )
    return entries


def stage_contribution(entry: StageEntry, rule: StageRule) -> float | None:
    """The number a stage feeds into the cup for one competitor, per the stage rule."""
    if rule is StageRule.TIME:
        return entry.value
    raise ValueError(f"unsupported stage rule: {rule}")  # pragma: no cover


def combine_cup(contributions: list[float | None], rule: CupRule) -> float | None:
    """Combine per-stage contributions into a cup total, per the cup rule."""
    if rule is CupRule.SUM_OF_TIMES:
        return combine_times(contributions)
    raise ValueError(f"unsupported cup rule: {rule}")  # pragma: no cover


def build_cup_entries(
    per_stage_entries: list[list[StageEntry]],
    stage_rules: list[StageRule] | None = None,
    cup_rule: CupRule = CupRule.SUM_OF_TIMES,
) -> list[CupEntry]:
    """Combine every competitor's stage values into cup entries in first-seen order.

    ``stage_rules`` (defaulting to ``TIME`` for each stage) selects what each stage
    contributes; ``cup_rule`` selects how they combine. A competitor missing from a
    stage contributes ``None`` there, so their total is undefined unless they scored in
    every stage.
    """
    n = len(per_stage_entries)
    rules = stage_rules or [StageRule.TIME] * n
    order: list[str] = []
    competitors: dict[str, Competitor] = {}
    values: dict[str, dict[int, float | None]] = {}
    urls: dict[str, dict[int, str]] = {}
    for i, entries in enumerate(per_stage_entries):
        for entry in entries:
            key = entry.competitor.key
            if key not in competitors:
                competitors[key] = entry.competitor
                values[key] = {}
                urls[key] = {}
                order.append(key)
            values[key][i] = stage_contribution(entry, rules[i])
            urls[key][i] = entry.result_url
    cup: list[CupEntry] = []
    for key in order:
        stage_values = [values[key].get(i) for i in range(n)]
        cup.append(
            CupEntry(
                competitor=competitors[key],
                stage_values=stage_values,
                total=combine_cup(stage_values, cup_rule),
                stage_urls=[urls[key].get(i, "") for i in range(n)],
            )
        )
    return cup


def _value_of(entry: StageEntry | CupEntry) -> float | None:
    return entry.total if isinstance(entry, CupEntry) else entry.value


def rank_entries(entries: list[StageEntry | CupEntry]) -> list[Ranked]:
    """Rank entries fastest-first, ties sharing a place, missing results unranked last.

    Entries with a value are sorted ascending (lower time is better) and numbered with
    standard competition ranking (equal values share a place, the next distinct value
    skips ahead). Entries without a value keep their input order and get place ``None``.
    """
    scored = [e for e in entries if _value_of(e) is not None]
    unscored = [e for e in entries if _value_of(e) is None]
    scored.sort(key=lambda e: _value_of(e))  # type: ignore[arg-type,return-value]
    ranked: list[Ranked] = []
    for i, entry in enumerate(scored):
        if i > 0 and _value_of(entry) == _value_of(scored[i - 1]):
            place = ranked[-1].place
        else:
            place = i + 1
        ranked.append(Ranked(place=place, entry=entry))
    ranked.extend(Ranked(place=None, entry=e) for e in unscored)
    return ranked
