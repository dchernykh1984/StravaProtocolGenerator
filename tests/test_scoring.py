"""Tests for stage/cup aggregation, grouping, and ranking."""

from app.matching import MatchResult
from app.models import LeaderboardRow, Participant
from app.scoring import (
    Competitor,
    CupEntry,
    CupRule,
    StageEntry,
    StageRule,
    build_cup_entries,
    build_stage_entries,
    combine_cup,
    combine_times,
    rank_entries,
    stage_contribution,
)


def _participant(pid: int, name: str, category: str = "A") -> Participant:
    return Participant(
        id=pid,
        first_name=name.split()[0],
        last_name=name.split()[-1],
        participant_names=name,
        category_id=1,
        category_name=category,
        additional_info="",
    )


def _row(name: str, athlete_id: str, seconds: float) -> LeaderboardRow:
    return LeaderboardRow(
        athlete_name=name, athlete_id=athlete_id, raw_result="", result_seconds=seconds
    )


def _comp(name: str) -> Competitor:
    return Competitor(key=name, name=name, group_name="A", is_registered=True)


def _stage_entry(name: str, value: float | None) -> StageEntry:
    return StageEntry(competitor=_comp(name), segment_values=[value], value=value)


def test_combine_times() -> None:
    assert combine_times([10.0, 20.0]) == 30.0
    assert combine_times([10.0, None]) is None
    assert combine_times([]) is None


def test_stage_entry_carries_profile_and_effort_links() -> None:
    row = LeaderboardRow(
        athlete_name="Ivan Petrov",
        athlete_id="111",
        raw_result="",
        result_seconds=300.0,
        athlete_url="https://www.strava.com/athletes/111",
        attempt_url="https://www.strava.com/activities/900/segments/1",
    )
    match = MatchResult(results={1: row})
    entry = build_stage_entries([match], [_participant(1, "Ivan Petrov")])[0]
    assert entry.competitor.athlete_url == "https://www.strava.com/athletes/111"
    assert entry.result_url == "https://www.strava.com/activities/900/segments/1"


def test_registered_without_a_row_links_profile_from_registration() -> None:
    participant = Participant(
        id=1,
        first_name="A",
        last_name="B",
        participant_names="A B",
        category_id=1,
        category_name="A",
        additional_info="https://www.strava.com/athletes/777",
    )
    entry = build_stage_entries([MatchResult()], [participant])[0]
    assert entry.competitor.athlete_url == "https://www.strava.com/athletes/777"
    assert entry.result_url == ""


def test_unregistered_competitor_carries_profile_link() -> None:
    row = LeaderboardRow(
        athlete_name="Guest",
        athlete_id="999",
        raw_result="",
        result_seconds=250.0,
        athlete_url="https://www.strava.com/athletes/999",
    )
    entry = build_stage_entries([MatchResult(unregistered=[row])], [])[0]
    assert entry.competitor.athlete_url == "https://www.strava.com/athletes/999"


def test_cup_entry_carries_per_stage_effort_links() -> None:
    e1 = StageEntry(_comp("Ivan"), [300.0], 300.0, result_url="u1")
    e2 = StageEntry(_comp("Ivan"), [200.0], 200.0, result_url="u2")
    cup = build_cup_entries([[e1], [e2]])
    assert cup[0].stage_urls == ["u1", "u2"]


def test_build_stage_entries_registered_all_appear() -> None:
    participants = [_participant(1, "Ivan Petrov"), _participant(2, "Anna Ivanova")]
    match = MatchResult(results={1: _row("Ivan Petrov", "111", 300.0)}, unregistered=[])
    entries = build_stage_entries([match], participants)
    by_name = {e.competitor.name: e for e in entries}
    assert by_name["Ivan Petrov"].value == 300.0
    # Registered but no time still appears, with value None.
    assert by_name["Anna Ivanova"].value is None
    assert all(e.competitor.is_registered for e in entries)


def test_build_stage_entries_sums_multiple_segments() -> None:
    participants = [_participant(1, "Ivan Petrov")]
    seg1 = MatchResult(results={1: _row("Ivan Petrov", "111", 300.0)})
    seg2 = MatchResult(results={1: _row("Ivan Petrov", "111", 200.0)})
    entry = build_stage_entries([seg1, seg2], participants)[0]
    assert entry.segment_values == [300.0, 200.0]
    assert entry.value == 500.0


def test_build_stage_entries_missing_segment_is_none() -> None:
    participants = [_participant(1, "Ivan Petrov")]
    seg1 = MatchResult(results={1: _row("Ivan Petrov", "111", 300.0)})
    seg2 = MatchResult(results={})
    entry = build_stage_entries([seg1, seg2], participants)[0]
    assert entry.value is None


def test_build_stage_entries_unregistered_group() -> None:
    match = MatchResult(unregistered=[_row("Random Rider", "999", 250.0)])
    entries = build_stage_entries([match], [], unregistered_group_name="Others")
    assert len(entries) == 1
    comp = entries[0].competitor
    assert comp.group_name == "Others"
    assert comp.is_registered is False
    assert comp.key == "s:999"
    assert entries[0].value == 250.0


def test_stage_contribution_and_cup_rule() -> None:
    entry = _stage_entry("x", 42.0)
    assert stage_contribution(entry, StageRule.TIME) == 42.0
    assert combine_cup([10.0, 20.0], CupRule.SUM_OF_TIMES) == 30.0


def test_build_cup_entries_sums_across_stages() -> None:
    p = [_participant(1, "Ivan Petrov")]
    stage1 = build_stage_entries([MatchResult(results={1: _row("I P", "1", 300.0)})], p)
    stage2 = build_stage_entries([MatchResult(results={1: _row("I P", "1", 200.0)})], p)
    cup = build_cup_entries([stage1, stage2])
    assert len(cup) == 1
    assert cup[0].stage_values == [300.0, 200.0]
    assert cup[0].total == 500.0


def test_build_cup_entries_missing_stage_uses_partial_total() -> None:
    p = [_participant(1, "Ivan Petrov")]
    stage1 = build_stage_entries([MatchResult(results={1: _row("I P", "1", 300.0)})], p)
    stage2 = build_stage_entries([MatchResult(results={})], p)
    cup = build_cup_entries([stage1, stage2])
    assert cup[0].stage_values == [300.0, None]
    assert cup[0].total == 300.0  # only the completed stage counts


def test_rank_cup_orders_by_stages_completed_then_total() -> None:
    fast_full = CupEntry(_comp("Fast"), [150.0, 150.0], 300.0)
    slow_full = CupEntry(_comp("Full"), [300.0, 200.0], 500.0)
    partial = CupEntry(_comp("Partial"), [100.0, None], 100.0)  # tiny total, 1 missed
    none_done = CupEntry(_comp("None"), [None, None], None)
    ranked = rank_entries([partial, slow_full, none_done, fast_full])
    places = [(r.entry.competitor.name, r.place) for r in ranked]
    # Both full-completion riders rank ahead of the partial one despite its tiny total.
    assert places == [("Fast", 1), ("Full", 2), ("Partial", 3), ("None", None)]


def test_rank_entries_ties_and_unranked() -> None:
    entries: list[StageEntry | CupEntry] = [
        _stage_entry("a", 300.0),
        _stage_entry("b", 100.0),
        _stage_entry("c", 100.0),
        _stage_entry("d", None),
    ]
    ranked = rank_entries(entries)
    places = [(r.entry.competitor.name, r.place) for r in ranked]
    assert places == [("b", 1), ("c", 1), ("a", 3), ("d", None)]
