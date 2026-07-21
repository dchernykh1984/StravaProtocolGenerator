"""Tests for app.paths base-dir resolution."""

from __future__ import annotations

from pathlib import Path

from app import paths


def test_base_dir_in_development_is_cwd() -> None:
    assert paths.base_dir() == Path.cwd()


def test_app_path_joins_under_base_dir(monkeypatch) -> None:
    monkeypatch.setattr(paths, "base_dir", lambda: Path("/opt/app"))
    assert paths.app_path("data", "config.json") == Path("/opt/app/data/config.json")


def test_base_dir_frozen_uses_executable_folder(monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        paths.sys, "executable", "/downloads/StravaProtocolGenerator", raising=False
    )
    assert paths.base_dir() == Path("/downloads")


def test_base_dir_frozen_macos_app_uses_bundle_parent(monkeypatch) -> None:
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        paths.sys,
        "executable",
        "/Applications/StravaProtocolGenerator.app/Contents/MacOS/StravaProtocolGenerator",
        raising=False,
    )
    assert paths.base_dir() == Path("/Applications")
