"""Tests for configuration dataclasses and JSON round-tripping."""

from app.config import (
    AppConfig,
    CupConfig,
    DateRange,
    FilterType,
    Gender,
    HttpAction,
    SegmentConfig,
    StageConfig,
)
from app.models import RaceInfo
from app.scoring import CupRule, StageRule


def _rich_config() -> AppConfig:
    return AppConfig(
        site_url="https://site.test",
        strava_cookies=[{"name": "_strava4_session", "value": "abc"}],
        roster_token="roster-tok",
        decimals=1,
        show_strava_links=True,
        log_to_file=True,
        template_file="template.html",
        output_dir="out",
        stages=[
            StageConfig(
                name="Day 1",
                segments=[
                    SegmentConfig(
                        "111",
                        date_range=DateRange.THIS_WEEK,
                        gender=Gender.MEN,
                        filter_type=FilterType.FOLLOWING,
                    )
                ],
                token="stage1-tok",
                freeze_strava_data=True,
                absolute_action=HttpAction.UPLOAD,
                group_action=HttpAction.DELETE,
                cup_column_label="D1",
                disable_dnf=True,
                group_label="Group",
                show_gap=False,
                gap_label="(d)",
                show_year=False,
                unregistered_group_name="Others",
                show_unregistered=False,
                race_info=RaceInfo(referee="Day-1 ref", weather="Rain"),
            ),
        ],
        cup=CupConfig(
            name="Overall",
            token="cup-tok",
            absolute_action=HttpAction.UPLOAD,
            disable_dnf=True,
            group_label="Cat",
            show_gap=False,
            show_stage_gap=False,
            stage_gap_label="(sg)",
            show_stage_count=False,
            stage_count_label="(cnt)",
            show_city=False,
            unregistered_group_name="Guests",
            show_unregistered=False,
            race_info=RaceInfo(organizer="UBT", sponsor="<b>x</b>"),
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


def test_redacted_config_blanks_cookies() -> None:
    cfg = _rich_config()
    public = cfg.to_dict(include_secrets=False)
    assert public["strava_cookies"] == []
    # Everything non-secret is preserved.
    assert public["site_url"] == "https://site.test"
    # With secrets included, the session cookies are kept for the next launch.
    assert cfg.to_dict()["strava_cookies"] == cfg.strava_cookies


def test_from_dict_defaults_missing_keys() -> None:
    cfg = AppConfig.from_dict({"site_url": "https://x", "unknown_key": 1})
    assert cfg.site_url == "https://x"
    assert cfg.stages[0].unregistered_group_name == "Not registered"
    assert cfg.cup.unregistered_group_name == "Not registered"
    assert len(cfg.stages) == 1
    assert isinstance(cfg.cup, CupConfig)


def test_bad_http_action_falls_back_to_nothing() -> None:
    stage = StageConfig.from_dict({"absolute_action": "Garbage"})
    assert stage.absolute_action is HttpAction.NOTHING


def test_bad_segment_filters_fall_back_to_defaults() -> None:
    seg = SegmentConfig.from_dict(
        {
            "segment_id": "5",
            "date_range": "since_the_dawn_of_time",
            "gender": "aliens",
            "filter_type": "psychic",
        }
    )
    assert seg.date_range is DateRange.TODAY
    assert seg.gender is Gender.OVERALL
    assert seg.filter_type is FilterType.ALL


def test_stage_tolerates_null_race_info_block() -> None:
    stage = StageConfig.from_dict({"name": "D", "race_info": None})
    assert stage.race_info == RaceInfo()


def test_from_dict_tolerates_null_nested_blocks() -> None:
    # A hand-edited config with null blocks must load (not crash), using defaults.
    cfg = AppConfig.from_dict({"stages": [None], "cup": None})
    assert cfg.stages == [StageConfig()]
    assert cfg.cup == CupConfig()
    assert SegmentConfig.from_dict(None) == SegmentConfig()
    assert AppConfig.from_dict(None) == AppConfig()


def test_segment_defaults_to_today_overall_all() -> None:
    seg = SegmentConfig()
    assert (seg.date_range, seg.gender, seg.filter_type) == (
        DateRange.TODAY,
        Gender.OVERALL,
        FilterType.ALL,
    )
    assert SegmentConfig.from_dict({"segment_id": "5"}).date_range is DateRange.TODAY


def test_segment_filters_roundtrip() -> None:
    seg = SegmentConfig(
        "5",
        date_range=DateRange.THIS_YEAR,
        gender=Gender.WOMEN,
        filter_type=FilterType.MY_RESULTS,
    )
    assert SegmentConfig.from_dict(seg.to_dict()) == seg


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
