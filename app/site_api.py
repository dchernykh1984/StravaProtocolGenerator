"""HTTP client for the cycling-site API: roster download and protocol publishing.

Uses only the standard library (``urllib``), like the FinishProtocolGenerator client.
The network opener is injectable so the client is unit-testable without a server: the
default is ``urllib.request.urlopen``; tests pass a fake that returns canned responses.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import Category, Participant

Opener = Callable[..., Any]


class SiteApiError(Exception):
    """Any failure talking to the site (HTTP status, transport, or bad JSON)."""


@dataclass
class ParticipantsResponse:
    """The roster and its groups for one competition, from ``/participants/``."""

    competition_id: int = 0
    competition_title: str = ""
    categories: list[Category] = field(default_factory=list)
    participants: list[Participant] = field(default_factory=list)


class SiteApiClient:
    """Thin wrapper over the site's token-authenticated JSON/multipart endpoints."""

    def __init__(
        self,
        base_url: str,
        opener: Opener = urllib.request.urlopen,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._opener = opener
        self.timeout = timeout

    def _read_json(self, request: urllib.request.Request | str) -> dict[str, Any]:
        try:
            with self._opener(request, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SiteApiError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise SiteApiError(f"Connection error: {exc.reason}") from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise SiteApiError(f"Invalid response: {exc}") from exc

    def _post(self, url: str, data: bytes, content_type: str) -> int:
        request = urllib.request.Request(  # noqa: S310
            url, data=data, headers={"Content-Type": content_type}, method="POST"
        )
        try:
            with self._opener(request, timeout=self.timeout) as resp:
                status = int(getattr(resp, "status", 0))
                if not 200 <= status < 300:
                    raise SiteApiError(f"HTTP {status} from {url}")
                return status
        except urllib.error.HTTPError as exc:
            raise SiteApiError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise SiteApiError(f"Connection error: {exc.reason}") from exc

    def fetch_participants(self, token: str) -> ParticipantsResponse:
        """Download the registered roster and categories for a competition token."""
        url = (
            self.base_url
            + "/api/v1/participants/?"
            + urllib.parse.urlencode({"competition_token": token})
        )
        data = self._read_json(url)
        return ParticipantsResponse(
            competition_id=int(data.get("competition_id", 0)),
            competition_title=data.get("competition_title", ""),
            categories=[Category.from_api(c) for c in data.get("categories", [])],
            participants=[
                Participant.from_api(p) for p in data.get("participants", [])
            ],
        )

    def upload_protocol(
        self,
        token: str,
        protocol_type: str,
        html_path: str,
        is_live: bool = True,
        stage_label: str = "",
    ) -> None:
        """Publish a protocol HTML file to the site as ``absolute`` or ``group``."""
        path = Path(html_path)
        if not path.exists():
            raise SiteApiError(f"File not found: {html_path}")
        body, content_type = _multipart(
            fields={
                "competition_token": token,
                "protocol_type": protocol_type,
                "is_live": "true" if is_live else "false",
                "stage_label": stage_label,
            },
            file_field="html_file",
            filename=path.name,
            file_content=path.read_bytes(),
        )
        self._post(self.base_url + "/api/v1/protocols/upload/", body, content_type)

    def delete_protocol(self, token: str, protocol_type: str) -> None:
        """Remove a published protocol so its live-broadcast link disappears."""
        body = urllib.parse.urlencode(
            {"competition_token": token, "protocol_type": protocol_type}
        ).encode()
        self._post(
            self.base_url + "/api/v1/protocols/delete/",
            body,
            "application/x-www-form-urlencoded",
        )

    def upload_live_stats(self, token: str, stats: dict[str, dict[str, str]]) -> int:
        """Push the per-competitor live-standings snapshot; returns the stored count."""
        body = json.dumps({"competition_token": token, "stats": stats}).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310
            self.base_url + "/api/v1/live-stats/",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        data = self._read_json(request)
        return int(data.get("count", len(stats)))


def _multipart(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    file_content: bytes,
) -> tuple[bytes, str]:
    """Encode text fields and a file as multipart/form-data; return (body, type)."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}";'
            f' filename="{filename}"\r\n'
            "Content-Type: text/html\r\n\r\n"
        ).encode()
        + file_content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
