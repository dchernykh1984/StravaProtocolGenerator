"""Tests for config persistence and raw-data snapshot archiving."""

import json

from app.backup import (
    FileSegmentStorage,
    archive_segment,
    list_snapshots,
    load_config,
    load_raw_data,
    load_segment_store,
    save_config,
    save_raw_data,
    save_segment_store,
)
from app.config import AppConfig
from app.models import LeaderboardRow
from app.store import SegmentStore


def test_save_config_writes_current_and_redacted_version(tmp_path) -> None:
    cookies = [{"name": "_strava4_session", "value": "secret"}]
    cfg = AppConfig(strava_cookies=cookies, site_url="https://x")
    data_dir = tmp_path / "data"
    history_dir = tmp_path / "history"
    current, version = save_config(
        cfg, data_dir, history_dir, timestamp="20260715_101112"
    )

    current_data = json.loads(current.read_text(encoding="utf-8"))
    assert current_data["strava_cookies"] == cookies  # current keeps the session

    version_data = json.loads(version.read_text(encoding="utf-8"))
    assert version_data["strava_cookies"] == []  # history redacts it
    assert version_data["site_url"] == "https://x"
    assert version.name == "config_20260715_101112.json"


def test_load_config_roundtrips_current(tmp_path) -> None:
    cfg = AppConfig(site_url="https://site", roster_token="rider")
    current, _ = save_config(cfg, tmp_path, tmp_path, timestamp="t1")
    assert load_config(current) == cfg


def test_load_config_missing_returns_default(tmp_path) -> None:
    assert load_config(tmp_path / "nope.json") == AppConfig()


def test_load_config_invalid_json_returns_default(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_config(bad) == AppConfig()


def test_load_config_non_dict_json_returns_default(tmp_path) -> None:
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_config(arr) == AppConfig()


def test_save_and_load_raw_data(tmp_path) -> None:
    snapshot = {"stages": [{"segments": [[{"athlete_id": "1"}]]}]}
    data_dir, history_dir = tmp_path / "data", tmp_path / "temp"
    current, version = save_raw_data(
        snapshot, data_dir, history_dir, timestamp="20260715_120000"
    )
    assert current.name == "rawdata.json"
    assert version.name == "rawdata_20260715_120000.json"
    assert load_raw_data(current) == snapshot
    assert load_raw_data(version) == snapshot


def test_load_raw_data_missing_returns_empty(tmp_path) -> None:
    assert load_raw_data(tmp_path / "missing.json") == {}


def test_list_snapshots_sorted(tmp_path) -> None:
    save_raw_data({"a": 1}, tmp_path, tmp_path, timestamp="20260101_000000")
    save_raw_data({"b": 2}, tmp_path, tmp_path, timestamp="20260102_000000")
    names = [p.name for p in list_snapshots(tmp_path)]
    assert names == ["rawdata_20260101_000000.json", "rawdata_20260102_000000.json"]


def test_list_snapshots_missing_dir_is_empty(tmp_path) -> None:
    assert list_snapshots(tmp_path / "nope") == []


def test_save_config_default_timestamp(tmp_path) -> None:
    # Without an explicit timestamp a version file is still produced.
    _, version = save_config(AppConfig(), tmp_path, tmp_path)
    assert version.exists()
    assert version.name.startswith("config_")


def _row(aid: str, seconds: float) -> LeaderboardRow:
    return LeaderboardRow(
        athlete_name=f"Rider {aid}",
        athlete_id=aid,
        raw_result="",
        result_seconds=seconds,
        date="2026-07-15T08:00:00Z",
        attempt_url=f"https://www.strava.com/activities/{aid}",
    )


def test_segment_store_round_trips_on_disk(tmp_path) -> None:
    store = SegmentStore()
    store.merge([_row("1", 300.0), _row("2", 320.0)])
    path = save_segment_store(tmp_path, "41792182", store)
    assert path.parent.name == "segments"
    assert load_segment_store(tmp_path, "41792182") == store


def test_load_segment_store_missing_is_empty(tmp_path) -> None:
    assert load_segment_store(tmp_path, "999").rows == []


def test_archive_segment_writes_a_tree_by_segment_id(tmp_path) -> None:
    path = archive_segment(
        tmp_path, "41792182", [_row("1", 300.0)], timestamp="20260715_101112"
    )
    assert path.name == "20260715_101112.json"
    assert path.parent.name == "41792182"
    assert path.parent.parent.name == "segments"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["rows"][0]["athlete_id"] == "1"


def test_unsafe_segment_id_is_sanitised(tmp_path) -> None:
    path = save_segment_store(tmp_path, "../evil id", SegmentStore())
    assert path.name == "_evil_id.json"  # unsafe runs collapse to one underscore
    assert path.parent == tmp_path / "segments"


def test_file_segment_storage_commits_store_and_archive(tmp_path) -> None:
    data_dir = tmp_path / "data"
    history_dir = tmp_path / "history"
    storage = FileSegmentStorage(data_dir, history_dir)
    assert storage.load("55").rows == []  # empty until committed

    store = SegmentStore()
    scraped = [_row("1", 300.0)]
    store.merge(scraped)
    storage.commit("55", store, scraped)

    assert storage.load("55") == store  # persisted to data/
    archives = list((history_dir / "segments" / "55").glob("*.json"))
    assert len(archives) == 1  # one scrape archived under the segment tree
