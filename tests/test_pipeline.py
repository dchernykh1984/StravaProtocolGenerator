"""End-to-end pipeline tests with a fake browser and fake site client."""

from app.config import AppConfig, CupConfig, HttpAction, SegmentConfig, StageConfig
from app.models import Category, Participant
from app.pipeline import generate, generate_from_snapshot
from app.site_api import ParticipantsResponse, SiteApiError


def _page(aid: str, name: str, result: str, day: int = 5) -> str:
    return (
        '<div id="results"><table><tbody>'
        f'<tr><td>1</td><td><a href="/athletes/{aid}">{name}</a></td>'
        f"<td>Aug {day}, 2025</td><td>{result}</td></tr>"
        "</tbody></table></div>"
    )


class _FakeBrowser:
    """Returns a page keyed by whichever segment id appears in the requested URL."""

    def __init__(self, pages_by_segment: dict[str, str]) -> None:
        self._pages = pages_by_segment
        self._current = ""

    def get(self, url: str) -> None:
        self._current = next((v for k, v in self._pages.items() if k in url), "")

    def page_source(self) -> str:
        return self._current

    def has_next_page(self) -> bool:
        return False

    def go_next_page(self) -> None:
        pass


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
        unregistered_group_name="Not registered",
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
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
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


def test_generate_registered_rider_grouped_by_category() -> None:
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    written: dict[str, str] = {}
    generate(_config(), browser, client, writer=_capture_writer(written))
    stage_grp = next(c for p, c in written.items() if "Day_1_group" in p)
    assert "3.5+" in stage_grp


def test_generate_unregistered_rider_goes_to_named_group() -> None:
    browser = _FakeBrowser({"seg1": _page("999", "Random Rider", "4:30")})
    client = _FakeClient(_roster())
    written: dict[str, str] = {}
    generate(_config(), browser, client, writer=_capture_writer(written))
    stage_grp = next(c for p, c in written.items() if "Day_1_group" in p)
    assert "Not registered" in stage_grp
    assert "Random Rider" in stage_grp


def test_generate_publishes_per_action() -> None:
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    generate(_config(), browser, client, writer=_capture_writer({}))
    # Stage abs upload + cup abs upload; cup group delete; stage group nothing.
    assert ("stage1-tok", "absolute") in [(t, p) for t, p, _ in client.uploads]
    assert ("cup-tok", "absolute") in [(t, p) for t, p, _ in client.uploads]
    assert ("cup-tok", "group") in client.deletes
    assert len(client.uploads) == 2


def test_generate_no_publish_when_disabled() -> None:
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster())
    generate(_config(), browser, client, writer=_capture_writer({}), publish=False)
    assert client.uploads == []
    assert client.deletes == []


def test_generate_records_roster_failure_and_continues() -> None:
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
    client = _FakeClient(_roster(), fail=True)
    written: dict[str, str] = {}
    result = generate(_config(), browser, client, writer=_capture_writer(written))
    assert any("roster fetch failed" in e for e in result.errors)
    # Without a roster everyone is unregistered, but protocols still render.
    assert len(written) == 4


def test_generate_snapshot_roundtrips_through_regeneration() -> None:
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
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
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
    written: dict[str, str] = {}
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer(written))
    assert any('style="T-STYLE"' in c for c in written.values())


def test_generate_tolerates_bad_date() -> None:
    cfg = _config()
    cfg.stages[0].date_from = "not-a-date"
    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
    written: dict[str, str] = {}
    generate(cfg, browser, _FakeClient(_roster()), writer=_capture_writer(written))
    assert len(written) == 4


def test_generate_publish_error_recorded_on_output() -> None:
    class _FailingUpload(_FakeClient):
        def upload_protocol(self, *a: object, **k: object) -> None:
            raise SiteApiError("upload down")

    browser = _FakeBrowser({"seg1": _page("111", "Ivan Petrov", "5:00")})
    client = _FailingUpload(_roster())
    result = generate(_config(), browser, client, writer=_capture_writer({}))
    uploaded = [o for o in result.outputs if o.scope == "absolute"]
    assert any(o.error == "upload down" for o in uploaded)
