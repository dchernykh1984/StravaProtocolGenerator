"""Persist the config and archive the raw scraped data, both as JSON on disk.

The config is written twice on every save (like StartProtocolMaker's ``spm_backup``): a
current copy that keeps the Strava password so it survives a restart, and a timestamped
history copy with the password redacted. Each generation also snapshots the raw data
fetched from the services, so a protocol can be regenerated later even if Strava stops
serving that day's efforts -- the services are outside our control and not replayable.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.models import LeaderboardRow
from app.store import SegmentStore

CONFIG_NAME = "config.json"
RAWDATA_NAME = "rawdata.json"
SEGMENTS_DIRNAME = "segments"

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_segment_id(segment_id: str) -> str:
    """A filesystem-safe folder/file name for a segment id (guards path traversal)."""
    return _UNSAFE_NAME.sub("_", segment_id) or "unknown"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: str | Path) -> Any | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError, UnicodeDecodeError:
        return None


def save_config(
    config: AppConfig,
    data_dir: str | Path,
    history_dir: str | Path,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    """Write the current config (with secrets) and a redacted timestamped version.

    Returns ``(current_path, version_path)``. The current file keeps the password so the
    next launch restores it; the history file omits it, so backups never leak it.
    """
    current = Path(data_dir) / CONFIG_NAME
    _write_json(current, config.to_dict(include_secrets=True))
    ts = timestamp or _timestamp()
    version = Path(history_dir) / f"config_{ts}.json"
    _write_json(version, config.to_dict(include_secrets=False))
    return current, version


def load_config(path: str | Path) -> AppConfig:
    """Load a saved config, or a fresh default one if it is missing or unreadable."""
    data = _read_json(path)
    if not isinstance(data, dict):
        return AppConfig()
    return AppConfig.from_dict(data)


def save_raw_data(
    snapshot: dict[str, Any],
    data_dir: str | Path,
    history_dir: str | Path,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    """Write the current raw snapshot and a timestamped history copy.

    Mirrors ``save_config``: ``data/rawdata.json`` is the latest snapshot (which frozen
    stages reuse instead of re-scraping) and ``temp/rawdata_<ts>.json`` keeps history.
    """
    current = Path(data_dir) / RAWDATA_NAME
    _write_json(current, snapshot)
    ts = timestamp or _timestamp()
    version = Path(history_dir) / f"rawdata_{ts}.json"
    _write_json(version, snapshot)
    return current, version


def load_raw_data(path: str | Path) -> dict[str, Any]:
    """Load a raw-data snapshot, or an empty dict if it is missing or unreadable."""
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


def list_snapshots(history_dir: str | Path, prefix: str = "rawdata_") -> list[Path]:
    """List archived snapshots (or config versions) oldest-first by filename."""
    directory = Path(history_dir)
    if not directory.exists():
        return []
    return sorted(directory.glob(f"{prefix}*.json"))


def segment_store_path(data_dir: str | Path, segment_id: str) -> Path:
    """Where a segment's accumulating store lives: ``<data_dir>/segments/<id>.json``."""
    return Path(data_dir) / SEGMENTS_DIRNAME / f"{_safe_segment_id(segment_id)}.json"


def load_segment_store(data_dir: str | Path, segment_id: str) -> SegmentStore:
    """Load a segment's accumulated efforts, or an empty store if there are none yet."""
    data = _read_json(segment_store_path(data_dir, segment_id))
    return SegmentStore.from_dict(data if isinstance(data, dict) else None)


def save_segment_store(
    data_dir: str | Path, segment_id: str, store: SegmentStore
) -> Path:
    """Write a segment's accumulated store, returning its path."""
    path = segment_store_path(data_dir, segment_id)
    _write_json(path, store.to_dict())
    return path


def archive_segment(
    history_dir: str | Path,
    segment_id: str,
    rows: list[LeaderboardRow],
    timestamp: str | None = None,
) -> Path:
    """Snapshot one scrape's rows under ``<history_dir>/segments/<id>/<ts>.json``.

    The per-segment tree keeps an audit trail of exactly what Strava served and when, so
    a rider who was missing at generation time can be traced back to the raw data.
    """
    ts = timestamp or _timestamp()
    path = (
        Path(history_dir)
        / SEGMENTS_DIRNAME
        / _safe_segment_id(segment_id)
        / f"{ts}.json"
    )
    _write_json(path, {"rows": [row.to_dict() for row in rows]})
    return path
