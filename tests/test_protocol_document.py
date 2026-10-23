"""Stage and cup protocols as data: what the HTML shows, in the site schema."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import jsonschema
import pytest

from app.config import (
    AppConfig,
    CupConfig,
    HttpAction,
    ProtocolFormat,
    SegmentConfig,
    StageConfig,
)
from app.models import Category, LeaderboardRow, Participant
from app.pipeline import generate, generate_from_snapshot
from app.site_api import ParticipantsResponse, SiteApiClient, _multipart
from app.timeparse import parse_time

# "km/h" in Russian, from code points: source files stay ASCII.
KMH_RU = "".join(map(chr, (0x43A, 0x43C, 0x2F, 0x447)))
SCHEMA = json.loads(
    (Path(__file__).parent / "fixtures" / "protocol-document-v1.json").read_text()
)


def check_document_rules(document: dict) -> None:
    """What the site checks beyond the JSON Schema: ids, references and the budget."""
    groups = [g["id"] for g in document.get("groups", [])]
    assert len(groups) == len(set(groups)) and "" not in groups
    cells = 0
    for section in document["sections"]:
        ids = [c["id"] for c in section["columns"]]
        assert len(ids) == len(set(ids))
        assert section.get("group") in (None, *groups)
        for row in section["rows"]:
            assert set(row["cells"]) <= set(ids)
            assert row.get("group") in (None, *groups)
        cells += len(ids) * len(section["rows"])
    assert cells <= 100_000


def _row(aid: str, name: str, result: str, seg: str) -> LeaderboardRow:
    return LeaderboardRow(
        athlete_name=name,
        athlete_id=aid,
        raw_result=result,
        result_seconds=parse_time(result),
        date="Aug 5, 2025",
        athlete_url=f"https://www.strava.com/athletes/{aid}",
        attempt_url=f"https://www.strava.com/activities/{aid}-{seg}",
        avg_speed=10.0,
        avg_hr=150.0,
    )


class _Board:
    def __init__(self, rows: dict[str, list[LeaderboardRow]]) -> None:
        self._rows = rows

    def page(
        self, segment_id, page, date_range="", gender="overall", filter_type="all"
    ):
        rows = self._rows.get(segment_id, []) if page == 1 else []
        return rows, len(rows)


class _Client:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Any, bool]] = []
        self.refuse = ""

    def fetch_participants(self, token: str) -> ParticipantsResponse:
        def rider(pid, first, last, cat_id, cat, aid):
            return Participant(
                id=pid,
                first_name=first,
                last_name=last,
                participant_names=f"{first} {last}",
                category_id=cat_id,
                category_name=cat,
                additional_info=f"athletes/{aid}",
                birth_year=1990,
                team="Team",
                city="Almaty",
            )

        return ParticipantsResponse(
            competition_id=1,
            categories=[Category(id=1, name="M30"), Category(id=2, name="M40")],
            participants=[
                rider(1, "Ivan", "Petrov", 1, "M30", "111"),
                rider(2, "Oleg", "Kim", 2, "M40", "222"),
                rider(3, "Ann", "Lee", 1, "M30", "333"),
            ],
        )

    def upload_protocol(
        self,
        token,
        protocol_type,
        html_path,
        is_live=True,
        stage_label="",
        document=None,
        send_html=True,
    ) -> str:
        self.sent.append((token, protocol_type, document, send_html))
        return self.refuse

    def delete_protocol(self, token, protocol_type) -> None:
        pass


def _board() -> _Board:
    return _Board(
        {
            "s1": [
                _row("222", "Oleg Kim", "4:50", "s1"),
                _row("111", "Ivan Petrov", "5:00", "s1"),
                _row("999", "Guest Rider", "5:10", "s1"),
            ],
            "s2": [
                _row("111", "Ivan Petrov", "6:00", "s2"),
                _row("999", "Guest Rider", "6:30", "s2"),
            ],
        }
    )


def _config(fmt: ProtocolFormat = ProtocolFormat.BOTH) -> AppConfig:
    def stage(name, seg, token):
        return StageConfig(
            name=name,
            segments=[SegmentConfig(seg)],
            token=token,
            absolute_action=HttpAction.UPLOAD,
            group_action=HttpAction.UPLOAD,
            unregistered_group_name="Stage guests",
            show_gap=True,
        )

    return AppConfig(
        roster_token="cup",
        output_dir="out",
        show_strava_links=True,
        show_strava_statistics=True,
        protocol_format=fmt,
        stages=[stage("Day 1", "s1", "t1"), stage("Day 2", "s2", "t2")],
        cup=CupConfig(
            name="Cup",
            token="cup",
            absolute_action=HttpAction.UPLOAD,
            group_action=HttpAction.UPLOAD,
            unregistered_group_name="Cup guests",
            show_gap=True,
            show_stage_gap=True,
            show_stage_count=True,
        ),
    )


def _run(fmt: ProtocolFormat = ProtocolFormat.BOTH, client: _Client | None = None):
    client = client or _Client()
    written: dict[str, str] = {}
    result = generate(
        _config(fmt), _board(), client, writer=lambda p, c: written.__setitem__(p, c)
    )
    return result, client, written


def _documents(client: _Client) -> dict[tuple[str, str], dict]:
    return {(token, kind): doc for token, kind, doc, _ in client.sent if doc}


def test_every_document_matches_the_schema_and_the_sites_rules():
    _, client, _ = _run()
    documents = _documents(client)
    assert len(documents) == 6  # two stages and the cup, absolute and group
    for document in documents.values():
        jsonschema.validate(document, SCHEMA)
        check_document_rules(document)


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[str]] = []
        self._row = 0
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
            self._row = 0
        elif tag == "tr":
            self._row += 1
        elif tag == "td" and self._row > 1:  # the first row is the header
            self._cell = [""]
        elif tag == "br" and self._cell is not None:
            self._cell.append("")

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None:
            self.tables[-1].extend(p for p in self._cell if p.strip())
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell[-1] += data


def _tokens(texts: list[str]) -> list[str]:
    return sorted(t for text in texts for t in re.findall(r"[^\s()]+", text))


def _texts(section: dict) -> list[str]:
    out = []
    for row in section["rows"]:
        for cell in row["cells"].values():
            if isinstance(cell, str):
                out.append(cell)
            else:
                out.append(cell["text"])
                out.extend(cell.get("sub", []))
    return out


@pytest.mark.parametrize(
    ("token", "kind", "file_part"),
    [
        ("t1", "absolute", "Day_1_absolute"),
        ("t1", "group", "Day_1_group"),
        ("cup", "absolute", "Cup_absolute"),
        ("cup", "group", "Cup_group"),
    ],
)
def test_document_holds_every_value_the_html_shows(token, kind, file_part):
    _, client, written = _run()
    html = next(c for p, c in written.items() if file_part in p)
    parser = _Tables()
    parser.feed(html)
    document = _documents(client)[(token, kind)]
    assert len(parser.tables) == len(document["sections"])
    for cells, section in zip(parser.tables, document["sections"], strict=True):
        assert _tokens(cells) == _tokens(_texts(section))


def test_links_to_strava_stay():
    _, client, _ = _run()
    stage = _documents(client)[("t1", "absolute")]
    ivan = next(
        r
        for r in stage["sections"][0]["rows"]
        if r["cells"]["name"]["text"] == "Ivan Petrov"
    )
    assert ivan["cells"]["name"]["url"] == "https://www.strava.com/athletes/111"
    assert ivan["cells"]["result"]["url"] == "https://www.strava.com/activities/111-s1"
    cup = _documents(client)[("cup", "absolute")]
    ivan = next(
        r
        for r in cup["sections"][0]["rows"]
        if r["cells"]["name"]["text"] == "Ivan Petrov"
    )
    assert ivan["cells"]["stage2"]["url"] == "https://www.strava.com/activities/111-s2"


def test_statistics_columns_come_with_their_units():
    _, client, _ = _run()
    stage = _documents(client)[("t1", "group")]
    ids = [c["id"] for c in stage["sections"][0]["columns"]]
    assert "speed" in ids and "hr" in ids and "power" not in ids
    row = stage["sections"][0]["rows"][0]
    assert row["cells"]["speed"].endswith(("km/h", KMH_RU))


@pytest.mark.parametrize("from_snapshot", [False, True])
def test_absolute_groups_follow_the_rows_and_each_protocols_guest_name(from_snapshot):
    result, client, _ = _run()
    if from_snapshot:
        client = _Client()
        generate_from_snapshot(
            _config(),
            result.raw_snapshot,
            client,
            writer=lambda p, c: None,
            publish=True,
        )
    documents = _documents(client)
    stage = documents[("t1", "absolute")]
    cup = documents[("cup", "absolute")]
    assert [g["id"] for g in stage["groups"]] == ["M30", "M40", "Stage guests"]
    assert [g["id"] for g in cup["groups"]] == ["M30", "M40", "Cup guests"]
    by_name = {
        r["cells"]["name"]["text"]: r["group"] for r in stage["sections"][0]["rows"]
    }
    # Ann Lee is registered but rode neither segment: she is listed (DNF) in her group.
    assert by_name == {
        "Oleg Kim": "M40",
        "Ivan Petrov": "M30",
        "Guest Rider": "Stage guests",
        "Ann Lee": "M30",
    }
    guest = next(
        r
        for r in cup["sections"][0]["rows"]
        if r["cells"]["name"]["text"] == "Guest Rider"
    )
    assert guest["group"] == "Cup guests"
    assert "group" in [c["id"] for c in stage["sections"][0]["columns"]]


def test_absolute_groups_without_a_group_column():
    config = _config()
    config.stages[0].show_group = False
    client = _Client()
    generate(config, _board(), client, writer=lambda p, c: None)
    stage = _documents(client)[("t1", "absolute")]
    assert "group" not in [c["id"] for c in stage["sections"][0]["columns"]]
    assert all("group" in r for r in stage["sections"][0]["rows"])


def test_hidden_unregistered_riders_leave_no_guest_group():
    config = _config()
    config.stages[0].show_unregistered = False
    client = _Client()
    generate(config, _board(), client, writer=lambda p, c: None)
    stage = _documents(client)[("t1", "absolute")]
    assert [g["id"] for g in stage["groups"]] == ["M30", "M40"]


def test_group_protocol_tables_carry_their_group():
    _, client, _ = _run()
    group = _documents(client)[("t1", "group")]
    assert [s.get("group") for s in group["sections"]] == ["M30", "M40", "Stage guests"]


@pytest.mark.parametrize(
    ("fmt", "with_data", "with_html"),
    [
        (ProtocolFormat.BOTH, True, True),
        (ProtocolFormat.HTML, False, True),
        (ProtocolFormat.DATA, True, False),
    ],
)
def test_format_decides_what_goes_to_the_site(fmt, with_data, with_html):
    _, client, _ = _run(fmt)
    assert all((doc is not None) == with_data for _, _, doc, _ in client.sent)
    assert all(send_html == with_html for _, _, _, send_html in client.sent)


def test_refused_data_is_a_warning_and_the_protocol_is_published():
    client = _Client()
    client.refuse = "schema 2"
    result, _, _ = _run(client=client)
    assert all(o.published and "schema 2" in o.warning for o in result.outputs)


def test_a_failing_build_still_sends_the_html(monkeypatch):
    import app.pipeline as pipeline

    def boom(*args, **kwargs):
        raise RuntimeError("bad data")

    monkeypatch.setattr(pipeline, "build_stage_document", boom)
    result, client, _ = _run(ProtocolFormat.DATA)
    stage_sends = [s for s in client.sent if s[0] == "t1"]
    assert stage_sends and all(doc is None and html for _, _, doc, html in stage_sends)
    stage_outputs = [o for o in result.outputs if o.kind == "stage"]
    assert all("bad data" in o.warning and o.published for o in stage_outputs)


def test_format_survives_save_and_load():
    config = _config(ProtocolFormat.DATA)
    assert AppConfig.from_dict(config.to_dict()).protocol_format is ProtocolFormat.DATA
    assert AppConfig.from_dict({}).protocol_format is ProtocolFormat.BOTH
    assert AppConfig.from_dict({"protocol_format": "bad"}).protocol_format is (
        ProtocolFormat.BOTH
    )


def _api(answer: bytes) -> tuple[SiteApiClient, dict]:
    sent: dict = {}
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = 200
    resp.read.return_value = answer

    def opener(request, timeout):
        sent["body"] = request.data
        return resp

    return SiteApiClient("https://site.test", opener=opener), sent


def test_upload_sends_both_parts_and_reports_a_refused_document(tmp_path):
    html = tmp_path / "p.html"
    html.write_text("<html></html>", encoding="utf-8")
    client, sent = _api(b'{"id": 1, "document_error": "too big"}')
    warning = client.upload_protocol("tok", "group", str(html), document={"schema": 1})
    assert warning == "too big"
    assert b'name="html_file"; filename="p.html"' in sent["body"]
    assert b'name="document"; filename="protocol.json"' in sent["body"]


def test_upload_of_data_alone_and_an_older_sites_answer(tmp_path):
    client, sent = _api(b"OK")
    warning = client.upload_protocol(
        "tok",
        "group",
        str(tmp_path / "missing.html"),
        document={"a": 1},
        send_html=False,
    )
    assert warning == ""
    assert b'name="html_file"' not in sent["body"]


def test_upload_with_nothing_is_refused(tmp_path):
    from app.site_api import SiteApiError

    client, _ = _api(b"{}")
    with pytest.raises(SiteApiError, match="Nothing to upload"):
        client.upload_protocol("tok", "group", "x.html", send_html=False)


def test_multipart_carries_each_file_with_its_type():
    body, content_type = _multipart(
        {"a": "1"}, [("f", "x.json", "application/json", b"{}")]
    )
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b"Content-Type: application/json" in body
