"""End-to-end pipeline tests with a fake leaderboard source and fake site client."""

from app.config import AppConfig, CupConfig, HttpAction, SegmentConfig, StageConfig
from app.models import Category, LeaderboardRow, Participant
from app.pipeline import generate, generate_from_snapshot
from app.site_api import ParticipantsResponse, SiteApiError
from app.store import SegmentStore
from app.timeparse import parse_time


def _row(aid: str, name: str, result: str, day: int = 5) -> LeaderboardRow:
    return LeaderboardRow(
        athlete_name=name,
        athlete_id=aid,
        raw_result=result,
        result_seconds=parse_time(result),
        date=f"Aug {day}, 2025",
        athlete_url=f"https://www.strava.com/athletes/{aid}",
        attempt_url=f"https://www.strava.com/activities/{aid}-{day}",
    )


class _FakeStorage:
    """In-memory segment storage that accumulates across generate calls."""

    def __init__(self) -> None:
        self.stores: dict[str, SegmentStore] = {}

    def load(self, segment_id: str) -> SegmentStore:
        return self.stores.get(segment_id) or SegmentStore()

    def commit(
        self, segment_id: str, store: SegmentStore, scraped: list[LeaderboardRow]
    ) -> None:
        self.stores[segment_id] = store


def _store_with(*rows: LeaderboardRow) -> SegmentStore:
    store = SegmentStore()
    store.merge(list(rows))
    return store


class _FakeLeaderboard:
    """Serves one segment's row, keyed by segment id (a single page)."""

    def __init__(self, rows_by_segment: dict[str, LeaderboardRow]) -> None:
        self._rows = rows_by_segment
        self.filters: list[tuple[str, str, str]] = []

    def page(
        self,
        segment_id: str,
        page: int,
        date_range: str = "",
        gender: str = "overall",
        filter_type: str = "all",
    ) -> tuple[list[LeaderboardRow], int]:
        self.filters.append((date_range, gender, filter_type))
        present = segment_id in self._rows and page == 1
        rows = [self._rows[segment_id]] if present else []
        return rows, len(rows)


class _FakeClient:
    def __init__(self, roster: ParticipantsResponse, fail: bool = False) -> None:
        self._roster = roster
        self._fail = fail
        self.uploads: list[tuple[str, str, str]] = []
        self.deletes: list[tuple[str, str]] = []

    def fetch_participants(self, token: str) -> ParticipantsResponse:
        if self._fail:
            raise SiteApiError("boom")
        return self._roster

    def upload_protocol(
        self,
        token: str,
        protocol_type: str,
        html_path: str,
        is_live: bool = True,
        stage_label: str = "",
    ) -> None:
        self.uploads.append((token, protocol_type, html_path))

    def delete_protocol(self, token: str, protocol_type: str) -> None:
        self.deletes.append((token, protocol_type))


def _roster() -> ParticipantsResponse:
    return ParticipantsResponse(
        competition_id=250,
        categories=[Category(id=1, name="3.5+")],
        participants=[
            Participant(
                id=1,
                first_name="Ivan",
                last_name="Petrov",
                participant_names="Ivan Petrov",
                category_id=1,
                category_name="3.5+",
                additional_info="athletes/111",
            )
        ],
    )


def _config() -> AppConfig:
    return AppConfig(
        roster_token="cup-tok",
        output_dir="out",
        stages=[
            StageConfig(
                name="Day 1",
                segments=[SegmentConfig("seg1")],
                token="stage1-tok",
                absolute_action=HttpAction.UPLOAD,
                group_action=HttpAction.NOTHING,
            ),
        ],
        cup=CupConfig(
            name="Cup",
            token="cup-tok",
            absolute_action=HttpAction.UPLOAD,
            group_action=HttpAction.DELETE,
        ),
    )


def _capture_writer(store: dict[str, str]):
    def _writer(path: str, content: str) -> None:
        store[path] = content

    return _writer


def test_generate_writes_all_four_protocols() -> None:
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    written: dict[str, str] = {}
    result = generate(_config(), browser, client, writer=_capture_writer(written))

    kinds = {(o.kind, o.scope) for o in result.outputs}
    assert kinds == {
        ("stage", "absolute"),
        ("stage", "group"),
        ("cup", "absolute"),
        ("cup", "group"),
    }
    # Four files were written (stage abs/grp, cup abs/grp).
    assert len(written) == 4
    stage_abs = next(c for p, c in written.items() if "Day_1_absolute" in p)
    assert "Ivan Petrov" in stage_abs
    assert "5:00" in stage_abs


def test_generate_requests_the_segment_filters() -> None:
    from app.config import DateRange, FilterType, Gender

    cfg = _config()
    cfg.stages[0].segments[0].date_range = DateRange.THIS_WEEK
    cfg.stages[0].segments[0].gender = Gender.WOMEN
    cfg.stages[0].segments[0].filter_type = FilterType.FOLLOWING
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer({}))
    assert ("this_week", "F", "following") in browser.filters


def test_generate_renders_per_protocol_race_info() -> None:
    from app.models import RaceInfo

    cfg = _config()
    cfg.stages[0].race_info = RaceInfo(referee="Stage ref")
    cfg.cup.race_info = RaceInfo(organizer="Cup org")
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    written: dict[str, str] = {}
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer(written))
    stage_abs = next(c for p, c in written.items() if "Day_1_absolute" in p)
    cup_abs = next(c for p, c in written.items() if "Cup_absolute" in p)
    assert "Stage ref" in stage_abs
    assert "Cup org" in cup_abs
    # Each protocol carries only its own officials.
    assert "Cup org" not in stage_abs


def test_generate_registered_rider_grouped_by_category() -> None:
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    written: dict[str, str] = {}
    generate(_config(), browser, client, writer=_capture_writer(written))
    stage_grp = next(c for p, c in written.items() if "Day_1_group" in p)
    assert "3.5+" in stage_grp


def test_generate_unregistered_rider_goes_to_named_group() -> None:
    browser = _FakeLeaderboard({"seg1": _row("999", "Random Rider", "4:30")})
    client = _FakeClient(_roster())
    written: dict[str, str] = {}
    generate(_config(), browser, client, writer=_capture_writer(written))
    stage_grp = next(c for p, c in written.items() if "Day_1_group" in p)
    assert "Not registered" in stage_grp
    assert "Random Rider" in stage_grp


def test_stage_and_cup_name_the_unregistered_group_independently() -> None:
    cfg = _config()
    cfg.stages[0].unregistered_group_name = "Stage guests"
    cfg.cup.unregistered_group_name = "Cup guests"
    browser = _FakeLeaderboard({"seg1": _row("999", "Random Rider", "4:30")})
    written: dict[str, str] = {}
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer(written))
    stage_grp = next(c for p, c in written.items() if "Day_1_group" in p)
    cup_grp = next(c for p, c in written.items() if "Cup_group" in p)
    assert "Stage guests" in stage_grp
    assert "Cup guests" in cup_grp


def test_hidden_unregistered_group_drops_unregistered_riders() -> None:
    cfg = _config()
    cfg.stages[0].show_unregistered = False
    cfg.cup.show_unregistered = False
    browser = _FakeLeaderboard({"seg1": _row("999", "Random Rider", "4:30")})
    written: dict[str, str] = {}
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer(written))
    # The unregistered rider appears in no protocol when hidden.
    assert "Random Rider" not in "\n".join(written.values())


def test_generate_publishes_per_action() -> None:
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    generate(_config(), browser, client, writer=_capture_writer({}))
    # Stage abs upload + cup abs upload; cup group delete; stage group nothing.
    assert ("stage1-tok", "absolute") in [(t, p) for t, p, _ in client.uploads]
    assert ("cup-tok", "absolute") in [(t, p) for t, p, _ in client.uploads]
    assert ("cup-tok", "group") in client.deletes
    assert len(client.uploads) == 2


def test_generate_no_publish_when_disabled() -> None:
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    generate(_config(), browser, client, writer=_capture_writer({}), publish=False)
    assert client.uploads == []
    assert client.deletes == []


def test_generate_records_roster_failure_and_continues() -> None:
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster(), fail=True)
    written: dict[str, str] = {}
    result = generate(_config(), browser, client, writer=_capture_writer(written))
    assert any("roster fetch failed" in e for e in result.errors)
    # Without a roster everyone is unregistered, but protocols still render.
    assert len(written) == 4


def test_generate_snapshot_roundtrips_through_regeneration() -> None:
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    live = generate(_config(), browser, client, writer=_capture_writer({}))

    replayed: dict[str, str] = {}
    result = generate_from_snapshot(
        _config(), live.raw_snapshot, writer=_capture_writer(replayed)
    )
    assert len(result.outputs) == 4
    stage_abs = next(c for p, c in replayed.items() if "Day_1_absolute" in p)
    assert "Ivan Petrov" in stage_abs
    assert "5:00" in stage_abs


def test_default_writer_writes_to_disk(tmp_path) -> None:
    from app.pipeline import _default_writer

    path = tmp_path / "sub" / "f.html"
    _default_writer(str(path), "hi")
    assert path.read_text(encoding="utf-8") == "hi"


def test_generate_uses_template_file(tmp_path) -> None:
    template = tmp_path / "template.html"
    template.write_text("\n".join(["T-STYLE", *[""] * 10]), encoding="utf-8")
    cfg = _config()
    cfg.template_file = str(template)
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    written: dict[str, str] = {}
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer(written))
    assert any('style="T-STYLE"' in c for c in written.values())


def test_generate_tolerates_bad_date() -> None:
    cfg = _config()
    cfg.stages[0].date_from = "not-a-date"
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    written: dict[str, str] = {}
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer(written))
    assert len(written) == 4


def test_generate_publish_error_recorded_on_output() -> None:
    class _FailingUpload(_FakeClient):
        def upload_protocol(self, *a: object, **k: object) -> None:
            raise SiteApiError("upload down")

    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    client = _FailingUpload(_roster())
    result = generate(_config(), browser, client, writer=_capture_writer({}))
    uploaded = [o for o in result.outputs if o.scope == "absolute"]
    assert any(o.error == "upload down" for o in uploaded)


def test_frozen_stage_reads_the_store_without_scraping() -> None:
    cfg = _config()
    cfg.stages[0].freeze_strava_data = True
    storage = _FakeStorage()
    storage.stores["seg1"] = _store_with(_row("999", "Guest Rider", "4:30"))
    # The browser would return a different rider; freezing must not scrape at all.
    browser = _FakeLeaderboard({"seg1": _row("777", "Fresh Scrape", "5:00")})
    written: dict[str, str] = {}
    generate(
        cfg,
        browser,
        _FakeClient(_roster()),
        writer=_capture_writer(written),
        storage=storage,
    )
    joined = "\n".join(written.values())
    assert "Guest Rider" in joined  # served from the store
    assert "Fresh Scrape" not in joined
    assert browser.filters == []  # nothing was scraped
    assert "Ivan Petrov" in joined  # roster still fetched fresh


def test_unfrozen_stage_scrapes_into_the_store() -> None:
    cfg = _config()  # freeze_strava_data defaults to False
    storage = _FakeStorage()
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    generate(
        cfg,
        browser,
        _FakeClient(_roster()),
        writer=_capture_writer({}),
        storage=storage,
    )
    assert browser.filters  # it scraped
    assert [r.athlete_id for r in storage.stores["seg1"].rows] == ["111"]


def test_store_accumulates_across_runs_and_recovers_the_in_window_effort() -> None:
    # The core scenario: a race-day effort is captured, then Strava only shows a faster
    # PR from another day; the earlier in-window effort survives in the store.
    cfg = _config()
    cfg.stages[0].date_from = "2025-08-05"
    cfg.stages[0].date_to = "2025-08-05"
    storage = _FakeStorage()
    on_the_day = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00", day=5)})
    generate(
        cfg,
        on_the_day,
        _FakeClient(_roster()),
        writer=_capture_writer({}),
        storage=storage,
    )
    # A later run: the board now returns only Ivan's faster PR from the 9th.
    later = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "4:00", day=9)})
    written: dict[str, str] = {}
    generate(
        cfg,
        later,
        _FakeClient(_roster()),
        writer=_capture_writer(written),
        storage=storage,
    )
    stage_abs = next(c for p, c in written.items() if "Day_1_absolute" in p)
    assert "5:00" in stage_abs  # the in-window effort is preserved
    assert "4:00" not in stage_abs  # the out-of-window PR is filtered out


def test_segment_cohorts_do_not_share_a_store() -> None:
    from app.config import Gender

    overall = SegmentConfig("seg1")  # gender overall -> bare id key
    women = SegmentConfig("seg1", gender=Gender.WOMEN)  # different cohort -> own key
    cfg = _config()
    cfg.stages[0].segments = [overall, women]
    storage = _FakeStorage()
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    generate(
        cfg,
        browser,
        _FakeClient(_roster()),
        writer=_capture_writer({}),
        storage=storage,
    )
    # The two cohorts landed in separate stores, not one shared by segment id.
    assert set(storage.stores) == {"seg1", "seg1_F_all"}


def test_empty_scrape_does_not_commit_or_archive() -> None:
    cfg = _config()
    storage = _FakeStorage()
    browser = _FakeLeaderboard({})  # the board returns no rows for seg1
    written: dict[str, str] = {}
    generate(
        cfg,
        browser,
        _FakeClient(_roster()),
        writer=_capture_writer(written),
        storage=storage,
    )
    assert storage.stores == {}  # nothing persisted or archived for an empty scrape
    assert len(written) == 4  # protocols still render (registered riders, no times)


def test_default_date_range_scrapes_multiple_windows() -> None:
    from datetime import date

    from app.config import DateRange

    cfg = _config()
    cfg.stages[0].segments[0].date_range = DateRange.DEFAULT
    cfg.stages[0].date_from = "2026-06-15"
    cfg.stages[0].date_to = "2026-08-15"
    browser = _FakeLeaderboard({"seg1": _row("111", "Ivan Petrov", "5:00")})
    generate(
        cfg,
        browser,
        _FakeClient(_roster()),
        writer=_capture_writer({}),
        today=date(2026, 7, 15),
    )
    ranges = [r for r, _, _ in browser.filters]
    assert "today" in ranges and "this_week" in ranges  # several windows scraped
