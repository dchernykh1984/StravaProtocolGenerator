"""Tests for FinishProtocolGenerator-compatible HTML rendering."""

from app.html_render import (
    CupColumns,
    HtmlStyles,
    StageColumns,
    _decode_lines,
    _gap_text,
    load_template,
    render_cup_protocol,
    render_stage_protocol,
)
from app.models import RaceInfo
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


def test_stage_protocol_shows_year_team_city_when_enabled() -> None:
    reg = StageEntry(
        Competitor(
            "p:1", "Ivan", "A", True, birth_year=1984, team="UBT", city="Almaty"
        ),
        [300.0],
        300.0,
    )
    guest = StageEntry(Competitor("s:9", "Guest", "A", False), [280.0], 280.0)
    html = render_stage_protocol(
        "S",
        [("A", [Ranked(1, guest), Ranked(2, reg)])],
        columns=StageColumns(
            show_year=True,
            year_label="Year",
            show_team=True,
            team_label="Team",
            show_city=True,
            city_label="City",
        ),
    )
    for header in ("<B>Year</B>", "<B>Team</B>", "<B>City</B>"):
        assert header in html
    assert "1984" in html and "UBT" in html and "Almaty" in html
    # The unregistered guest has blank registration cells (three empty cells in a row).
    assert "<td ALIGN=center></td><td ALIGN=center></td><td ALIGN=center></td>" in html


def test_stage_protocol_hides_registration_columns_by_default() -> None:
    reg = StageEntry(
        Competitor(
            "p:1", "Ivan", "A", True, birth_year=1984, team="UBT", city="Almaty"
        ),
        [300.0],
        300.0,
    )
    html = render_stage_protocol("S", [("A", [Ranked(1, reg)])])
    assert "1984" not in html and "UBT" not in html


def test_cup_protocol_shows_registration_columns() -> None:
    entry = CupEntry(
        Competitor(
            "p:1", "Ivan", "A", True, birth_year=1990, team="ART", city="Astana"
        ),
        [300.0, 200.0],
        500.0,
    )
    html = render_cup_protocol(
        "Cup",
        [("A", [Ranked(1, entry)])],
        ["D1", "D2"],
        columns=CupColumns(show_year=True, show_team=True, show_city=True),
    )
    assert "1990" in html and "ART" in html and "Astana" in html


def test_stage_protocol_marks_no_result_as_dnf() -> None:
    finished = StageEntry(Competitor("p:1", "Ivan", "A", True), [300.0], 300.0)
    no_result = StageEntry(Competitor("p:2", "Anna", "A", True), [None], None)
    group = [("A", [Ranked(1, finished), Ranked(None, no_result)])]
    # DNF shown when not disabled, blank when disabled.
    shown = render_stage_protocol("S", group, columns=StageColumns(disable_dnf=False))
    assert "<td ALIGN=center>DNF</td>" in shown
    hidden = render_stage_protocol("S", group, columns=StageColumns(disable_dnf=True))
    assert "DNF" not in hidden


def test_cup_protocol_marks_no_result_as_dnf() -> None:
    finished = CupEntry(Competitor("p:1", "Ivan", "A", True), [300.0], 300.0)
    none_done = CupEntry(Competitor("p:2", "Anna", "A", True), [None], None)
    html = render_cup_protocol(
        "Cup",
        [("A", [Ranked(1, finished), Ranked(None, none_done)])],
        ["D1"],
        columns=CupColumns(disable_dnf=False),
    )
    assert "<td ALIGN=center>DNF</td>" in html


def test_gap_text_covers_leader_slower_and_missing() -> None:
    assert _gap_text(300.0, 300.0, 0) == "(0:00)"  # leader shows a zero gap
    assert _gap_text(500.0, 300.0, 0) == "(+3:20)"  # slower than the leader
    assert _gap_text(100.0, 500.0, 0) == ""  # ahead of the ranked leader -> blank
    assert _gap_text(None, 300.0, 0) == ""  # no result -> blank
    assert _gap_text(300.0, None, 0) == ""  # no leader -> blank


def _two_stage_entries() -> tuple[str, list[Ranked]]:
    a = StageEntry(Competitor("p:1", "Fast", "A", True), [300.0], 300.0)
    b = StageEntry(Competitor("p:2", "Slow", "A", True), [360.0], 360.0)
    return "A", [Ranked(1, a), Ranked(2, b)]


def test_stage_protocol_shows_gap_when_enabled() -> None:
    html = render_stage_protocol(
        "S",
        [_two_stage_entries()],
        columns=StageColumns(show_gap=True, gap_label="(gap)"),
    )
    # The gap caption is in the result header and the runner-up shows the gap.
    assert "(gap)" in html
    assert "(+1:00)" in html  # 360 - 300


def test_cup_protocol_shows_total_and_stage_gaps() -> None:
    a = CupEntry(Competitor("p:1", "Fast", "A", True), [300.0, 200.0], 500.0)
    b = CupEntry(Competitor("p:2", "Slow", "A", True), [360.0, 260.0], 620.0)
    html = render_cup_protocol(
        "Cup",
        [("A", [Ranked(1, a), Ranked(2, b)])],
        ["D1", "D2"],
        columns=CupColumns(
            show_gap=True,
            gap_label="(tot)",
            show_stage_gap=True,
            stage_gap_label="(st)",
        ),
    )
    assert "(tot)" in html  # total gap caption
    assert "(st)" in html  # stage gap caption
    assert "(+1:00)" in html  # stage 1 gap: 360 - 300
    assert "(+2:00)" in html  # total gap: 620 - 500


def test_cup_protocol_shows_stage_count() -> None:
    # "Two" completed both stages, "One" only the first.
    two = CupEntry(Competitor("p:1", "Two", "A", True), [300.0, 200.0], 500.0)
    one = CupEntry(Competitor("p:2", "One", "A", True), [360.0, None], 360.0)
    html = render_cup_protocol(
        "Cup",
        [("A", [Ranked(1, two), Ranked(2, one)])],
        ["D1", "D2"],
        columns=CupColumns(show_stage_count=True, stage_count_label="(done)"),
    )
    assert "(done)" in html  # the caption in the total header
    assert '<FONT SIZE="3">(2)</FONT>' in html  # completed both stages
    assert '<FONT SIZE="3">(1)</FONT>' in html  # completed one stage


def test_cup_protocol_hides_stage_count_by_default() -> None:
    html = render_cup_protocol("Cup", [_cup_group("A")], ["D1", "D2"])
    assert '<FONT SIZE="3">(' not in html


def test_cup_stage_gap_blank_for_rider_ahead_of_ranked_leader() -> None:
    # The rank-1 rider completed both stages; the rank-2 rider did only one, giving a
    # smaller partial total -- their total gap is negative and must render blank.
    leader = CupEntry(Competitor("p:1", "All", "A", True), [300.0, 300.0], 600.0)
    partial = CupEntry(Competitor("p:2", "One", "A", True), [100.0, None], 100.0)
    html = render_cup_protocol(
        "Cup",
        [("A", [Ranked(1, leader), Ranked(2, partial)])],
        ["D1", "D2"],
        columns=CupColumns(show_gap=True),
    )
    assert "(-" not in html  # never a negative gap


def _full_race_info() -> RaceInfo:
    return RaceInfo(
        date="4 July 2026",
        place="Almaty",
        weather_label="Weather",
        weather="+20",
        track_label="Track",
        track_conditions="Asphalt",
        referee_label="Head referee",
        referee="R. Mamaev",
        secretary_label="Timekeeper",
        secretary="D. Chernykh",
        organizer_label="Organizer",
        organizer="UBT",
        sponsor="<img src='x'>",
        bottom_text="<i>auto-generated</i>",
    )


def test_stage_protocol_renders_race_info_header_and_footer() -> None:
    html = render_stage_protocol("S", [_stage_group("A")], race_info=_full_race_info())
    assert "4 July 2026, Almaty" in html
    assert "Track: Asphalt" in html
    assert "Weather: +20" in html
    assert "Head referee: R. Mamaev" in html
    assert "Timekeeper: D. Chernykh" in html
    assert "Organizer: UBT" in html
    assert "<img src='x'>" in html  # sponsor is raw HTML
    assert "<i>auto-generated</i>" in html  # bottom text is raw HTML


def test_cup_protocol_renders_race_info() -> None:
    html = render_cup_protocol(
        "Cup", [_cup_group("A")], ["D1", "D2"], race_info=_full_race_info()
    )
    assert "4 July 2026, Almaty" in html
    assert "Organizer: UBT" in html
