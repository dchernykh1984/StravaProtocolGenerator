"""Application configuration: stages, the cup, and global settings, with JSON I/O.

Everything the UI edits lives here as plain dataclasses that round-trip through dicts,
so the config saves as JSON and restores forward-compatibly (unknown keys ignored,
missing keys defaulted). ``AppConfig.to_dict`` can redact the Strava password, which the
backup layer uses to keep it out of the versioned history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.models import RaceInfo
from app.scoring import CupRule, StageRule


class HttpAction(StrEnum):
    """What to do with a protocol on the site (as in FinishProtocolGenerator)."""

    NOTHING = "Nothing"
    UPLOAD = "Upload"
    DELETE = "Delete"


class DateRange(StrEnum):
    """Strava's server-side leaderboard window preset (its ``date_range`` param).

    This is essential, not cosmetic: on a popular segment the all-time board returns
    each rider's best-ever effort, so a rider who rode today but was faster before never
    appears with today's time. Asking Strava for ``today`` (or the week/month/year)
    returns the efforts from that window instead. ``ALL_TIME`` omits the param.

    ``DEFAULT`` is not sent to Strava: it tells the app to pick the window(s) itself
    from the stage's date range and today's date (see ``app.windows``), scraping wider
    windows to backfill an already-finished period.
    """

    DEFAULT = "default"
    TODAY = "today"
    THIS_WEEK = "this_week"
    THIS_MONTH = "this_month"
    THIS_YEAR = "this_year"
    ALL_TIME = "all_time"


class Gender(StrEnum):
    """Strava's leaderboard ``gender`` filter (``overall`` combines everyone)."""

    OVERALL = "overall"
    MEN = "M"
    WOMEN = "F"


class FilterType(StrEnum):
    """Strava's leaderboard ``filter_type`` (``all`` is the public overall board)."""

    ALL = "all"
    FOLLOWING = "following"
    MY_RESULTS = "my_results"


def _coerce_action(value: Any) -> HttpAction:
    try:
        return HttpAction(value)
    except ValueError:
        return HttpAction.NOTHING


def _coerce_enum(enum: type[Any], value: Any, default: Any) -> Any:
    try:
        return enum(value)
    except ValueError:
        return default


@dataclass
class SegmentConfig:
    """One Strava segment scraped for a stage: its id and leaderboard filters.

    The filters map straight onto Strava's ``date_range`` / ``gender`` / ``filter_type``
    leaderboard query params, so each segment is scraped with the window and cohort the
    stage needs (usually ``today`` on the overall board for a race-day protocol).
    """

    segment_id: str = ""
    date_range: DateRange = DateRange.TODAY
    gender: Gender = Gender.OVERALL
    filter_type: FilterType = FilterType.ALL

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "date_range": self.date_range.value,
            "gender": self.gender.value,
            "filter_type": self.filter_type.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SegmentConfig:
        data = data or {}
        return cls(
            segment_id=str(data.get("segment_id", "")),
            date_range=_coerce_enum(DateRange, data.get("date_range"), DateRange.TODAY),
            gender=_coerce_enum(Gender, data.get("gender"), Gender.OVERALL),
            filter_type=_coerce_enum(
                FilterType, data.get("filter_type"), FilterType.ALL
            ),
        )


@dataclass
class StageConfig:
    """One stage: its segments, rule, collection window, columns, and publishing."""

    name: str = "Stage"
    segments: list[SegmentConfig] = field(default_factory=lambda: [SegmentConfig()])
    rule: StageRule = StageRule.TIME
    date_from: str = ""
    date_to: str = ""
    freeze_strava_data: bool = False
    token: str = ""
    is_live: bool = True
    stage_label: str = ""
    absolute_action: HttpAction = HttpAction.NOTHING
    group_action: HttpAction = HttpAction.NOTHING
    absolute_file: str = ""
    group_file: str = ""
    cup_column_label: str = ""
    place_label: str = "Place"
    name_label: str = "Name"
    result_label: str = "Result"
    show_place: bool = True
    show_name: bool = True
    disable_dnf: bool = False
    group_label: str = ""
    show_group: bool = True
    show_year: bool = True
    year_label: str = "Year of birth"
    show_team: bool = True
    team_label: str = "Team"
    show_city: bool = True
    city_label: str = "City"
    show_gap: bool = True
    gap_label: str = "(gap)"
    unregistered_group_name: str = "Not registered"
    show_unregistered: bool = True
    race_info: RaceInfo = field(default_factory=RaceInfo)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "segments": [s.to_dict() for s in self.segments],
            "rule": self.rule.value,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "freeze_strava_data": self.freeze_strava_data,
            "token": self.token,
            "is_live": self.is_live,
            "stage_label": self.stage_label,
            "absolute_action": self.absolute_action.value,
            "group_action": self.group_action.value,
            "absolute_file": self.absolute_file,
            "group_file": self.group_file,
            "cup_column_label": self.cup_column_label,
            "place_label": self.place_label,
            "name_label": self.name_label,
            "result_label": self.result_label,
            "show_year": self.show_year,
            "year_label": self.year_label,
            "show_team": self.show_team,
            "team_label": self.team_label,
            "show_city": self.show_city,
            "city_label": self.city_label,
            "show_gap": self.show_gap,
            "gap_label": self.gap_label,
            "show_place": self.show_place,
            "show_name": self.show_name,
            "disable_dnf": self.disable_dnf,
            "group_label": self.group_label,
            "show_group": self.show_group,
            "unregistered_group_name": self.unregistered_group_name,
            "show_unregistered": self.show_unregistered,
            "race_info": self.race_info.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StageConfig:
        data = data or {}
        d = _Defaults(data, cls())
        segments = [SegmentConfig.from_dict(s) for s in data.get("segments", [])]
        return cls(
            name=d("name"),
            segments=segments or [SegmentConfig()],
            rule=StageRule(data.get("rule", StageRule.TIME.value)),
            date_from=d("date_from"),
            date_to=d("date_to"),
            freeze_strava_data=d("freeze_strava_data"),
            token=d("token"),
            is_live=d("is_live"),
            stage_label=d("stage_label"),
            absolute_action=_coerce_action(data.get("absolute_action")),
            group_action=_coerce_action(data.get("group_action")),
            absolute_file=d("absolute_file"),
            group_file=d("group_file"),
            cup_column_label=d("cup_column_label"),
            place_label=d("place_label"),
            name_label=d("name_label"),
            result_label=d("result_label"),
            show_year=d("show_year"),
            year_label=d("year_label"),
            show_team=d("show_team"),
            team_label=d("team_label"),
            show_city=d("show_city"),
            city_label=d("city_label"),
            show_gap=d("show_gap"),
            gap_label=d("gap_label"),
            show_place=d("show_place"),
            show_name=d("show_name"),
            disable_dnf=d("disable_dnf"),
            group_label=d("group_label"),
            show_group=d("show_group"),
            unregistered_group_name=d("unregistered_group_name"),
            show_unregistered=d("show_unregistered"),
            race_info=RaceInfo.from_dict(data.get("race_info", {})),
        )

    def column_label(self) -> str:
        """The label for this stage's cup column (falls back to the stage name)."""
        return self.cup_column_label or self.name


@dataclass
class CupConfig:
    """The overall cup: combine rule, columns, output files, token, and publishing."""

    name: str = "Cup"
    cup_rule: CupRule = CupRule.SUM_OF_TIMES
    token: str = ""
    is_live: bool = True
    stage_label: str = ""
    absolute_action: HttpAction = HttpAction.NOTHING
    group_action: HttpAction = HttpAction.NOTHING
    absolute_file: str = ""
    group_file: str = ""
    place_label: str = "Place"
    name_label: str = "Name"
    total_label: str = "Total"
    show_place: bool = True
    show_name: bool = True
    disable_dnf: bool = False
    group_label: str = ""
    show_group: bool = True
    show_year: bool = True
    year_label: str = "Year of birth"
    show_team: bool = True
    team_label: str = "Team"
    show_city: bool = True
    city_label: str = "City"
    show_gap: bool = True
    gap_label: str = "(gap)"
    show_stage_gap: bool = True
    stage_gap_label: str = "(gap)"
    show_stage_count: bool = True
    stage_count_label: str = "(stages)"
    unregistered_group_name: str = "Not registered"
    show_unregistered: bool = True
    race_info: RaceInfo = field(default_factory=RaceInfo)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cup_rule": self.cup_rule.value,
            "token": self.token,
            "is_live": self.is_live,
            "stage_label": self.stage_label,
            "absolute_action": self.absolute_action.value,
            "group_action": self.group_action.value,
            "absolute_file": self.absolute_file,
            "group_file": self.group_file,
            "place_label": self.place_label,
            "name_label": self.name_label,
            "total_label": self.total_label,
            "show_place": self.show_place,
            "show_name": self.show_name,
            "disable_dnf": self.disable_dnf,
            "group_label": self.group_label,
            "show_group": self.show_group,
            "show_year": self.show_year,
            "year_label": self.year_label,
            "show_team": self.show_team,
            "team_label": self.team_label,
            "show_city": self.show_city,
            "city_label": self.city_label,
            "show_gap": self.show_gap,
            "gap_label": self.gap_label,
            "show_stage_gap": self.show_stage_gap,
            "stage_gap_label": self.stage_gap_label,
            "show_stage_count": self.show_stage_count,
            "stage_count_label": self.stage_count_label,
            "unregistered_group_name": self.unregistered_group_name,
            "show_unregistered": self.show_unregistered,
            "race_info": self.race_info.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CupConfig:
        data = data or {}
        d = _Defaults(data, cls())
        return cls(
            name=d("name"),
            cup_rule=CupRule(data.get("cup_rule", CupRule.SUM_OF_TIMES.value)),
            token=d("token"),
            is_live=d("is_live"),
            stage_label=d("stage_label"),
            absolute_action=_coerce_action(data.get("absolute_action")),
            group_action=_coerce_action(data.get("group_action")),
            absolute_file=d("absolute_file"),
            group_file=d("group_file"),
            place_label=d("place_label"),
            name_label=d("name_label"),
            total_label=d("total_label"),
            show_place=d("show_place"),
            show_name=d("show_name"),
            disable_dnf=d("disable_dnf"),
            group_label=d("group_label"),
            show_group=d("show_group"),
            show_year=d("show_year"),
            year_label=d("year_label"),
            show_team=d("show_team"),
            team_label=d("team_label"),
            show_city=d("show_city"),
            city_label=d("city_label"),
            show_gap=d("show_gap"),
            gap_label=d("gap_label"),
            show_stage_gap=d("show_stage_gap"),
            stage_gap_label=d("stage_gap_label"),
            show_stage_count=d("show_stage_count"),
            stage_count_label=d("stage_count_label"),
            unregistered_group_name=d("unregistered_group_name"),
            show_unregistered=d("show_unregistered"),
            race_info=RaceInfo.from_dict(data.get("race_info", {})),
        )


@dataclass
class AppConfig:
    """The whole configuration: credentials, global options, stages, and the cup."""

    site_url: str = ""
    strava_cookies: list[dict[str, Any]] = field(default_factory=list)
    roster_token: str = ""
    decimals: int = 0
    show_strava_links: bool = False
    show_strava_statistics: bool = False
    strava_statistics_language: str = "ru"
    log_to_file: bool = False
    auto_refresh: bool = False
    refresh_interval: int = 30
    template_file: str = ""
    output_dir: str = "output"
    stages: list[StageConfig] = field(default_factory=lambda: [StageConfig()])
    cup: CupConfig = field(default_factory=CupConfig)

    def roster_token_effective(self) -> str:
        """Token used to fetch the roster: the explicit one, else the cup token."""
        return self.roster_token or self.cup.token

    def to_dict(self, include_secrets: bool = True) -> dict[str, Any]:
        return {
            "site_url": self.site_url,
            "strava_cookies": self.strava_cookies if include_secrets else [],
            "roster_token": self.roster_token,
            "decimals": self.decimals,
            "show_strava_links": self.show_strava_links,
            "show_strava_statistics": self.show_strava_statistics,
            "strava_statistics_language": self.strava_statistics_language,
            "log_to_file": self.log_to_file,
            "auto_refresh": self.auto_refresh,
            "refresh_interval": self.refresh_interval,
            "template_file": self.template_file,
            "output_dir": self.output_dir,
            "stages": [s.to_dict() for s in self.stages],
            "cup": self.cup.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AppConfig:
        data = data or {}
        d = _Defaults(data, cls())
        stages = [StageConfig.from_dict(s) for s in data.get("stages", [])]
        cup = CupConfig.from_dict(data["cup"]) if "cup" in data else CupConfig()
        return cls(
            site_url=d("site_url"),
            strava_cookies=list(data.get("strava_cookies", [])),
            roster_token=d("roster_token"),
            decimals=d("decimals"),
            show_strava_links=d("show_strava_links"),
            show_strava_statistics=d("show_strava_statistics"),
            strava_statistics_language=d("strava_statistics_language"),
            log_to_file=d("log_to_file"),
            auto_refresh=d("auto_refresh"),
            refresh_interval=d("refresh_interval"),
            template_file=d("template_file"),
            output_dir=d("output_dir"),
            stages=stages or [StageConfig()],
            cup=cup,
        )


class _Defaults:
    """Read keys from a dict, falling back to a template instance's attribute value."""

    def __init__(self, data: dict[str, Any], template: object) -> None:
        self._data = data
        self._template = template

    def __call__(self, key: str) -> Any:
        return self._data.get(key, getattr(self._template, key))
