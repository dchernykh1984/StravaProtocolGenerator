"""PySide6 desktop UI: edit the config, add/remove stage tabs, generate, and publish.

Coverage-omitted -- it wires the tested core (config/backup/pipeline/site_api/selenium)
to widgets and a background worker, and cannot run without a display or a browser. The
window loads the saved config on start and saves it (plus a versioned backup) on every
explicit save and on close; each generation archives the raw scraped data for replay.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QComboBox,
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
    QToolButton,
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
from app.http_browser import HttpBrowser, StravaAuthError
from app.pipeline import GenerationResult, generate
from app.scoring import CupRule, StageRule
from app.selenium_driver import SeleniumBrowser
from app.site_api import SiteApiClient

DATA_DIR = "data"
HISTORY_DIR = "temp"
LOG_DIR = "logs"
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


def _field_with_checkbox(field: QWidget, checkbox: QCheckBox) -> QHBoxLayout:
    """Pack a field and a trailing checkbox onto one form row to save height."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(field, stretch=1)
    row.addWidget(checkbox)
    return row


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


class DateField(QWidget):
    """An ISO date entry: a free-text field with a calendar popup for convenience.

    Typing is primary, so any string is kept verbatim -- an empty open bound, a partial
    date, or a full ``YYYY-MM-DD`` all survive losing focus (a plain ``QDateEdit`` reset
    text it could not parse section-by-section). The calendar button just fills the
    field with a chosen date.
    """

    _ISO = "yyyy-MM-dd"

    def __init__(self, iso: str = "") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(iso)
        self.edit.setPlaceholderText("YYYY-MM-DD")
        button = QToolButton()
        button.setArrowType(Qt.ArrowType.DownArrow)
        button.clicked.connect(self._open_calendar)
        row.addWidget(self.edit, stretch=1)
        row.addWidget(button)

    def set_iso(self, iso: str) -> None:
        self.edit.setText(iso)

    def iso(self) -> str:
        return self.edit.text().strip()

    def _open_calendar(self) -> None:
        calendar = QCalendarWidget()
        calendar.setWindowFlags(Qt.WindowType.Popup)
        current = QDate.fromString(self.iso(), self._ISO)
        if current.isValid():
            calendar.setSelectedDate(current)
        calendar.clicked.connect(self._apply_date)
        calendar.clicked.connect(calendar.close)
        calendar.move(self.edit.mapToGlobal(self.edit.rect().bottomLeft()))
        calendar.show()
        self._calendar = calendar

    def _apply_date(self, chosen: QDate) -> None:
        self.edit.setText(chosen.toString(self._ISO))


class FilePicker(QWidget):
    """A line edit paired with a Browse button that opens a file chooser.

    Exposes ``text``/``setText`` so it drops in wherever a ``QLineEdit`` held a path.
    ``existing`` chooses an existing file to read (e.g. a template) rather than a save
    target.
    """

    def __init__(self, value: str = "", *, existing: bool = False) -> None:
        super().__init__()
        self._existing = existing
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
        dialog = (
            QFileDialog.getOpenFileName
            if self._existing
            else QFileDialog.getSaveFileName
        )
        path, _ = dialog(self, "Pick file", self.edit.text(), "*.html")
        if path:
            self.edit.setText(path)


class _GenerateWorker(QThread):
    """Runs one generation off the UI thread so scraping does not freeze the window."""

    done = Signal(object)
    failed = Signal(str)
    cookies_refreshed = Signal(object)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config

    def run(self) -> None:
        try:
            client = SiteApiClient(self._config.site_url)
            result = self._generate_authenticated(client)
            save_raw_data(result.raw_snapshot, HISTORY_DIR)
            self.done.emit(result)
        except Exception as exc:  # report any failure back to the UI log
            self.failed.emit(str(exc))

    def _generate_authenticated(self, client: SiteApiClient) -> GenerationResult:
        """Scrape with saved cookies; log in once (and re-cache) only when needed.

        Each protocol's own action (Nothing/Upload/Delete) decides what reaches the
        site, so generation always runs the publish path.
        """
        if self._config.strava_cookies:
            try:
                browser = HttpBrowser(self._config.strava_cookies)
                return generate(self._config, browser, client, publish=True)
            except StravaAuthError:
                pass  # session expired -> log in again and refresh the cookies below
        browser = self._login_and_capture()
        return generate(self._config, browser, client, publish=True)

    def _login_and_capture(self) -> HttpBrowser:
        """Log in with a real browser once, then scrape over its cookies via HTTP.

        A failed login raises and caches nothing, so the next run just tries again.
        """
        selenium = SeleniumBrowser()
        try:
            selenium.login(self._config.strava_login, self._config.strava_password)
            cookies = selenium.cookies()
        finally:
            selenium.quit()
        self.cookies_refreshed.emit(cookies)
        return HttpBrowser(cookies)


class StageTab(QWidget):
    """Editor for one stage's segments, rule, window, columns, and publishing."""

    def __init__(self, stage: StageConfig) -> None:
        super().__init__()
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

        # Two form columns halve the stage's height so the window fits on screen.
        columns = QHBoxLayout(self)
        left = QVBoxLayout()
        right = QVBoxLayout()
        self._left_form = QFormLayout()
        self._right_form = QFormLayout()
        left.addLayout(self._left_form)
        left.addStretch(1)
        right.addLayout(self._right_form)
        right.addStretch(1)
        columns.addLayout(left, stretch=1)
        columns.addLayout(right, stretch=1)

        self._left_form.addRow("Stage name", self.name)
        self._left_form.addRow("Segments (id [key=value])", self.segments)
        self._left_form.addRow("Feed to cup", self.rule)
        self._left_form.addRow("Date from (including)", self.date_from)
        self._left_form.addRow("Date to (including)", self.date_to)
        self._left_form.addRow("Broadcast token (to Site URL)", self.token)
        self._left_form.addRow("", self.is_live)
        self._left_form.addRow("Stage label", self.stage_label)

        self._right_form.addRow("Absolute protocol", self.absolute_action)
        self._right_form.addRow("Group protocol", self.group_action)
        self._right_form.addRow("Absolute file", self.absolute_file)
        self._right_form.addRow("Group file", self.group_file)
        self._right_form.addRow("Cup column label", self.cup_column_label)
        self._right_form.addRow("Place label", self.place_label)
        self._right_form.addRow("Name label", self.name_label)
        self._right_form.addRow("Result label", self.result_label)
        self._right_form.addRow("", self.show_place)
        self._right_form.addRow("", self.show_name)

    def field_label(self, widget: QWidget) -> str:
        """Return the text of the form label paired with ``widget`` (for tests/UX)."""
        for form in (self._left_form, self._right_form):
            label = form.labelForField(widget)
            if label is not None:
                return label.text()
        return ""

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
        form.addRow("Overall token", _field_with_checkbox(self.token, self.is_live))
        form.addRow("Stage label", self.stage_label)
        form.addRow("Absolute protocol", self.absolute_action)
        form.addRow("Group protocol", self.group_action)
        form.addRow("Absolute file", self.absolute_file)
        form.addRow("Group file", self.group_file)
        form.addRow(
            "Place label", _field_with_checkbox(self.place_label, self.show_place)
        )
        form.addRow("Name label", _field_with_checkbox(self.name_label, self.show_name))
        form.addRow("Total label", self.total_label)

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
        self._timer: QTimer | None = None
        self._strava_cookies: list[dict[str, Any]] = []
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Globals and the cup share one two-column row above the stages so the window
        # stays short enough to fit on screen.
        self._globals = self._build_globals()
        top = QHBoxLayout()
        left = QVBoxLayout()
        left.addLayout(self._globals_layout)
        left.addStretch(1)
        right = QVBoxLayout()
        self._cup = CupPanel(CupConfig())
        right.addWidget(self._cup)
        right.addStretch(1)
        top.addLayout(left, stretch=1)
        top.addLayout(right, stretch=1)
        root.addLayout(top)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)
        root.addLayout(self._build_stage_buttons())

        root.addLayout(self._build_action_buttons())

        self._log_to_file = QCheckBox("Log to file")
        root.addWidget(self._log_to_file)
        self._log_file: Path | None = None
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
            "output_dir": QLineEdit(),
        }
        self._template_file = FilePicker(existing=True)
        self._decimals = QSpinBox()
        self._decimals.setRange(0, 4)
        self._show_strava_links = QCheckBox("Add Strava links")
        self._globals_layout.addRow("Site URL", widgets["site_url"])
        self._globals_layout.addRow("Strava login", widgets["strava_login"])
        self._globals_layout.addRow("Strava password", widgets["strava_password"])
        self._globals_layout.addRow("Roster token", widgets["roster_token"])
        self._globals_layout.addRow(
            "Unregistered group", widgets["unregistered_group_name"]
        )
        self._globals_layout.addRow("Decimals", self._decimals)
        self._globals_layout.addRow("", self._show_strava_links)
        self._globals_layout.addRow("Template file", self._template_file)
        self._globals_layout.addRow("Output dir", widgets["output_dir"])
        return widgets

    def _build_stage_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        add_left = QPushButton("Add stage left")
        add_left.clicked.connect(lambda: self._add_stage_copy(0))
        add_right = QPushButton("Add stage right")
        add_right.clicked.connect(lambda: self._add_stage_copy(1))
        remove = QPushButton("Delete stage")
        remove.clicked.connect(self._on_delete_stage)
        row.addWidget(add_left)
        row.addWidget(add_right)
        row.addWidget(remove)
        row.addStretch(1)
        return row

    def _build_action_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        generate_btn = QPushButton("Generate")
        generate_btn.clicked.connect(self._on_generate)
        self._auto_refresh = QCheckBox("Auto-refresh")
        self._auto_refresh.toggled.connect(self._on_refresh_toggled)
        self._interval = QSpinBox()
        self._interval.setRange(1, 3600)
        self._interval.setValue(30)
        save_btn = QPushButton("Save config")
        save_btn.clicked.connect(self._on_save)
        row.addWidget(generate_btn)
        row.addWidget(self._auto_refresh)
        row.addWidget(QLabel("Interval (sec):"))
        row.addWidget(self._interval)
        row.addWidget(save_btn)
        row.addStretch(1)
        return row

    # -- config <-> widgets --------------------------------------------------

    def collect_config(self) -> AppConfig:
        stages = [self._tabs.widget(i).to_config() for i in range(self._tabs.count())]
        return AppConfig(
            site_url=self._globals["site_url"].text().strip(),
            strava_login=self._globals["strava_login"].text().strip(),
            strava_password=self._globals["strava_password"].text(),
            strava_cookies=self._strava_cookies,
            roster_token=self._globals["roster_token"].text().strip(),
            unregistered_group_name=self._globals["unregistered_group_name"].text(),
            decimals=self._decimals.value(),
            show_strava_links=self._show_strava_links.isChecked(),
            template_file=self._template_file.text().strip(),
            output_dir=self._globals["output_dir"].text().strip() or "output",
            stages=stages or [StageConfig()],
            cup=self._cup.to_config(),
        )

    def apply_config(self, config: AppConfig) -> None:
        self._strava_cookies = config.strava_cookies
        self._globals["site_url"].setText(config.site_url)
        self._globals["strava_login"].setText(config.strava_login)
        self._globals["strava_password"].setText(config.strava_password)
        self._globals["roster_token"].setText(config.roster_token)
        self._globals["unregistered_group_name"].setText(config.unregistered_group_name)
        self._decimals.setValue(config.decimals)
        self._show_strava_links.setChecked(config.show_strava_links)
        self._template_file.setText(config.template_file)
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

    def _add_stage_copy(self, offset: int) -> None:
        """Insert a copy of the current stage beside it (offset 0 left, 1 right)."""
        current = self._tabs.currentWidget()
        template = current.to_config() if current is not None else StageConfig()
        self._add_stage_tab(template, index=self._tabs.currentIndex() + offset)

    def _append_log(self, message: str) -> None:
        """Append a line to the on-screen log, mirroring it to a file when enabled."""
        self._log.appendPlainText(message)
        if self._log_to_file.isChecked():
            self._write_log_line(message)

    def _write_log_line(self, message: str) -> None:
        if self._log_file is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_file = Path(LOG_DIR) / f"session_{ts}.log"
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
        with self._log_file.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    def _on_delete_stage(self) -> None:
        if self._tabs.count() <= 1:
            self._append_log("At least one stage is required.")
            return
        self._tabs.removeTab(self._tabs.currentIndex())

    def _on_save(self) -> None:
        save_config(self.collect_config(), DATA_DIR, HISTORY_DIR)
        self._append_log("Config saved.")

    def _on_generate(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._append_log("A generation is already running.")
            return
        config = self.collect_config()
        save_config(config, DATA_DIR, HISTORY_DIR)
        self._append_log("Generating...")
        self._worker = _GenerateWorker(config)
        self._worker.done.connect(self._on_generation_done)
        self._worker.failed.connect(self._on_generation_failed)
        self._worker.cookies_refreshed.connect(self._on_cookies_refreshed)
        self._worker.start()

    def _on_cookies_refreshed(self, cookies: Any) -> None:
        """Persist a freshly captured Strava session so later runs skip the login."""
        self._strava_cookies = cookies
        save_config(self.collect_config(), DATA_DIR, HISTORY_DIR)

    def _on_refresh_toggled(self, checked: bool) -> None:
        """Start or stop periodic regeneration at the configured interval."""
        if checked:
            if self._timer is None:
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._on_generate)
            self._timer.start(self._interval.value() * 1000)
        elif self._timer is not None:
            self._timer.stop()

    def _on_generation_done(self, result: Any) -> None:
        generation: GenerationResult = result
        for error in generation.errors:
            self._append_log(f"! {error}")
        for output in generation.outputs:
            status = "published" if output.published else "local"
            if output.error:
                status = f"publish failed: {output.error}"
            self._append_log(
                f"{output.kind}/{output.scope} {output.label}: {output.path} ({status})"
            )
        self._append_log("Done.")

    def _on_generation_failed(self, message: str) -> None:
        self._append_log(f"Generation failed: {message}")

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
