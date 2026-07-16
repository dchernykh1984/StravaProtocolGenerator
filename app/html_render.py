"""Render stage and cup protocols to HTML, reusing FinishProtocolGenerator's look.

``HtmlStyles`` and ``load_template`` accept the same 11-line positional template file
FinishProtocolGenerator uses, so an existing template applies here unchanged. A stage
protocol is a simple place/name/result table; the cup protocol shows one column per
stage (the "laps") plus a combined total, with every column label configurable. Callers
pass data already grouped and ranked (see ``app.scoring``) as ``(group_name, ranked)``.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import cast

from app.models import RaceInfo
from app.scoring import Competitor, CupEntry, Ranked, StageEntry
from app.timeparse import format_time

_TEMPLATE_FIELDS = (
    "table_style",
    "top_line_style",
    "even_line_style",
    "odd_line_style",
    "group_name_style",
    "additional_text_top_style",
    "additional_text_style",
    "top_text_style",
    "additional_info_top_style",
    "additional_info_style",
    "common_style_text",
)


@dataclass
class HtmlStyles:
    """Look-and-feel knobs shared with FinishProtocolGenerator templates."""

    table_style: str = ""
    top_line_style: str = "background-color: rgb(175, 175, 175)"
    even_line_style: str = "background-color: rgb(215, 215, 215)"
    odd_line_style: str = "background-color: rgb(175, 175, 175)"
    group_name_style: str = '<FONT SIZE="4" COLOR="#FF0066">'
    additional_text_top_style: str = '<FONT SIZE="2" COLOR="#339900">'
    additional_text_style: str = '<FONT SIZE="2" COLOR="#339900">'
    top_text_style: str = '<FONT SIZE="4" COLOR="">'
    additional_info_top_style: str = '<FONT COLOR="#339900">'
    additional_info_style: str = '<FONT COLOR="#339900">'
    common_style_text: str = ""


def _decode_lines(raw: bytes) -> list[str]:
    """Decode template bytes trying utf-8, then cp1251, then latin-1 (never fails)."""
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1").splitlines()


def load_template(path: str) -> HtmlStyles | None:
    """Load an 11-line positional styles template, or ``None`` if it cannot be read.

    Missing trailing lines default to empty, like the FinishProtocolGenerator loader.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    lines = _decode_lines(raw)
    while len(lines) < len(_TEMPLATE_FIELDS):
        lines.append("")
    styles = HtmlStyles()
    for name, value in zip(_TEMPLATE_FIELDS, lines, strict=False):
        setattr(styles, name, value)
    return styles


@dataclass
class PersonColumns:
    """Shared registration columns (year of birth, team, city) and their toggles.

    Values come from the registration, so they are blank for an unregistered rider.
    """

    show_year: bool = False
    year_label: str = "Year"
    show_team: bool = False
    team_label: str = "Team"
    show_city: bool = False
    city_label: str = "City"


@dataclass
class StageColumns(PersonColumns):
    """Column labels and toggles for a stage protocol table."""

    place_label: str = "Place"
    name_label: str = "Name"
    result_label: str = "Result"
    show_place: bool = True
    show_name: bool = True
    show_gap: bool = False
    gap_label: str = "(gap)"
    show_links: bool = False


@dataclass
class CupColumns(PersonColumns):
    """Column labels and toggles for the cup protocol table."""

    place_label: str = "Place"
    name_label: str = "Name"
    total_label: str = "Total"
    show_place: bool = True
    show_name: bool = True
    show_gap: bool = False
    gap_label: str = "(gap)"
    show_stage_gap: bool = False
    stage_gap_label: str = "(gap)"
    show_stage_count: bool = False
    stage_count_label: str = "(stages)"
    show_links: bool = False


def _place_text(place: int | None) -> str:
    return str(place) if place is not None else ""


def _stage_url(entry: CupEntry, index: int) -> str:
    """The effort link behind a cup entry's value in stage ``index`` (empty if none)."""
    return entry.stage_urls[index] if index < len(entry.stage_urls) else ""


def _row_style(styles: HtmlStyles, index: int) -> str:
    return styles.odd_line_style if index % 2 == 0 else styles.even_line_style


def _header_cell(label: str) -> str:
    return f"<td ALIGN=center><B>{html.escape(label)}</B></td>"


def _header_cell_subs(label: str, subs: list[str], styles: HtmlStyles) -> str:
    """A header cell with one or more smaller caption lines below the label."""
    inner = html.escape(label)
    for sub in subs:
        inner += f"<BR>{styles.additional_text_top_style}{html.escape(sub)}</FONT>"
    return f"<td ALIGN=center><B>{inner}</B></td>"


def _header_cell_with_sub(label: str, sub: str, styles: HtmlStyles) -> str:
    """A header cell with a smaller second line (e.g. the gap-to-leader caption)."""
    return _header_cell_subs(label, [sub], styles)


def _link_inner(value: str, url: str) -> str:
    """The escaped ``value`` linked to ``url`` (bare text when there is no ``url``)."""
    if not url:
        return html.escape(value)
    safe_url = html.escape(url, quote=True)
    return (
        f'<a href="{safe_url}" target="_blank" rel="noopener">{html.escape(value)}</a>'
    )


def _cell(value: str) -> str:
    return f"<td ALIGN=center>{html.escape(value)}</td>"


def _link_cell(value: str, url: str) -> str:
    """A centered cell whose text links to ``url`` (a plain cell when no ``url``)."""
    return f"<td ALIGN=center>{_link_inner(value, url)}</td>"


def _person_headers(columns: PersonColumns) -> str:
    """The enabled registration column headers (year of birth, team, city)."""
    out = ""
    if columns.show_year:
        out += _header_cell(columns.year_label)
    if columns.show_team:
        out += _header_cell(columns.team_label)
    if columns.show_city:
        out += _header_cell(columns.city_label)
    return out


def _person_cells(competitor: Competitor, columns: PersonColumns) -> str:
    """The enabled registration cells for one rider (blank when not registered)."""
    out = ""
    if columns.show_year:
        out += _cell(str(competitor.birth_year) if competitor.birth_year else "")
    if columns.show_team:
        out += _cell(competitor.team)
    if columns.show_city:
        out += _cell(competitor.city)
    return out


def _gap_text(value: float | None, leader: float | None, decimals: int) -> str:
    """The ``(+diff)`` gap of ``value`` behind ``leader``; empty when not applicable.

    Blank when either time is missing or ``value`` is ahead of the ranked leader (a
    negative gap, which happens in the cup when a rider with fewer stages has a smaller
    partial total than the winner).
    """
    if value is None or leader is None:
        return ""
    diff = value - leader
    formatted = format_time(diff, decimals)
    if not formatted:
        return ""
    sign = "+" if diff > 0 else ""
    return f"({sign}{formatted})"


def _value_cell(inner: str, gap: str, styles: HtmlStyles, extra: str = "") -> str:
    """A centered result cell: value, then the gap and any ``extra`` line below it."""
    if gap:
        inner += f"<BR>{styles.additional_text_style}{html.escape(gap)}</FONT>"
    if extra:
        inner += f"<BR>{extra}"
    return f"<td ALIGN=center>{inner}</td>"


def _first_value(
    ranked: list[Ranked], pick: Callable[[StageEntry | CupEntry], float | None]
) -> float | None:
    """The leader's value: the first ranked entry with one (ranked is best-first)."""
    for item in ranked:
        value = pick(item.entry)
        if value is not None:
            return value
    return None


def _stage_leader(ranked: list[Ranked], index: int) -> float | None:
    """Fastest value on stage ``index`` among a group's cup entries, or ``None``."""
    values: list[float] = []
    for item in ranked:
        entry = cast(CupEntry, item.entry)
        if index < len(entry.stage_values) and entry.stage_values[index] is not None:
            values.append(cast(float, entry.stage_values[index]))
    return min(values) if values else None


def _centered_line(text: str, styles: HtmlStyles) -> str:
    return f"{styles.top_text_style}<B><CENTER>{text}</CENTER></B></FONT><BR>\n"


def _write_race_header(buf: StringIO, info: RaceInfo, styles: HtmlStyles) -> None:
    """Write the race metadata lines (date/place, track, weather) below the title."""
    date_place = ", ".join(p for p in (info.date, info.place) if p)
    if date_place:
        buf.write(_centered_line(html.escape(date_place), styles))
    if info.track_conditions:
        label = html.escape(info.track_label)
        buf.write(
            _centered_line(f"{label}: {html.escape(info.track_conditions)}", styles)
        )
    if info.weather:
        label = html.escape(info.weather_label)
        buf.write(_centered_line(f"{label}: {html.escape(info.weather)}", styles))


def _write_race_footer(buf: StringIO, info: RaceInfo) -> None:
    """Write the officials block (right-aligned) and the raw bottom text, if any."""
    officials = (
        (info.organizer_label, info.organizer),
        (info.referee_label, info.referee),
        (info.secretary_label, info.secretary),
    )
    for label, value in officials:
        if value:
            buf.write(
                f'<FONT SIZE="3"><B><p align="right">{html.escape(label)}: '
                f"{html.escape(value)}</p></B></FONT>\n"
            )
    if info.bottom_text:
        buf.write(info.bottom_text + "\n")


def _open_document(
    buf: StringIO, title: str, styles: HtmlStyles, info: RaceInfo
) -> None:
    buf.write('<html>\n<head>\n<meta charset="utf-8">\n')
    if styles.common_style_text:
        buf.write(f"<style>\n{styles.common_style_text}\n</style>\n")
    buf.write("</head>\n<body>\n")
    if info.sponsor:
        buf.write(f"<CENTER>{info.sponsor}</CENTER>\n")
    if title:
        buf.write(_centered_line(html.escape(title), styles))
    _write_race_header(buf, info, styles)


def _open_table(buf: StringIO, group_name: str, styles: HtmlStyles) -> None:
    if group_name:
        buf.write(f"{styles.group_name_style}{html.escape(group_name)}</FONT><BR>\n")
    buf.write(
        f'<table style="{styles.table_style}" border=1 cellspacing=0 cellpadding=3>\n'
    )


def render_stage_protocol(
    title: str,
    groups: list[tuple[str, list[Ranked]]],
    styles: HtmlStyles | None = None,
    columns: StageColumns | None = None,
    decimals: int = 0,
    race_info: RaceInfo | None = None,
) -> str:
    """Render a stage protocol: place / name / result, one table per group.

    With ``columns.show_gap`` the result carries the gap to that group's leader on a
    second line; ``race_info`` adds the shared header/footer (date, weather, officials).
    """
    styles = styles or HtmlStyles()
    columns = columns or StageColumns()
    info = race_info or RaceInfo()
    buf = StringIO()
    _open_document(buf, title, styles, info)
    for group_name, ranked in groups:
        _open_table(buf, group_name, styles)
        buf.write(f'<tr style="{styles.top_line_style}">')
        if columns.show_place:
            buf.write(_header_cell(columns.place_label))
        if columns.show_name:
            buf.write(_header_cell(columns.name_label))
        buf.write(_person_headers(columns))
        if columns.show_gap:
            buf.write(
                _header_cell_with_sub(columns.result_label, columns.gap_label, styles)
            )
        else:
            buf.write(_header_cell(columns.result_label))
        buf.write("</tr>\n")
        leader = _first_value(ranked, lambda e: cast(StageEntry, e).value)
        for i, item in enumerate(ranked):
            entry = cast(StageEntry, item.entry)
            buf.write(f'<tr style="{_row_style(styles, i)}">')
            if columns.show_place:
                buf.write(_cell(_place_text(item.place)))
            if columns.show_name:
                name = entry.competitor.name
                url = entry.competitor.athlete_url if columns.show_links else ""
                buf.write(_link_cell(name, url))
            buf.write(_person_cells(entry.competitor, columns))
            result = format_time(entry.value, decimals)
            result_url = entry.result_url if columns.show_links else ""
            gap = _gap_text(entry.value, leader, decimals) if columns.show_gap else ""
            buf.write(_value_cell(_link_inner(result, result_url), gap, styles))
            buf.write("</tr>\n")
        buf.write("</table>\n<BR>\n")
    _write_race_footer(buf, info)
    buf.write("</body>\n</html>\n")
    return buf.getvalue()


def render_cup_protocol(
    title: str,
    groups: list[tuple[str, list[Ranked]]],
    stage_labels: list[str],
    styles: HtmlStyles | None = None,
    columns: CupColumns | None = None,
    decimals: int = 0,
    race_info: RaceInfo | None = None,
) -> str:
    """Render the cup protocol: place / name / one column per stage / total.

    Each stage is shown as a "lap" column headed by its label from ``stage_labels``.
    ``columns.show_stage_gap`` adds each rider's gap to that stage's leader under the
    stage value; ``columns.show_gap`` adds the gap to the overall leader under the
    total. ``race_info`` adds the shared header/footer (date, weather, officials).
    """
    styles = styles or HtmlStyles()
    columns = columns or CupColumns()
    info = race_info or RaceInfo()
    buf = StringIO()
    _open_document(buf, title, styles, info)
    for group_name, ranked in groups:
        _open_table(buf, group_name, styles)
        _write_cup_header(buf, stage_labels, columns, styles)
        stage_leaders = [_stage_leader(ranked, j) for j in range(len(stage_labels))]
        total_leader = _first_value(ranked, lambda e: cast(CupEntry, e).total)
        for i, item in enumerate(ranked):
            buf.write(f'<tr style="{_row_style(styles, i)}">')
            _write_cup_row(
                buf, item, columns, styles, decimals, stage_leaders, total_leader
            )
            buf.write("</tr>\n")
        buf.write("</table>\n<BR>\n")
    _write_race_footer(buf, info)
    buf.write("</body>\n</html>\n")
    return buf.getvalue()


def _write_cup_header(
    buf: StringIO,
    stage_labels: list[str],
    columns: CupColumns,
    styles: HtmlStyles,
) -> None:
    buf.write(f'<tr style="{styles.top_line_style}">')
    if columns.show_place:
        buf.write(_header_cell(columns.place_label))
    if columns.show_name:
        buf.write(_header_cell(columns.name_label))
    buf.write(_person_headers(columns))
    for label in stage_labels:
        if columns.show_stage_gap:
            buf.write(_header_cell_with_sub(label, columns.stage_gap_label, styles))
        else:
            buf.write(_header_cell(label))
    total_subs: list[str] = []
    if columns.show_gap:
        total_subs.append(columns.gap_label)
    if columns.show_stage_count:
        total_subs.append(columns.stage_count_label)
    if total_subs:
        buf.write(_header_cell_subs(columns.total_label, total_subs, styles))
    else:
        buf.write(_header_cell(columns.total_label))
    buf.write("</tr>\n")


def _write_cup_row(
    buf: StringIO,
    item: Ranked,
    columns: CupColumns,
    styles: HtmlStyles,
    decimals: int,
    stage_leaders: list[float | None],
    total_leader: float | None,
) -> None:
    entry = cast(CupEntry, item.entry)
    if columns.show_place:
        buf.write(_cell(_place_text(item.place)))
    if columns.show_name:
        url = entry.competitor.athlete_url if columns.show_links else ""
        buf.write(_link_cell(entry.competitor.name, url))
    buf.write(_person_cells(entry.competitor, columns))
    for j, value in enumerate(entry.stage_values):
        stage_url = _stage_url(entry, j) if columns.show_links else ""
        leader = stage_leaders[j] if j < len(stage_leaders) else None
        gap = _gap_text(value, leader, decimals) if columns.show_stage_gap else ""
        buf.write(
            _value_cell(
                _link_inner(format_time(value, decimals), stage_url), gap, styles
            )
        )
    total_gap = (
        _gap_text(entry.total, total_leader, decimals) if columns.show_gap else ""
    )
    count_extra = ""
    if columns.show_stage_count:
        completed = sum(1 for v in entry.stage_values if v is not None)
        count_extra = f'<FONT SIZE="3">({completed})</FONT>'
    buf.write(
        _value_cell(
            html.escape(format_time(entry.total, decimals)),
            total_gap,
            styles,
            count_extra,
        )
    )
