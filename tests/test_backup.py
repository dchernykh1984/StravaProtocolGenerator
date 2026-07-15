"""Tests for config persistence and raw-data snapshot archiving."""

import json

from app.backup import (
    list_snapshots,
    load_config,
    load_raw_data,
    save_config,
    save_raw_data,
)
from app.config import AppConfig


def test_save_config_writes_current_and_redacted_version(tmp_path) -> None:
    cfg = AppConfig(strava_login="me", strava_password="secret", site_url="https://x")
    data_dir = tmp_path / "data"
    history_dir = tmp_path / "history"
    current, version = save_config(
        cfg, data_dir, history_dir, timestamp="20260715_101112"
    )

    current_data = json.loads(current.read_text(encoding="utf-8"))
    assert current_data["strava_password"] == "secret"  # current keeps the password

    version_data = json.loads(version.read_text(encoding="utf-8"))
    assert version_data["strava_password"] == ""  # history redacts it
    assert version_data["strava_login"] == "me"
    assert version.name == "config_20260715_101112.json"


def test_load_config_roundtrips_current(tmp_path) -> None:
    cfg = AppConfig(site_url="https://site", strava_login="rider")
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
    path = save_raw_data(snapshot, tmp_path, timestamp="20260715_120000")
    assert path.name == "rawdata_20260715_120000.json"
    assert load_raw_data(path) == snapshot


def test_load_raw_data_missing_returns_empty(tmp_path) -> None:
    assert load_raw_data(tmp_path / "missing.json") == {}


def test_list_snapshots_sorted(tmp_path) -> None:
    save_raw_data({"a": 1}, tmp_path, timestamp="20260101_000000")
    save_raw_data({"b": 2}, tmp_path, timestamp="20260102_000000")
    names = [p.name for p in list_snapshots(tmp_path)]
    assert names == ["rawdata_20260101_000000.json", "rawdata_20260102_000000.json"]


def test_list_snapshots_missing_dir_is_empty(tmp_path) -> None:
    assert list_snapshots(tmp_path / "nope") == []


def test_save_config_default_timestamp(tmp_path) -> None:
    # Without an explicit timestamp a version file is still produced.
    _, version = save_config(AppConfig(), tmp_path, tmp_path)
    assert version.exists()
    assert version.name.startswith("config_")
