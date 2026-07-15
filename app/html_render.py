"""Render stage and cup protocols to HTML, reusing FinishProtocolGenerator's look.

``HtmlStyles`` and ``load_template`` accept the same 11-line positional template file
FinishProtocolGenerator uses, so an existing template applies here unchanged. A stage
protocol is a simple place/name/result table; the cup protocol shows one column per
stage (the "laps") plus a combined total, with every column label configurable. Callers
pass data already grouped and ranked (see ``app.scoring``) as ``(group_name, ranked)``.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import cast

from app.scoring import CupEntry, Ranked, StageEntry
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
class StageColumns:
    """Column labels and toggles for a stage protocol table."""

    place_label: str = "Place"
    name_label: str = "Name"
    result_label: str = "Result"
    show_place: bool = True
    show_name: bool = True
    show_links: bool = False


@dataclass
class CupColumns:
    """Column labels and toggles for the cup protocol table."""

    place_label: str = "Place"
    name_label: str = "Name"
    total_label: str = "Total"
    show_place: bool = True
    show_name: bool = True
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


def _cell(value: str) -> str:
    return f"<td ALIGN=center>{html.escape(value)}</td>"


def _link_cell(value: str, url: str) -> str:
    """A centered cell whose text links to ``url`` (a plain cell when no ``url``)."""
    if not url:
        return _cell(value)
    safe_url = html.escape(url, quote=True)
    return (
        f'<td ALIGN=center><a href="{safe_url}" target="_blank" '
        f'rel="noopener">{html.escape(value)}</a></td>'
    )


def _open_document(buf: StringIO, title: str, styles: HtmlStyles) -> None:
    buf.write('<html>\n<head>\n<meta charset="utf-8">\n')
    if styles.common_style_text:
        buf.write(f"<style>\n{styles.common_style_text}\n</style>\n")
    buf.write("</head>\n<body>\n")
    if title:
        buf.write(f"{styles.top_text_style}{html.escape(title)}</FONT><BR>\n")


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
) -> str:
    """Render a stage protocol: place / name / result, one table per group."""
    styles = styles or HtmlStyles()
    columns = columns or StageColumns()
    buf = StringIO()
    _open_document(buf, title, styles)
    for group_name, ranked in groups:
        _open_table(buf, group_name, styles)
        buf.write(f'<tr style="{styles.top_line_style}">')
        if columns.show_place:
            buf.write(_header_cell(columns.place_label))
        if columns.show_name:
            buf.write(_header_cell(columns.name_label))
        buf.write(_header_cell(columns.result_label) + "</tr>\n")
        for i, item in enumerate(ranked):
            entry = cast(StageEntry, item.entry)
            buf.write(f'<tr style="{_row_style(styles, i)}">')
            if columns.show_place:
                buf.write(_cell(_place_text(item.place)))
            if columns.show_name:
                name = entry.competitor.name
                url = entry.competitor.athlete_url if columns.show_links else ""
                buf.write(_link_cell(name, url))
            result = format_time(entry.value, decimals)
            result_url = entry.result_url if columns.show_links else ""
            buf.write(_link_cell(result, result_url) + "</tr>\n")
        buf.write("</table>\n<BR>\n")
    buf.write("</body>\n</html>\n")
    return buf.getvalue()


def render_cup_protocol(
    title: str,
    groups: list[tuple[str, list[Ranked]]],
    stage_labels: list[str],
    styles: HtmlStyles | None = None,
    columns: CupColumns | None = None,
    decimals: int = 0,
) -> str:
    """Render the cup protocol: place / name / one column per stage / total.

    Each stage is shown as a "lap" column headed by its label from ``stage_labels``.
    """
    styles = styles or HtmlStyles()
    columns = columns or CupColumns()
    buf = StringIO()
    _open_document(buf, title, styles)
    for group_name, ranked in groups:
        _open_table(buf, group_name, styles)
        buf.write(f'<tr style="{styles.top_line_style}">')
        if columns.show_place:
            buf.write(_header_cell(columns.place_label))
        if columns.show_name:
            buf.write(_header_cell(columns.name_label))
        for label in stage_labels:
            buf.write(_header_cell(label))
        buf.write(_header_cell(columns.total_label) + "</tr>\n")
        for i, item in enumerate(ranked):
            entry = cast(CupEntry, item.entry)
            buf.write(f'<tr style="{_row_style(styles, i)}">')
            if columns.show_place:
                buf.write(_cell(_place_text(item.place)))
            if columns.show_name:
                name = entry.competitor.name
                url = entry.competitor.athlete_url if columns.show_links else ""
                buf.write(_link_cell(name, url))
            for j, value in enumerate(entry.stage_values):
                stage_url = _stage_url(entry, j) if columns.show_links else ""
                buf.write(_link_cell(format_time(value, decimals), stage_url))
            buf.write(_cell(format_time(entry.total, decimals)) + "</tr>\n")
        buf.write("</table>\n<BR>\n")
    buf.write("</body>\n</html>\n")
    return buf.getvalue()
