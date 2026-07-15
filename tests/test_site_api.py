"""Tests for the cycling-site API client, driven by a fake network opener."""

import json
import urllib.error
from typing import Any

import pytest

from app.site_api import SiteApiClient, SiteApiError


class _FakeResp:
    def __init__(self, body: bytes = b"", status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakeOpener:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _client(response: Any) -> tuple[SiteApiClient, _FakeOpener]:
    opener = _FakeOpener(response)
    return SiteApiClient("https://site.test/", opener=opener), opener


def test_fetch_participants_parses_roster() -> None:
    payload = {
        "competition_id": 250,
        "competition_title": "Spicy Ride",
        "categories": [{"id": 1, "name": "3.5+"}],
        "participants": [
            {
                "id": 5,
                "first_name": "Ivan",
                "last_name": "Petrov",
                "participant_names": "Petrov Ivan",
                "category_id": 1,
                "category_name": "3.5+",
                "additional_info": "athletes/999",
            }
        ],
    }
    client, opener = _client(_FakeResp(json.dumps(payload).encode()))
    resp = client.fetch_participants("tok-123")
    assert resp.competition_id == 250
    assert resp.categories[0].name == "3.5+"
    assert resp.participants[0].display_name == "Petrov Ivan"
    assert "competition_token=tok-123" in opener.requests[0]


def test_fetch_participants_http_error_raises() -> None:
    err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
    client, _ = _client(err)
    with pytest.raises(SiteApiError, match="401"):
        client.fetch_participants("bad")


def test_fetch_participants_connection_error_raises() -> None:
    client, _ = _client(urllib.error.URLError("boom"))
    with pytest.raises(SiteApiError, match="Connection error"):
        client.fetch_participants("tok")


def test_fetch_participants_bad_json_raises() -> None:
    client, _ = _client(_FakeResp(b"not json"))
    with pytest.raises(SiteApiError, match="Invalid response"):
        client.fetch_participants("tok")


def test_delete_protocol_connection_error_raises() -> None:
    client, _ = _client(urllib.error.URLError("down"))
    with pytest.raises(SiteApiError, match="Connection error"):
        client.delete_protocol("tok", "absolute")


def test_upload_protocol_sends_multipart(tmp_path) -> None:
    html = tmp_path / "prot.html"
    html.write_text("<html><body>ok</body></html>", encoding="utf-8")
    client, opener = _client(_FakeResp(b'{"id": 1, "file_hash": "x"}', status=201))
    client.upload_protocol("tok", "absolute", str(html), is_live=True, stage_label="S1")
    request = opener.requests[0]
    assert request.full_url.endswith("/api/v1/protocols/upload/")
    assert request.method == "POST"
    body = request.data
    assert b'name="competition_token"' in body
    assert b"absolute" in body
    assert b'name="stage_label"' in body and b"S1" in body
    assert b"<html><body>ok</body></html>" in body


def test_upload_protocol_missing_file_raises(tmp_path) -> None:
    client, _ = _client(_FakeResp(status=201))
    with pytest.raises(SiteApiError, match="File not found"):
        client.upload_protocol("tok", "absolute", str(tmp_path / "nope.html"))


def test_upload_protocol_non_2xx_raises(tmp_path) -> None:
    html = tmp_path / "p.html"
    html.write_text("<html></html>", encoding="utf-8")
    client, _ = _client(_FakeResp(status=500))
    with pytest.raises(SiteApiError, match="500"):
        client.upload_protocol("tok", "group", str(html))


def test_upload_protocol_http_error_raises(tmp_path) -> None:
    html = tmp_path / "p.html"
    html.write_text("<html></html>", encoding="utf-8")
    err = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)  # type: ignore[arg-type]
    client, _ = _client(err)
    with pytest.raises(SiteApiError, match="403"):
        client.upload_protocol("tok", "absolute", str(html))


def test_delete_protocol_posts_form() -> None:
    client, opener = _client(_FakeResp(status=200))
    client.delete_protocol("tok", "group")
    request = opener.requests[0]
    assert request.full_url.endswith("/api/v1/protocols/delete/")
    assert b"competition_token=tok" in request.data
    assert b"protocol_type=group" in request.data


def test_upload_live_stats_returns_count() -> None:
    client, opener = _client(_FakeResp(b'{"count": 2}'))
    count = client.upload_live_stats("tok", {"1": {"place": "1"}})
    assert count == 2
    body = json.loads(opener.requests[0].data)
    assert body["competition_token"] == "tok"
    assert body["stats"]["1"]["place"] == "1"
