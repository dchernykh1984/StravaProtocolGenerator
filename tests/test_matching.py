"""Tests for matching leaderboard rows to registered participants."""

from app.matching import (
    ParticipantIndex,
    duplicate_strava_id_warnings,
    extract_strava_id,
    match_rows_to_participants,
    name_match_key,
)
from app.models import LeaderboardRow, Participant


def _participant(
    pid: int, name: str, info: str = "", cat: int | None = 1
) -> Participant:
    return Participant(
        id=pid,
        first_name=name.split()[0],
        last_name=name.split()[-1],
        participant_names=name,
        category_id=cat,
        category_name="A",
        additional_info=info,
    )


def _row(name: str, athlete_id: str, result: str) -> LeaderboardRow:
    return LeaderboardRow.from_scrape(
        athlete_name=name, athlete_id=athlete_id, raw_result=result
    )


def test_extract_strava_id_from_url() -> None:
    assert extract_strava_id("https://www.strava.com/athletes/12345") == "12345"
    assert extract_strava_id("see athletes/999 profile") == "999"
    assert extract_strava_id("no link here") is None
    assert extract_strava_id("") is None


def test_duplicate_strava_id_warns_with_both_names() -> None:
    people = [
        _participant(1, "Ivan Petrov", "athletes/12345"),
        _participant(2, "Ivan P", "athletes/12345"),
        _participant(3, "Solo Rider", "athletes/999"),
    ]
    warnings = duplicate_strava_id_warnings(people)
    assert warnings == ['duplicate Strava id 12345: "Ivan Petrov", "Ivan P"']


def test_duplicate_strava_id_ignores_unlinked_and_unique() -> None:
    people = [
        _participant(1, "No Link", ""),
        _participant(2, "Also No Link", "just a note"),
        _participant(3, "Linked Once", "athletes/42"),
    ]
    assert duplicate_strava_id_warnings(people) == []


def test_name_match_key_is_swap_invariant() -> None:
    assert name_match_key("Ivan Petrov") == name_match_key("Petrov Ivan")
    assert name_match_key("  Ivan   Petrov ") == "ivan petrov"
    assert name_match_key("!!!") == ""


def test_match_by_strava_id_takes_priority() -> None:
    participants = [
        _participant(1, "Someone Else", "athletes/111"),
        _participant(2, "Wrong Name", "athletes/222"),
    ]
    index = ParticipantIndex.build(participants)
    # Name does not match anyone, but the id does -> id wins.
    row = _row("Totally Different", "222", "5:00")
    assert index.match(row) is participants[1]


def test_match_by_name_swap() -> None:
    participants = [_participant(1, "Petrov Ivan", "")]
    index = ParticipantIndex.build(participants)
    row = _row("Ivan Petrov", "999", "5:00")
    assert index.match(row) is participants[0]


def test_ambiguous_name_is_not_matched() -> None:
    participants = [_participant(1, "Ivan Petrov"), _participant(2, "Petrov Ivan")]
    index = ParticipantIndex.build(participants)
    assert index.match(_row("Ivan Petrov", "5", "5:00")) is None


def test_match_rows_splits_registered_and_unregistered() -> None:
    participants = [
        _participant(1, "Ivan Petrov", "athletes/111"),
        _participant(2, "Anna Ivanova", ""),
    ]
    rows = [
        _row("Ivan Petrov", "111", "5:00"),
        _row("Anna Ivanova", "222", "6:00"),
        _row("Random Rider", "333", "4:30"),
    ]
    result = match_rows_to_participants(rows, participants)
    assert set(result.results) == {1, 2}
    assert [r.athlete_id for r in result.unregistered] == ["333"]


def test_match_rows_keeps_fastest_on_duplicate() -> None:
    participants = [_participant(1, "Ivan Petrov", "athletes/111")]
    rows = [_row("Ivan Petrov", "111", "5:30"), _row("Ivan Petrov", "111", "5:10")]
    result = match_rows_to_participants(rows, participants)
    assert result.results[1].raw_result == "5:10"


def test_match_rows_prefers_valid_time_over_missing() -> None:
    participants = [_participant(1, "Ivan Petrov", "athletes/111")]
    rows = [_row("Ivan Petrov", "111", "-"), _row("Ivan Petrov", "111", "5:10")]
    result = match_rows_to_participants(rows, participants)
    assert result.results[1].raw_result == "5:10"


def test_match_rows_missing_time_does_not_replace_valid() -> None:
    participants = [_participant(1, "Ivan Petrov", "athletes/111")]
    rows = [_row("Ivan Petrov", "111", "5:10"), _row("Ivan Petrov", "111", "-")]
    result = match_rows_to_participants(rows, participants)
    assert result.results[1].raw_result == "5:10"
