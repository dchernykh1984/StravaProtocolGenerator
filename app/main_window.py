"""PySide6 desktop UI: edit the config, add/remove stage tabs, generate, and publish.

Coverage-omitted -- it wires the tested core (config/backup/pipeline/site_api/selenium)
to widgets and a background worker, and cannot run without a display or a browser. The
window loads the saved config on start and saves it (plus a versioned backup) on every
explicit save and on close; each generation archives the raw scraped data for replay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.backup import CONFIG_NAME, load_config, save_config, save_raw_data
from app.config import (
    AppConfig,
    CupConfig,
    HttpAction,
    SegmentConfig,
    StageConfig,
)
from app.pipeline import GenerationResult, generate
from app.scoring import CupRule, StageRule
from app.selenium_driver import SeleniumBrowser
from app.site_api import SiteApiClient

DATA_DIR = "data"
HISTORY_DIR = "temp"
ICON_PATH = str(Path(__file__).parent / "app.ico")
_CONFIG_PATH = f"{DATA_DIR}/{CONFIG_NAME}"
_ACTIONS = [a.value for a in HttpAction]
_STAGE_RULES = [r.value for r in StageRule]
_CUP_RULES = [r.value for r in CupRule]


def _combo(values: list[str], current: str) -> QComboBox:
    box = QComboBox()
    box.addItems(values)
    box.setCurrentText(current)
    return box


def _parse_segments(text: str) -> list[SegmentConfig]:
    """Parse one segment per line: ``<id> [key=value ...]`` filters."""
    segments: list[SegmentConfig] = []
    for raw in text.splitlines():
        parts = raw.split()
        if not parts:
            continue
        filters = dict(token.split("=", 1) for token in parts[1:] if "=" in token)
        segments.append(SegmentConfig(parts[0], filters))
    return segments or [SegmentConfig()]


def _segments_to_text(segments: list[SegmentConfig]) -> str:
    lines = []
    for seg in segments:
        parts = [seg.segment_id, *[f"{k}={v}" for k, v in seg.filters.items()]]
        lines.append(" ".join(parts))
    return "\n".join(lines)


class DateField(QDateEdit):
    """A calendar date picker that also represents an empty (open) collection bound.

    A stage window may be open on either side, so the minimum date doubles as "no
    date": it shows a blank special value and round-trips to an empty ISO string, while
    any real date round-trips as ``YYYY-MM-DD``.
    """

    _ISO = "yyyy-MM-dd"
    _EMPTY = QDate(1900, 1, 1)

    def __init__(self, iso: str = "") -> None:
        super().__init__()
        self.setDisplayFormat(self._ISO)
        self.setCalendarPopup(True)
        self.setMinimumDate(self._EMPTY)
        self.setSpecialValueText(" ")
        self.set_iso(iso)

    def set_iso(self, iso: str) -> None:
        parsed = QDate.fromString(iso, self._ISO)
        self.setDate(parsed if parsed.isValid() else self._EMPTY)

    def iso(self) -> str:
        return "" if self.date() == self._EMPTY else self.date().toString(self._ISO)


class FilePicker(QWidget):
    """A line edit paired with a Browse button that opens a save-file chooser.

    Exposes ``text``/``setText`` so it drops in wherever a ``QLineEdit`` held a path.
    """

    def __init__(self, value: str = "") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        button = QPushButton("Browse")
        button.clicked.connect(self._browse)
        row.addWidget(self.edit, stretch=1)
        row.addWidget(button)

    def text(self) -> str:
        return self.edit.text()

    def setText(self, value: str) -> None:  # noqa: N802 - mirrors QLineEdit
        self.edit.setText(value)

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Pick file", self.edit.text(), "*.html"
        )
        if path:
            self.edit.setText(path)


class _GenerateWorker(QThread):
    """Runs one generation off the UI thread so scraping does not freeze the window."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, config: AppConfig, publish: bool) -> None:
        super().__init__()
        self._config = config
        self._publish = publish

    def run(self) -> None:
        browser = None
        try:
            browser = SeleniumBrowser()
            browser.login(self._config.strava_login, self._config.strava_password)
            client = SiteApiClient(self._config.site_url)
            result = generate(self._config, browser, client, publish=self._publish)
            save_raw_data(result.raw_snapshot, HISTORY_DIR)
            self.done.emit(result)
        except Exception as exc:  # report any failure back to the UI log
            self.failed.emit(str(exc))
        finally:
            if browser is not None:
                browser.quit()


class StageTab(QWidget):
    """Editor for one stage's segments, rule, window, columns, and publishing."""

    def __init__(self, stage: StageConfig) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.name = QLineEdit(stage.name)
        self.segments = QPlainTextEdit(_segments_to_text(stage.segments))
        self.rule = _combo(_STAGE_RULES, stage.rule.value)
        self.date_from = DateField(stage.date_from)
        self.date_to = DateField(stage.date_to)
        self.token = QLineEdit(stage.token)
        self.is_live = QCheckBox("Live broadcast")
        self.is_live.setChecked(stage.is_live)
        self.stage_label = QLineEdit(stage.stage_label)
        self.absolute_action = _combo(_ACTIONS, stage.absolute_action.value)
        self.group_action = _combo(_ACTIONS, stage.group_action.value)
        self.absolute_file = FilePicker(stage.absolute_file)
        self.group_file = FilePicker(stage.group_file)
        self.cup_column_label = QLineEdit(stage.cup_column_label)
        self.place_label = QLineEdit(stage.place_label)
        self.name_label = QLineEdit(stage.name_label)
        self.result_label = QLineEdit(stage.result_label)
        self.show_place = QCheckBox("Show place")
        self.show_place.setChecked(stage.show_place)
        self.show_name = QCheckBox("Show name")
        self.show_name.setChecked(stage.show_name)

        form.addRow("Stage name", self.name)
        form.addRow("Segments (id [key=value])", self.segments)
        form.addRow("Feed to cup", self.rule)
        form.addRow("Date from (including)", self.date_from)
        form.addRow("Date to (including)", self.date_to)
        form.addRow("Broadcast token", self.token)
        form.addRow("", self.is_live)
        form.addRow("Stage label", self.stage_label)
        form.addRow("Absolute protocol", self.absolute_action)
        form.addRow("Group protocol", self.group_action)
        form.addRow("Absolute file", self.absolute_file)
        form.addRow("Group file", self.group_file)
        form.addRow("Cup column label", self.cup_column_label)
        form.addRow("Place label", self.place_label)
        form.addRow("Name label", self.name_label)
        form.addRow("Result label", self.result_label)
        form.addRow("", self.show_place)
        form.addRow("", self.show_name)

    def to_config(self) -> StageConfig:
        return StageConfig(
            name=self.name.text(),
            segments=_parse_segments(self.segments.toPlainText()),
            rule=StageRule(self.rule.currentText()),
            date_from=self.date_from.iso(),
            date_to=self.date_to.iso(),
            token=self.token.text().strip(),
            is_live=self.is_live.isChecked(),
            stage_label=self.stage_label.text(),
            absolute_action=HttpAction(self.absolute_action.currentText()),
            group_action=HttpAction(self.group_action.currentText()),
            absolute_file=self.absolute_file.text().strip(),
            group_file=self.group_file.text().strip(),
            cup_column_label=self.cup_column_label.text(),
            place_label=self.place_label.text(),
            name_label=self.name_label.text(),
            result_label=self.result_label.text(),
            show_place=self.show_place.isChecked(),
            show_name=self.show_name.isChecked(),
        )


class CupPanel(QWidget):
    """Editor for the overall cup: rule, token, columns, files, and publishing."""

    def __init__(self, cup: CupConfig) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.name = QLineEdit(cup.name)
        self.rule = _combo(_CUP_RULES, cup.cup_rule.value)
        self.token = QLineEdit(cup.token)
        self.is_live = QCheckBox("Live broadcast")
        self.is_live.setChecked(cup.is_live)
        self.stage_label = QLineEdit(cup.stage_label)
        self.absolute_action = _combo(_ACTIONS, cup.absolute_action.value)
        self.group_action = _combo(_ACTIONS, cup.group_action.value)
        self.absolute_file = FilePicker(cup.absolute_file)
        self.group_file = FilePicker(cup.group_file)
        self.place_label = QLineEdit(cup.place_label)
        self.name_label = QLineEdit(cup.name_label)
        self.total_label = QLineEdit(cup.total_label)
        self.show_place = QCheckBox("Show place")
        self.show_place.setChecked(cup.show_place)
        self.show_name = QCheckBox("Show name")
        self.show_name.setChecked(cup.show_name)

        form.addRow("Cup name", self.name)
        form.addRow("Combine rule", self.rule)
        form.addRow("Overall token", self.token)
        form.addRow("", self.is_live)
        form.addRow("Stage label", self.stage_label)
        form.addRow("Absolute protocol", self.absolute_action)
        form.addRow("Group protocol", self.group_action)
        form.addRow("Absolute file", self.absolute_file)
        form.addRow("Group file", self.group_file)
        form.addRow("Place label", self.place_label)
        form.addRow("Name label", self.name_label)
        form.addRow("Total label", self.total_label)
        form.addRow("", self.show_place)
        form.addRow("", self.show_name)

    def to_config(self) -> CupConfig:
        return CupConfig(
            name=self.name.text(),
            cup_rule=CupRule(self.rule.currentText()),
            token=self.token.text().strip(),
            is_live=self.is_live.isChecked(),
            stage_label=self.stage_label.text(),
            absolute_action=HttpAction(self.absolute_action.currentText()),
            group_action=HttpAction(self.group_action.currentText()),
            absolute_file=self.absolute_file.text().strip(),
            group_file=self.group_file.text().strip(),
            place_label=self.place_label.text(),
            name_label=self.name_label.text(),
            total_label=self.total_label.text(),
            show_place=self.show_place.isChecked(),
            show_name=self.show_name.isChecked(),
        )


class MainWindow(QMainWindow):
    """Main window: global settings, a tab per stage, the cup panel, and actions."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Strava Protocol Generator")
        self.setWindowIcon(QIcon(ICON_PATH))
        self._worker: _GenerateWorker | None = None
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self._globals = self._build_globals()
        root.addLayout(self._globals_layout)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)
        root.addLayout(self._build_stage_buttons())

        root.addWidget(QLabel("Cup"))
        self._cup = CupPanel(CupConfig())
        root.addWidget(self._cup)

        root.addLayout(self._build_action_buttons())

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        root.addWidget(self._log)

        self.apply_config(load_config(_CONFIG_PATH))

    # -- construction helpers ------------------------------------------------

    def _build_globals(self) -> dict[str, QLineEdit]:
        self._globals_layout = QFormLayout()
        widgets: dict[str, QLineEdit] = {
            "site_url": QLineEdit(),
            "strava_login": QLineEdit(),
            "strava_password": QLineEdit(),
            "roster_token": QLineEdit(),
            "unregistered_group_name": QLineEdit(),
            "template_file": QLineEdit(),
            "output_dir": QLineEdit(),
        }
        widgets["strava_password"].setEchoMode(QLineEdit.EchoMode.Password)
        self._decimals = QSpinBox()
        self._decimals.setRange(0, 4)
        self._globals_layout.addRow("Site URL", widgets["site_url"])
        self._globals_layout.addRow("Strava login", widgets["strava_login"])
        self._globals_layout.addRow("Strava password", widgets["strava_password"])
        self._globals_layout.addRow("Roster token", widgets["roster_token"])
        self._globals_layout.addRow(
            "Unregistered group", widgets["unregistered_group_name"]
        )
        self._globals_layout.addRow("Decimals", self._decimals)
        self._globals_layout.addRow("Template file", widgets["template_file"])
        self._globals_layout.addRow("Output dir", widgets["output_dir"])
        return widgets

    def _build_stage_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        add = QPushButton("Add stage")
        add.clicked.connect(self._on_add_stage)
        remove = QPushButton("Delete stage")
        remove.clicked.connect(self._on_delete_stage)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        return row

    def _build_action_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        generate_btn = QPushButton("Generate and publish")
        generate_btn.clicked.connect(lambda: self._on_generate(publish=True))
        local_btn = QPushButton("Generate locally")
        local_btn.clicked.connect(lambda: self._on_generate(publish=False))
        save_btn = QPushButton("Save config")
        save_btn.clicked.connect(self._on_save)
        template_btn = QPushButton("Pick template")
        template_btn.clicked.connect(self._on_pick_template)
        row.addWidget(generate_btn)
        row.addWidget(local_btn)
        row.addWidget(save_btn)
        row.addWidget(template_btn)
        row.addStretch(1)
        return row

    # -- config <-> widgets --------------------------------------------------

    def collect_config(self) -> AppConfig:
        stages = [self._tabs.widget(i).to_config() for i in range(self._tabs.count())]
        return AppConfig(
            site_url=self._globals["site_url"].text().strip(),
            strava_login=self._globals["strava_login"].text().strip(),
            strava_password=self._globals["strava_password"].text(),
            roster_token=self._globals["roster_token"].text().strip(),
            unregistered_group_name=self._globals["unregistered_group_name"].text(),
            decimals=self._decimals.value(),
            template_file=self._globals["template_file"].text().strip(),
            output_dir=self._globals["output_dir"].text().strip() or "output",
            stages=stages or [StageConfig()],
            cup=self._cup.to_config(),
        )

    def apply_config(self, config: AppConfig) -> None:
        self._globals["site_url"].setText(config.site_url)
        self._globals["strava_login"].setText(config.strava_login)
        self._globals["strava_password"].setText(config.strava_password)
        self._globals["roster_token"].setText(config.roster_token)
        self._globals["unregistered_group_name"].setText(config.unregistered_group_name)
        self._decimals.setValue(config.decimals)
        self._globals["template_file"].setText(config.template_file)
        self._globals["output_dir"].setText(config.output_dir)
        self._tabs.clear()
        for stage in config.stages:
            self._add_stage_tab(stage)
        self._cup = self._replace_cup(config.cup)

    def _replace_cup(self, cup: CupConfig) -> CupPanel:
        new_panel = CupPanel(cup)
        self.centralWidget().layout().replaceWidget(self._cup, new_panel)
        self._cup.deleteLater()
        return new_panel

    def _add_stage_tab(self, stage: StageConfig, index: int | None = None) -> None:
        tab = StageTab(stage)
        at = self._tabs.count() if index is None else index
        self._tabs.insertTab(at, tab, stage.name or f"Stage {at + 1}")
        tab.name.textChanged.connect(
            lambda text, t=tab: self._update_tab_title(t, text)
        )
        self._tabs.setCurrentIndex(at)

    def _update_tab_title(self, tab: StageTab, text: str) -> None:
        """Keep a stage's tab label in sync with its edited name."""
        index = self._tabs.indexOf(tab)
        if index >= 0:
            self._tabs.setTabText(index, text or f"Stage {index + 1}")

    # -- actions -------------------------------------------------------------

    def _on_add_stage(self) -> None:
        current = self._tabs.currentWidget()
        template = current.to_config() if current is not None else StageConfig()
        self._add_stage_tab(template, index=self._tabs.currentIndex() + 1)

    def _on_delete_stage(self) -> None:
        if self._tabs.count() <= 1:
            self._log.appendPlainText("At least one stage is required.")
            return
        self._tabs.removeTab(self._tabs.currentIndex())

    def _on_pick_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pick template", "", "*.html")
        if path:
            self._globals["template_file"].setText(path)

    def _on_save(self) -> None:
        save_config(self.collect_config(), DATA_DIR, HISTORY_DIR)
        self._log.appendPlainText("Config saved.")

    def _on_generate(self, publish: bool) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._log.appendPlainText("A generation is already running.")
            return
        config = self.collect_config()
        save_config(config, DATA_DIR, HISTORY_DIR)
        self._log.appendPlainText("Generating...")
        self._worker = _GenerateWorker(config, publish)
        self._worker.done.connect(self._on_generation_done)
        self._worker.failed.connect(self._on_generation_failed)
        self._worker.start()

    def _on_generation_done(self, result: Any) -> None:
        generation: GenerationResult = result
        for error in generation.errors:
            self._log.appendPlainText(f"! {error}")
        for output in generation.outputs:
            status = "published" if output.published else "local"
            if output.error:
                status = f"publish failed: {output.error}"
            self._log.appendPlainText(
                f"{output.kind}/{output.scope} {output.label}: {output.path} ({status})"
            )
        self._log.appendPlainText("Done.")

    def _on_generation_failed(self, message: str) -> None:
        self._log.appendPlainText(f"Generation failed: {message}")

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override name
        reply = QMessageBox.question(
            self,
            "Exit",
            "Are you sure you want to exit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        save_config(self.collect_config(), DATA_DIR, HISTORY_DIR)
        super().closeEvent(event)
