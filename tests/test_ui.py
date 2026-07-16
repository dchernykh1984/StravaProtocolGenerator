"""Qt-level tests for the main window.

``main_window`` is excluded from coverage, so these run under the offscreen Qt platform
to guard the widget wiring (here: the stage tab label tracking the stage name field).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QDate
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from app import main_window as mw
from app.config import AppConfig, CupConfig, SegmentConfig, StageConfig

_app = QApplication.instance() or QApplication([])


def test_app_icon_exists_and_loads() -> None:
    assert Path(mw.ICON_PATH).exists()
    assert not QIcon(mw.ICON_PATH).isNull()


def test_tab_title_follows_stage_name() -> None:
    window = mw.MainWindow()
    first_tab = window._tabs.widget(0)
    first_tab.name.setText("Day 1")
    assert window._tabs.tabText(0) == "Day 1"


def test_tab_title_falls_back_when_name_cleared() -> None:
    window = mw.MainWindow()
    first_tab = window._tabs.widget(0)
    first_tab.name.setText("")
    assert window._tabs.tabText(0) == "Stage 1"


def test_added_stage_tab_also_tracks_its_name() -> None:
    window = mw.MainWindow()
    window._add_stage_copy(1)
    new_index = window._tabs.currentIndex()
    window._tabs.widget(new_index).name.setText("Day 2")
    assert window._tabs.tabText(new_index) == "Day 2"


def test_add_stage_right_inserts_copy_after_current() -> None:
    window = mw.MainWindow()
    window.apply_config(AppConfig(stages=[StageConfig(name="A")], cup=CupConfig()))
    window._tabs.setCurrentIndex(0)
    window._add_stage_copy(1)
    assert window._tabs.count() == 2
    assert window._tabs.currentIndex() == 1
    assert window._tabs.widget(0).name.text() == "A"
    assert window._tabs.widget(1).name.text() == "A"


def test_add_stage_left_inserts_copy_before_current() -> None:
    window = mw.MainWindow()
    window.apply_config(
        AppConfig(
            stages=[StageConfig(name="A"), StageConfig(name="B")], cup=CupConfig()
        )
    )
    window._tabs.setCurrentIndex(1)
    window._add_stage_copy(0)
    assert window._tabs.count() == 3
    assert window._tabs.currentIndex() == 1
    assert window._tabs.widget(1).name.text() == "B"
    assert window._tabs.widget(2).name.text() == "B"


def test_stage_date_fields_are_date_fields() -> None:
    tab = mw.StageTab(StageConfig(date_from="2026-08-01", date_to="2026-08-02"))
    assert isinstance(tab.date_from, mw.DateField)
    assert tab.date_from.iso() == "2026-08-01"
    assert tab.date_to.iso() == "2026-08-02"


def test_stage_date_field_keeps_typed_text() -> None:
    tab = mw.StageTab(StageConfig())
    tab.date_from.edit.setText("2026-07-14")  # plain text survives, like a line edit
    assert tab.date_from.iso() == "2026-07-14"
    assert tab.to_config().date_from == "2026-07-14"


def test_stage_date_field_calendar_fills_iso() -> None:
    tab = mw.StageTab(StageConfig())
    tab.date_from._apply_date(QDate(2026, 7, 14))
    assert tab.date_from.iso() == "2026-07-14"


def test_stage_date_field_calendar_popup_reflects_current_value() -> None:
    tab = mw.StageTab(StageConfig(date_from="2026-07-14"))
    tab.date_from._open_calendar()
    assert tab.date_from._calendar.selectedDate() == QDate(2026, 7, 14)
    tab.date_from._calendar.close()


def test_stage_date_labels_mark_bounds_inclusive() -> None:
    tab = mw.StageTab(StageConfig())
    assert tab.field_label(tab.date_from) == "Date from (including)"
    assert tab.field_label(tab.date_to) == "Date to (including)"


def test_stage_broadcast_token_label_links_to_site_url() -> None:
    tab = mw.StageTab(StageConfig())
    assert tab.field_label(tab.token) == "Broadcast token (to Site URL)"


def test_two_column_stage_keeps_all_fields() -> None:
    stage = StageConfig(
        name="Day 7",
        date_from="2026-08-01",
        date_to="2026-08-02",
        token="bcast",
        stage_label="D7",
        absolute_file="abs.html",
        group_file="grp.html",
        cup_column_label="col",
        place_label="Pos",
        name_label="Rider",
        result_label="Time",
    )
    config = mw.StageTab(stage).to_config()
    assert config.name == "Day 7"
    assert config.date_from == "2026-08-01"
    assert config.date_to == "2026-08-02"
    assert config.token == "bcast"
    assert config.stage_label == "D7"
    assert config.absolute_file == "abs.html"
    assert config.group_file == "grp.html"
    assert config.cup_column_label == "col"
    assert config.place_label == "Pos"
    assert config.name_label == "Rider"
    assert config.result_label == "Time"


def test_stage_dates_round_trip_through_config() -> None:
    tab = mw.StageTab(StageConfig(date_from="2026-08-01", date_to="2026-08-02"))
    config = tab.to_config()
    assert config.date_from == "2026-08-01"
    assert config.date_to == "2026-08-02"


def test_stage_empty_dates_round_trip_to_empty_string() -> None:
    tab = mw.StageTab(StageConfig())
    assert tab.date_from.iso() == ""
    config = tab.to_config()
    assert config.date_from == ""
    assert config.date_to == ""


def test_two_column_top_keeps_globals_and_cup_fields() -> None:
    window = mw.MainWindow()
    assert isinstance(window._cup, mw.CupPanel)
    config = AppConfig(
        site_url="https://s.test",
        roster_token="rt",
        template_file="t.html",
        output_dir="out",
        cup=CupConfig(name="Grand Cup", token="cup-token"),
    )
    window.apply_config(config)
    collected = window.collect_config()
    assert collected.site_url == "https://s.test"
    assert collected.roster_token == "rt"
    assert collected.template_file == "t.html"
    assert collected.output_dir == "out"
    assert collected.cup.name == "Grand Cup"
    assert collected.cup.token == "cup-token"


def test_stage_segment_id_keeps_only_the_first_token() -> None:
    tab = mw.StageTab(StageConfig(segments=[SegmentConfig("41792375")]))
    tab.segments.rows[0].segment_id.setText("41792182 stray tokens")
    ids = [s.segment_id for s in tab.to_config().segments]
    assert ids == ["41792182"]


def test_stage_add_and_remove_segment_rows() -> None:
    tab = mw.StageTab(StageConfig(segments=[SegmentConfig("111")]))
    tab.segments.add_segment(SegmentConfig("222"))
    assert [s.segment_id for s in tab.to_config().segments] == ["111", "222"]
    tab.segments.rows[0].remove.click()
    assert [s.segment_id for s in tab.to_config().segments] == ["222"]
    # The last remaining row is never removed.
    tab.segments.rows[0].remove.click()
    assert len(tab.segments.rows) == 1


def test_stage_freeze_checkbox_round_trips() -> None:
    tab = mw.StageTab(StageConfig(freeze_strava_data=True))
    assert tab.freeze_strava_data.isChecked()
    assert tab.to_config().freeze_strava_data is True


def test_segment_filters_round_trip() -> None:
    from app.config import DateRange, FilterType, Gender

    segment = SegmentConfig(
        "5",
        date_range=DateRange.THIS_MONTH,
        gender=Gender.WOMEN,
        filter_type=FilterType.MY_RESULTS,
    )
    tab = mw.StageTab(StageConfig(segments=[segment]))
    row = tab.segments.rows[0]
    assert row.date_range.currentText() == "this_month"
    assert row.gender.currentText() == "F"
    assert row.filter_type.currentText() == "my_results"
    collected = tab.to_config().segments[0]
    assert collected.date_range is DateRange.THIS_MONTH
    assert collected.gender is Gender.WOMEN
    assert collected.filter_type is FilterType.MY_RESULTS


def test_stage_unregistered_group_round_trips() -> None:
    tab = mw.StageTab(
        StageConfig(unregistered_group_name="Stage guests", show_unregistered=False)
    )
    assert tab.unregistered_group_name.text() == "Stage guests"
    assert tab.show_unregistered.isChecked() is False
    config = tab.to_config()
    assert config.unregistered_group_name == "Stage guests"
    assert config.show_unregistered is False


def test_cup_unregistered_group_round_trips() -> None:
    panel = mw.CupPanel(
        CupConfig(unregistered_group_name="Cup guests", show_unregistered=False)
    )
    assert panel.unregistered_group_name.text() == "Cup guests"
    assert panel.show_unregistered.isChecked() is False
    config = panel.to_config()
    assert config.unregistered_group_name == "Cup guests"
    assert config.show_unregistered is False


def test_stage_file_fields_are_file_pickers() -> None:
    tab = mw.StageTab(StageConfig())
    assert isinstance(tab.absolute_file, mw.FilePicker)
    assert isinstance(tab.group_file, mw.FilePicker)


def test_cup_file_fields_are_file_pickers() -> None:
    panel = mw.CupPanel(CupConfig())
    assert isinstance(panel.absolute_file, mw.FilePicker)
    assert isinstance(panel.group_file, mw.FilePicker)


def test_cup_fields_survive_combined_rows() -> None:
    cup = CupConfig(
        name="Grand Cup",
        token="cup-tok",
        is_live=False,
        stage_label="GC",
        place_label="Pos",
        name_label="Rider",
        total_label="Sum",
        show_place=False,
        show_name=False,
    )
    result = mw.CupPanel(cup).to_config()
    assert result.name == "Grand Cup"
    assert result.token == "cup-tok"
    assert result.is_live is False
    assert result.stage_label == "GC"
    assert result.place_label == "Pos"
    assert result.name_label == "Rider"
    assert result.total_label == "Sum"
    assert result.show_place is False
    assert result.show_name is False


def test_file_picker_browse_sets_chosen_path(monkeypatch: pytest.MonkeyPatch) -> None:
    picker = mw.FilePicker()
    monkeypatch.setattr(
        mw.QFileDialog, "getSaveFileName", lambda *a, **k: ("chosen/out.html", "*.html")
    )
    picker._browse()
    assert picker.text() == "chosen/out.html"


def test_file_picker_browse_cancel_keeps_value(monkeypatch: pytest.MonkeyPatch) -> None:
    picker = mw.FilePicker("keep.html")
    monkeypatch.setattr(mw.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    picker._browse()
    assert picker.text() == "keep.html"


def test_log_to_file_checkbox_round_trips() -> None:
    window = mw.MainWindow()
    window.apply_config(AppConfig(log_to_file=True, cup=CupConfig()))
    assert window._log_to_file.isChecked()
    assert window.collect_config().log_to_file is True


def test_log_to_file_writes_only_when_checked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mw, "LOG_DIR", str(tmp_path))
    window = mw.MainWindow()

    window._log_to_file.setChecked(False)
    window._append_log("hidden")
    assert list(tmp_path.glob("session_*.log")) == []

    window._log_to_file.setChecked(True)
    window._append_log("captured")
    logs = list(tmp_path.glob("session_*.log"))
    assert len(logs) == 1
    written = logs[0].read_text(encoding="utf-8")
    assert "captured" in written
    assert "hidden" not in written
    # both messages always reach the on-screen log, regardless of the checkbox
    assert "hidden" in window._log.toPlainText()
    assert "captured" in window._log.toPlainText()


def test_single_generate_button_replaces_the_pair() -> None:
    window = mw.MainWindow()
    labels = [b.text() for b in window.findChildren(QPushButton)]
    assert "Generate" in labels
    assert "Generate and publish" not in labels
    assert "Generate locally" not in labels


def test_main_window_has_main_cup_stages_tabs() -> None:
    window = mw.MainWindow()
    labels = [window._main_tabs.tabText(i) for i in range(window._main_tabs.count())]
    assert labels == ["Main", "Cup", "Stages"]


def test_login_to_strava_button_present() -> None:
    window = mw.MainWindow()
    labels = [b.text() for b in window.findChildren(QPushButton)]
    assert "Login to Strava" in labels


def test_manual_login_stores_and_persists_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = mw.MainWindow()
    saved: list[tuple] = []
    monkeypatch.setattr(mw, "save_config", lambda *a, **k: saved.append(a))
    cookies = [{"name": "strava_remember_token", "value": "tok"}]
    window._on_login_done(cookies)
    assert window._strava_cookies == cookies
    assert window.collect_config().strava_cookies == cookies  # carried into the config
    assert saved  # persisted to disk
    assert "Logged in to Strava" in window._log.toPlainText()


def test_auto_refresh_toggle_starts_and_stops_timer() -> None:
    window = mw.MainWindow()
    window._interval.setValue(5)
    window._auto_refresh.setChecked(True)
    assert window._timer is not None
    assert window._timer.isActive()
    assert window._timer.interval() == 5000
    window._auto_refresh.setChecked(False)
    assert not window._timer.isActive()


def test_roster_token_field_has_clear_label() -> None:
    window = mw.MainWindow()
    field = window._globals["roster_token"]
    label = window._globals_layout.labelForField(field).text()
    assert label == "Registration list token"


def test_strava_links_checkbox_round_trips() -> None:
    window = mw.MainWindow()
    window.apply_config(AppConfig(show_strava_links=True, cup=CupConfig()))
    assert window._show_strava_links.isChecked()
    assert window.collect_config().show_strava_links is True


def test_template_field_is_an_open_file_picker() -> None:
    window = mw.MainWindow()
    assert isinstance(window._template_file, mw.FilePicker)
    assert window._template_file._existing is True


def test_open_file_picker_browse_reads_existing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    picker = mw.FilePicker(existing=True)
    monkeypatch.setattr(
        mw.QFileDialog, "getOpenFileName", lambda *a, **k: ("tpl.html", "*.html")
    )
    monkeypatch.setattr(
        mw.QFileDialog, "getSaveFileName", lambda *a, **k: ("WRONG", "*.html")
    )
    picker._browse()
    assert picker.text() == "tpl.html"


def test_stage_file_paths_round_trip_through_config() -> None:
    tab = mw.StageTab(StageConfig(absolute_file="a.html", group_file="g.html"))
    config = tab.to_config()
    assert config.absolute_file == "a.html"
    assert config.group_file == "g.html"


def test_close_confirmed_saves_and_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    window = mw.MainWindow()
    monkeypatch.setattr(
        mw.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    saved: list[tuple] = []
    monkeypatch.setattr(mw, "save_config", lambda *a, **k: saved.append(a))
    event = QCloseEvent()
    event.ignore()
    window.closeEvent(event)
    assert saved
    assert event.isAccepted()


def test_close_declined_ignores_and_does_not_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = mw.MainWindow()
    monkeypatch.setattr(
        mw.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )
    saved: list[tuple] = []
    monkeypatch.setattr(mw, "save_config", lambda *a, **k: saved.append(a))
    event = QCloseEvent()
    window.closeEvent(event)
    assert not saved
    assert not event.isAccepted()
