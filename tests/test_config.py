"""Tests for configuration dataclasses and JSON round-tripping."""

from app.config import (
    AppConfig,
    CupConfig,
    HttpAction,
    SegmentConfig,
    StageConfig,
)
from app.scoring import CupRule, StageRule


def _rich_config() -> AppConfig:
    return AppConfig(
        site_url="https://site.test",
        strava_login="rider@example.com",
        strava_password="secret",
        strava_cookies=[{"name": "_strava4_session", "value": "abc"}],
        roster_token="roster-tok",
        unregistered_group_name="Others",
        decimals=1,
        show_strava_links=True,
        log_to_file=True,
        template_file="template.html",
        output_dir="out",
        stages=[
            StageConfig(
                name="Day 1",
                segments=[SegmentConfig("111", {"filter": "club"})],
                token="stage1-tok",
                freeze_strava_data=True,
                absolute_action=HttpAction.UPLOAD,
                group_action=HttpAction.DELETE,
                cup_column_label="D1",
            ),
        ],
        cup=CupConfig(
            name="Overall", token="cup-tok", absolute_action=HttpAction.UPLOAD
        ),
    )


def test_default_config_roundtrips() -> None:
    cfg = AppConfig()
    assert AppConfig.from_dict(cfg.to_dict()) == cfg


def test_rich_config_roundtrips() -> None:
    cfg = _rich_config()
    assert AppConfig.from_dict(cfg.to_dict()) == cfg


def test_enums_serialize_as_strings() -> None:
    data = _rich_config().to_dict()
    assert data["stages"][0]["absolute_action"] == "Upload"
    assert data["stages"][0]["rule"] == StageRule.TIME.value
    assert data["cup"]["cup_rule"] == CupRule.SUM_OF_TIMES.value


def test_redacted_config_blanks_password_and_cookies() -> None:
    cfg = _rich_config()
    public = cfg.to_dict(include_secrets=False)
    assert public["strava_password"] == ""
    assert public["strava_cookies"] == []
    # The login and everything else is preserved.
    assert public["strava_login"] == "rider@example.com"
    # With secrets included, the session cookies are kept for the next launch.
    assert cfg.to_dict()["strava_cookies"] == cfg.strava_cookies


def test_from_dict_defaults_missing_keys() -> None:
    cfg = AppConfig.from_dict({"site_url": "https://x", "unknown_key": 1})
    assert cfg.site_url == "https://x"
    assert cfg.unregistered_group_name == "Not registered"
    assert len(cfg.stages) == 1
    assert isinstance(cfg.cup, CupConfig)


def test_bad_http_action_falls_back_to_nothing() -> None:
    stage = StageConfig.from_dict({"absolute_action": "Garbage"})
    assert stage.absolute_action is HttpAction.NOTHING


def test_stage_column_label_falls_back_to_name() -> None:
    assert StageConfig(name="Day 2").column_label() == "Day 2"
    assert StageConfig(name="Day 2", cup_column_label="D2").column_label() == "D2"


def test_roster_token_effective_prefers_explicit_then_cup() -> None:
    assert (
        AppConfig(roster_token="a", cup=CupConfig(token="b")).roster_token_effective()
        == "a"
    )
    assert (
        AppConfig(roster_token="", cup=CupConfig(token="b")).roster_token_effective()
        == "b"
    )


def test_from_dict_empty_stages_gets_one_default() -> None:
    cfg = AppConfig.from_dict({"stages": []})
    assert len(cfg.stages) == 1
