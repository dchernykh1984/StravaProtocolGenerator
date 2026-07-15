"""Qt-level tests for the main window.

``main_window`` is excluded from coverage, so these run under the offscreen Qt platform
to guard the widget wiring (here: the stage tab label tracking the stage name field).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app import main_window as mw

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
    window._on_add_stage()
    new_index = window._tabs.currentIndex()
    window._tabs.widget(new_index).name.setText("Day 2")
    assert window._tabs.tabText(new_index) == "Day 2"


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
