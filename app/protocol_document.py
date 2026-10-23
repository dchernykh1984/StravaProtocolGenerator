"""The structured protocol document (schema 1) the cycling site draws in its own look.

The HTML protocols stay what ``app.html_render`` makes; this is the same stage or cup as
data, built from the same inputs and helpers, so the two never disagree. The site knows
nothing of segments or stages: every choice of what to show is made here.

Schema: tests/fixtures/protocol-document-v1.json, a copy of the cycling site's
protocols/schema/protocol-document-v1.json.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any, cast

from app.html_render import (
    CupColumns,
    PersonColumns,
    StageColumns,
    _first_value,
    _gap_text,
    _group_column_cells,
    _hr_text,
    _place_text,
    _speed_kmh,
    _stage_leader,
    _stage_url,
    _stat_presence,
    _watts_text,
)
from app.models import RaceInfo
from app.scoring import CupEntry, Ranked, StageEntry, group_key
from app.timeparse import format_time

SCHEMA_VERSION = 1
GENERATOR = "StravaProtocolGenerator"
_MAX_GROUP_ID = 100


def _version() -> str:
    try:
        return metadata.version("strava-protocol-generator")
    except metadata.PackageNotFoundError:
        return ""


def _cell(text: str, sub: list[str] | None = None, url: str = "") -> Any:
    sub = [line for line in (sub or []) if line]
    if not sub and not url:
        return text
    cell: dict[str, Any] = {"text": text}
    if sub:
        cell["sub"] = sub
    if url:
        cell["url"] = url
    return cell


def _column(column_id: str, label: str, **extra: Any) -> dict[str, Any]:
    column: dict[str, Any] = {"id": column_id, "label": label}
    column.update({k: v for k, v in extra.items() if v})
    return column


def _person_columns(
    columns: PersonColumns,
    show_place: bool,
    show_name: bool,
    place_label: str,
    name_label: str,
    group_label: str,
    show_group_column: bool,
) -> list[dict[str, Any]]:
    out = []
    if show_place:
        out.append(_column("place", place_label, role="place"))
    if show_name:
        out.append(_column("name", name_label, role="name"))
    if show_group_column:
        out.append(_column("group", group_label, role="group", priority=2))
    if columns.show_year:
        out.append(_column("year", columns.year_label, priority=3))
    if columns.show_team:
        out.append(_column("team", columns.team_label, role="team", priority=2))
    if columns.show_city:
        out.append(_column("city", columns.city_label, priority=3))
    return out


def _person_cells(
    item: Ranked, disable_dnf: bool, show_links: bool, group_cell: str | None
) -> dict[str, Any]:
    competitor = item.entry.competitor
    url = competitor.athlete_url if show_links else ""
    cells = {
        "place": _place_text(item.place, disable_dnf),
        "name": _cell(competitor.name, url=url),
        "group": group_cell or "",
        "year": str(competitor.birth_year) if competitor.birth_year else "",
        "team": competitor.team,
        "city": competitor.city,
    }
    return cells


def _row(
    item: Ranked,
    cells: dict[str, Any],
    ids: set[str],
    unregistered_name: str,
    tag_group: bool,
    disable_dnf: bool,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "cells": {k: v for k, v in cells.items() if k in ids and v not in ("", None)}
    }
    if item.place is None and not disable_dnf:
        row["status"] = "dnf"
    if tag_group:
        key = group_key(item.entry.competitor, unregistered_name)[:_MAX_GROUP_ID]
        if key:
            row["group"] = key
    return row


def _section(
    group_name: str,
    group_label: str,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    section: dict[str, Any] = {"type": "table", "columns": columns, "rows": rows}
    if group_name:
        section["title"] = f"{group_label} {group_name}" if group_label else group_name
        section["group"] = group_name[:_MAX_GROUP_ID]
    return section


def _items(info: RaceInfo, header: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def field(key: str, label: str, value: str) -> None:
        if value:
            items.append({"type": "field", "key": key, "label": label, "value": value})

    if header:
        if info.sponsor:
            items.append({"type": "html", "html": info.sponsor})
        date_place = ", ".join(p for p in (info.date, info.place) if p)
        if date_place:
            items.append({"type": "text", "text": date_place})
        field("track", info.track_label, info.track_conditions)
        field("weather", info.weather_label, info.weather)
    else:
        field("organizer", info.organizer_label, info.organizer)
        field("referee", info.referee_label, info.referee)
        field("secretary", info.secretary_label, info.secretary)
        if info.bottom_text:
            items.append({"type": "html", "html": info.bottom_text})
    return items


def _registry(
    sections: list[dict[str, Any]], categories: list[str], unregistered_name: str
) -> list[dict[str, str]]:
    """The groups that actually hold rows, in the order the group protocol uses."""
    present: list[str] = []
    for section in sections:
        for key in [section.get("group"), *(r.get("group") for r in section["rows"])]:
            if key and key not in present:
                present.append(key)
    order = [*categories, unregistered_name]
    ordered = [g for g in order if g in present] + [
        g for g in present if g not in order
    ]
    return [{"id": g, "label": g} for g in ordered]


def _document(
    title: str,
    info: RaceInfo,
    sections: list[dict[str, Any]],
    categories: list[str],
    unregistered_name: str,
    lang: str,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generator": {"name": GENERATOR, "version": _version()},
        "header": _items(info, header=True),
        "groups": _registry(sections, categories, unregistered_name),
        "sections": sections,
        "footer": _items(info, header=False),
    }
    if title:
        document["title"] = title
    if lang:
        document["lang"] = lang
    return document


def build_stage_document(
    title: str,
    groups: list[tuple[str, list[Ranked]]],
    columns: StageColumns,
    decimals: int,
    race_info: RaceInfo,
    show_group_column: bool,
    categories: list[str],
    unregistered_name: str,
    lang: str = "",
) -> dict[str, Any]:
    """A stage protocol as a document; the inputs are render_stage_protocol's plus the
    group order and this protocol's name for unregistered riders."""
    flags = _stat_presence(groups, columns)
    table_columns = _person_columns(
        columns,
        columns.show_place,
        columns.show_name,
        columns.place_label,
        columns.name_label,
        columns.group_label,
        show_group_column,
    )
    result_sub = [columns.gap_label] if columns.show_gap else []
    table_columns.append(
        _column("result", columns.result_label, role="result", sub_label=result_sub)
    )
    for flag, column_id, label in zip(
        flags,
        ("speed", "hr", "power"),
        (columns.speed_label, columns.hr_label, columns.power_label),
        strict=True,
    ):
        if flag:
            table_columns.append(_column(column_id, label, priority=3))
    ids = {c["id"] for c in table_columns}
    sections = []
    for group_name, ranked in groups:
        leader = _first_value(ranked, lambda e: cast(StageEntry, e).value)
        group_cells = _group_column_cells(ranked) if show_group_column else []
        rows = []
        for i, item in enumerate(ranked):
            entry = cast(StageEntry, item.entry)
            cells = _person_cells(
                item,
                columns.disable_dnf,
                columns.show_links,
                group_cells[i] if group_cells else None,
            )
            gap = _gap_text(entry.value, leader, decimals) if columns.show_gap else ""
            cells["result"] = _cell(
                format_time(entry.value, decimals, force_hours=True),
                [gap],
                entry.result_url if columns.show_links else "",
            )
            cells["speed"] = _speed_kmh(entry.avg_speed, columns.speed_unit)
            cells["hr"] = _hr_text(entry.avg_hr, columns.hr_unit)
            cells["power"] = _watts_text(entry.avg_watts, columns.power_unit)
            rows.append(
                _row(
                    item,
                    cells,
                    ids,
                    unregistered_name,
                    not group_name,
                    columns.disable_dnf,
                )
            )
        sections.append(_section(group_name, columns.group_label, table_columns, rows))
    return _document(title, race_info, sections, categories, unregistered_name, lang)


def build_cup_document(
    title: str,
    groups: list[tuple[str, list[Ranked]]],
    stage_labels: list[str],
    columns: CupColumns,
    decimals: int,
    race_info: RaceInfo,
    show_group_column: bool,
    categories: list[str],
    unregistered_name: str,
    lang: str = "",
) -> dict[str, Any]:
    """The cup protocol as a document; the inputs are render_cup_protocol's plus the
    group order and this protocol's name for unregistered riders."""
    table_columns = _person_columns(
        columns,
        columns.show_place,
        columns.show_name,
        columns.place_label,
        columns.name_label,
        columns.group_label,
        show_group_column,
    )
    stage_sub = [columns.stage_gap_label] if columns.show_stage_gap else []
    for j, label in enumerate(stage_labels):
        table_columns.append(
            _column(f"stage{j + 1}", label, sub_label=stage_sub, priority=3)
        )
    total_sub = []
    if columns.show_gap:
        total_sub.append(columns.gap_label)
    if columns.show_stage_count:
        total_sub.append(columns.stage_count_label)
    table_columns.append(
        _column("total", columns.total_label, role="result", sub_label=total_sub)
    )
    ids = {c["id"] for c in table_columns}
    sections = []
    for group_name, ranked in groups:
        stage_leaders = [_stage_leader(ranked, j) for j in range(len(stage_labels))]
        total_leader = _first_value(ranked, lambda e: cast(CupEntry, e).total)
        group_cells = _group_column_cells(ranked) if show_group_column else []
        rows = []
        for i, item in enumerate(ranked):
            entry = cast(CupEntry, item.entry)
            cells = _person_cells(
                item,
                columns.disable_dnf,
                columns.show_links,
                group_cells[i] if group_cells else None,
            )
            for j, value in enumerate(entry.stage_values):
                leader = stage_leaders[j] if j < len(stage_leaders) else None
                gap = (
                    _gap_text(value, leader, decimals) if columns.show_stage_gap else ""
                )
                cells[f"stage{j + 1}"] = _cell(
                    format_time(value, decimals, force_hours=True),
                    [gap],
                    _stage_url(entry, j) if columns.show_links else "",
                )
            total_gap = (
                _gap_text(entry.total, total_leader, decimals)
                if columns.show_gap
                else ""
            )
            count = ""
            if columns.show_stage_count:
                count = f"({sum(1 for v in entry.stage_values if v is not None)})"
            cells["total"] = _cell(
                format_time(entry.total, decimals, force_hours=True), [total_gap, count]
            )
            rows.append(
                _row(
                    item,
                    cells,
                    ids,
                    unregistered_name,
                    not group_name,
                    columns.disable_dnf,
                )
            )
        sections.append(_section(group_name, columns.group_label, table_columns, rows))
    return _document(title, race_info, sections, categories, unregistered_name, lang)
