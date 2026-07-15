"""Tests for FinishProtocolGenerator-compatible HTML rendering."""

from app.html_render import (
    CupColumns,
    HtmlStyles,
    StageColumns,
    _decode_lines,
    load_template,
    render_cup_protocol,
    render_stage_protocol,
)
from app.scoring import Competitor, CupEntry, Ranked, StageEntry


def _stage_group(name: str) -> tuple[str, list[Ranked]]:
    a = StageEntry(Competitor("p:1", "Ivan Petrov", name, True), [300.0], 300.0)
    b = StageEntry(Competitor("p:2", "Anna Ivanova", name, True), [None], None)
    return name, [Ranked(1, a), Ranked(None, b)]


def _cup_group(name: str) -> tuple[str, list[Ranked]]:
    a = CupEntry(Competitor("p:1", "Ivan Petrov", name, True), [300.0, 200.0], 500.0)
    return name, [Ranked(1, a)]


def test_stage_protocol_renders_links_when_enabled() -> None:
    entry = StageEntry(
        Competitor(
            "p:1",
            "Ivan Petrov",
            "A",
            True,
            athlete_url="https://strava.test/athletes/1",
        ),
        [300.0],
        300.0,
        result_url="https://strava.test/activities/9",
    )
    out = render_stage_protocol(
        "T", [("A", [Ranked(1, entry)])], columns=StageColumns(show_links=True)
    )
    assert '<a href="https://strava.test/athletes/1"' in out
    assert '<a href="https://strava.test/activities/9"' in out


def test_stage_protocol_omits_links_by_default() -> None:
    name, ranked = _stage_group("A")
    assert "<a href" not in render_stage_protocol("T", [(name, ranked)])


def test_cup_protocol_renders_stage_links_when_enabled() -> None:
    entry = CupEntry(
        Competitor("p:1", "Ivan", "A", True, athlete_url="https://strava.test/a/1"),
        [300.0, 200.0],
        500.0,
        stage_urls=["https://strava.test/e/1", ""],
    )
    out = render_cup_protocol(
        "T",
        [("A", [Ranked(1, entry)])],
        ["D1", "D2"],
        columns=CupColumns(show_links=True),
    )
    assert '<a href="https://strava.test/a/1"' in out
    assert '<a href="https://strava.test/e/1"' in out


def test_cup_protocol_missing_stage_url_is_a_plain_cell() -> None:
    entry = CupEntry(
        Competitor("p:1", "Ivan", "A", True, athlete_url="u"),
        [300.0, 200.0],
        500.0,
        stage_urls=["only-first"],  # shorter than stage_values -> second has no link
    )
    out = render_cup_protocol(
        "T",
        [("A", [Ranked(1, entry)])],
        ["D1", "D2"],
        columns=CupColumns(show_links=True),
    )
    assert '<a href="only-first"' in out


def test_load_template_reads_11_lines(tmp_path) -> None:
    lines = [f"line{i}" for i in range(11)]
    path = tmp_path / "template.html"
    path.write_text("\n".join(lines), encoding="utf-8")
    styles = load_template(str(path))
    assert styles is not None
    assert styles.table_style == "line0"
    assert styles.common_style_text == "line10"


def test_load_template_pads_missing_lines(tmp_path) -> None:
    path = tmp_path / "t.html"
    path.write_text("only-first", encoding="utf-8")
    styles = load_template(str(path))
    assert styles is not None
    assert styles.table_style == "only-first"
    assert styles.common_style_text == ""


def test_load_template_missing_file_returns_none() -> None:
    assert load_template("/no/such/file.html") is None


def test_decode_lines_utf8() -> None:
    assert _decode_lines(b"a\nb") == ["a", "b"]


def test_decode_lines_falls_back_to_cp1251() -> None:
    # cp1251 bytes for a Cyrillic word; invalid as utf-8, so cp1251 is used.
    raw = b"\xcf\xf0\xe8\xe2\xe5\xf2"
    assert _decode_lines(raw) == ["\u041f\u0440\u0438\u0432\u0435\u0442"]


def test_decode_lines_falls_back_to_latin1() -> None:
    # 0x98 is undefined in cp1251 and invalid in utf-8, so latin-1 is the fallback.
    assert _decode_lines(b"\x98") == ["\x98"]


def test_render_stage_protocol_structure() -> None:
    html = render_stage_protocol(
        "Stage 1", [_stage_group("3.5+")], columns=StageColumns(result_label="Time")
    )
    assert "Stage 1" in html
    assert "3.5+" in html
    assert "Ivan Petrov" in html
    assert "<td ALIGN=center><B>Time</B></td>" in html
    assert "5:00" in html  # 300 seconds formatted
    # The registered no-time rider still appears with blank place and result.
    assert "Anna Ivanova" in html


def test_render_stage_hides_place_when_disabled() -> None:
    html = render_stage_protocol(
        "S", [_stage_group("A")], columns=StageColumns(show_place=False)
    )
    assert "<B>Place</B>" not in html
    assert "Ivan Petrov" in html


def test_render_stage_escapes_names() -> None:
    entry = StageEntry(Competitor("p:9", "A <b> B", "G", True), [10.0], 10.0)
    html = render_stage_protocol("T", [("G", [Ranked(1, entry)])])
    assert "A &lt;b&gt; B" in html


def test_render_cup_protocol_has_stage_columns_and_total() -> None:
    html = render_cup_protocol(
        "Cup",
        [_cup_group("3.5+")],
        stage_labels=["Day 1", "Day 2"],
        columns=CupColumns(total_label="Sum"),
    )
    assert "<td ALIGN=center><B>Day 1</B></td>" in html
    assert "<td ALIGN=center><B>Day 2</B></td>" in html
    assert "<td ALIGN=center><B>Sum</B></td>" in html
    assert "5:00" in html  # 300s stage
    assert "3:20" in html  # 200s stage
    assert "8:20" in html  # 500s total


def test_render_uses_custom_styles() -> None:
    styles = HtmlStyles(top_line_style="X-HEADER", common_style_text="body{}")
    html = render_stage_protocol("T", [_stage_group("A")], styles=styles)
    assert 'style="X-HEADER"' in html
    assert "<style>\nbody{}\n</style>" in html
