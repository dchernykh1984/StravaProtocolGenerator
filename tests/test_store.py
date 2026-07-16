"""Tests for the accumulating per-segment effort store."""

from datetime import date

from app.models import LeaderboardRow
from app.store import SegmentStore


def _row(
    aid: str,
    seconds: float | None,
    day: int,
    activity: str = "",
    name: str = "",
) -> LeaderboardRow:
    return LeaderboardRow(
        athlete_name=name or f"Rider {aid}",
        athlete_id=aid,
        raw_result="",
        result_seconds=seconds,
        date=f"2026-07-{day:02d}T08:00:00Z",
        attempt_url=activity,
    )


def test_merge_deduplicates_by_athlete_and_activity() -> None:
    store = SegmentStore()
    added = store.merge([_row("1", 300.0, 15, "act-a"), _row("2", 320.0, 15, "act-b")])
    assert added == 2
    # The same two efforts plus one new one: only the new one is added.
    added = store.merge([_row("1", 300.0, 15, "act-a"), _row("1", 290.0, 16, "act-c")])
    assert added == 1
    assert len(store.rows) == 3


def test_merge_without_activity_falls_back_to_date_and_time() -> None:
    store = SegmentStore()
    store.merge([_row("1", 300.0, 15)])  # no activity url
    # Same athlete/date/time -> duplicate; different time -> new.
    assert store.merge([_row("1", 300.0, 15)]) == 0
    assert store.merge([_row("1", 305.0, 15)]) == 1


def test_best_in_range_keeps_fastest_per_athlete_within_window() -> None:
    store = SegmentStore()
    store.merge(
        [
            _row("1", 300.0, 15, "a"),  # in window, slower
            _row("1", 280.0, 16, "b"),  # in window, faster -> kept
            _row("1", 250.0, 10, "c"),  # PR before the window -> excluded
            _row("2", 400.0, 16, "d"),
        ]
    )
    best = store.best_in_range(date(2026, 7, 14), date(2026, 7, 20))
    by_athlete = {r.athlete_id: r.result_seconds for r in best}
    assert by_athlete == {"1": 280.0, "2": 400.0}  # not the 250 PR from the 10th


def test_best_in_range_recovers_in_window_effort_hidden_by_a_faster_pr() -> None:
    # The core scenario: an athlete's all-time PR is outside the window, but a slower
    # in-window effort was captured earlier and is preserved here.
    store = SegmentStore()
    store.merge([_row("1", 250.0, 5, "pr"), _row("1", 300.0, 15, "race")])
    best = store.best_in_range(date(2026, 7, 15), date(2026, 7, 15))
    assert [r.result_seconds for r in best] == [300.0]


def test_best_in_range_sorted_fastest_first_timeless_last() -> None:
    store = SegmentStore()
    store.merge(
        [
            _row("1", 300.0, 15, "a"),
            _row("2", None, 15, "b"),  # appeared but no time
            _row("3", 200.0, 15, "c"),
        ]
    )
    best = store.best_in_range()
    assert [r.athlete_id for r in best] == ["3", "1", "2"]


def test_best_in_range_prefers_a_timed_effort_over_a_timeless_one() -> None:
    # Whichever order they arrive in, the timed effort wins over a timeless one.
    forward = SegmentStore()
    forward.merge([_row("1", None, 15, "a"), _row("1", 300.0, 15, "b")])
    assert [r.result_seconds for r in forward.best_in_range()] == [300.0]
    backward = SegmentStore()
    backward.merge([_row("1", 300.0, 15, "b"), _row("1", None, 15, "a")])
    assert [r.result_seconds for r in backward.best_in_range()] == [300.0]


def test_roundtrips_through_dict() -> None:
    store = SegmentStore()
    store.merge([_row("1", 300.0, 15, "a"), _row("2", 320.0, 16, "b")])
    restored = SegmentStore.from_dict(store.to_dict())
    assert restored == store
    assert SegmentStore.from_dict(None).rows == []
