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

from app.scoring import CupRule, StageRule


class HttpAction(StrEnum):
    """What to do with a protocol on the site (as in FinishProtocolGenerator)."""

    NOTHING = "Nothing"
    UPLOAD = "Upload"
    DELETE = "Delete"


def _coerce_action(value: Any) -> HttpAction:
    try:
        return HttpAction(value)
    except ValueError:
        return HttpAction.NOTHING


@dataclass
class SegmentConfig:
    """One Strava segment scraped for a stage (identified by its numeric id)."""

    segment_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"segment_id": self.segment_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SegmentConfig:
        return cls(segment_id=str(data.get("segment_id", "")))


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
            "show_place": self.show_place,
            "show_name": self.show_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageConfig:
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
            show_place=d("show_place"),
            show_name=d("show_name"),
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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CupConfig:
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
        )


@dataclass
class AppConfig:
    """The whole configuration: credentials, global options, stages, and the cup."""

    site_url: str = ""
    strava_cookies: list[dict[str, Any]] = field(default_factory=list)
    roster_token: str = ""
    unregistered_group_name: str = "Not registered"
    decimals: int = 0
    show_strava_links: bool = False
    log_to_file: bool = False
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
            "unregistered_group_name": self.unregistered_group_name,
            "decimals": self.decimals,
            "show_strava_links": self.show_strava_links,
            "log_to_file": self.log_to_file,
            "template_file": self.template_file,
            "output_dir": self.output_dir,
            "stages": [s.to_dict() for s in self.stages],
            "cup": self.cup.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        d = _Defaults(data, cls())
        stages = [StageConfig.from_dict(s) for s in data.get("stages", [])]
        cup = CupConfig.from_dict(data["cup"]) if "cup" in data else CupConfig()
        return cls(
            site_url=d("site_url"),
            strava_cookies=list(data.get("strava_cookies", [])),
            roster_token=d("roster_token"),
            unregistered_group_name=d("unregistered_group_name"),
            decimals=d("decimals"),
            show_strava_links=d("show_strava_links"),
            log_to_file=d("log_to_file"),
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
