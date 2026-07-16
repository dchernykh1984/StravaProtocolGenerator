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

from app.backup import (
    CONFIG_NAME,
    RAWDATA_NAME,
    load_config,
    load_raw_data,
    save_config,
    save_raw_data,
)
from app.config import (
    AppConfig,
    CupConfig,
    DateRange,
    FilterType,
    Gender,
    HttpAction,
    SegmentConfig,
    StageConfig,
)
from app.leaderboard_api import StravaAuthError, StravaLeaderboard
from app.pipeline import GenerationResult, generate
from app.scoring import CupRule, StageRule
from app.selenium_driver import SeleniumBrowser
from app.site_api import SiteApiClient

DATA_DIR = "data"
HISTORY_DIR = "temp"
LOG_DIR = "logs"
ICON_PATH = str(Path(__file__).parent / "app.ico")
_CONFIG_PATH = f"{DATA_DIR}/{CONFIG_NAME}"
_RAWDATA_PATH = f"{DATA_DIR}/{RAWDATA_NAME}"
_ACTIONS = [a.value for a in HttpAction]
_STAGE_RULES = [r.value for r in StageRule]
_CUP_RULES = [r.value for r in CupRule]
_DATE_RANGES = [d.value for d in DateRange]
_GENDERS = [g.value for g in Gender]
_FILTER_TYPES = [f.value for f in FilterType]


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


class SegmentRow(QWidget):
    """One segment's editor: its id plus the Strava leaderboard filter dropdowns."""

    def __init__(self, segment: SegmentConfig) -> None:
        super().__init__()
        self.segment_id = QLineEdit(segment.segment_id)
        self.segment_id.setPlaceholderText("segment id")
        self.date_range = _combo(_DATE_RANGES, segment.date_range.value)
        self.gender = _combo(_GENDERS, segment.gender.value)
        self.filter_type = _combo(_FILTER_TYPES, segment.filter_type.value)
        self.remove = QToolButton()
        self.remove.setText("x")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.segment_id, stretch=1)
        row.addWidget(self.date_range)
        row.addWidget(self.gender)
        row.addWidget(self.filter_type)
        row.addWidget(self.remove)

    def to_config(self) -> SegmentConfig:
        return SegmentConfig(
            segment_id=self.segment_id.text().split()[0]
            if self.segment_id.text().split()
            else "",
            date_range=DateRange(self.date_range.currentText()),
            gender=Gender(self.gender.currentText()),
            filter_type=FilterType(self.filter_type.currentText()),
        )


class SegmentList(QWidget):
    """A stage's segments as a growable list of ``SegmentRow`` editors."""

    def __init__(self, segments: list[SegmentConfig]) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(QLabel("id"), stretch=1)
        header.addWidget(QLabel("date range"))
        header.addWidget(QLabel("gender"))
        header.addWidget(QLabel("filter"))
        self._layout.addLayout(header)
        self.rows: list[SegmentRow] = []
        self._add_button = QPushButton("Add segment")
        self._add_button.clicked.connect(lambda: self.add_segment())
        # Add the button first so every row is inserted just above it.
        self._layout.addWidget(self._add_button)
        for segment in segments or [SegmentConfig()]:
            self.add_segment(segment)

    def add_segment(self, segment: SegmentConfig | None = None) -> SegmentRow:
        row = SegmentRow(segment or SegmentConfig())
        row.remove.clicked.connect(lambda: self._remove(row))
        self.rows.append(row)
        # Keep the "Add segment" button below the rows.
        self._layout.insertWidget(self._layout.count() - 1, row)
        return row

    def _remove(self, row: SegmentRow) -> None:
        if len(self.rows) <= 1:
            return  # always keep at least one segment row
        self.rows.remove(row)
        row.setParent(None)

    def to_config(self) -> list[SegmentConfig]:
        segments = [r.to_config() for r in self.rows]
        return segments or [SegmentConfig()]


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


class _LoginWorker(QThread):
    """Opens a real browser and waits for the user to sign in to Strava by hand."""

    done = Signal(object)  # captured cookies
    failed = Signal(str)

    def run(self) -> None:
        browser = None
        try:
            browser = SeleniumBrowser(diagnostics_dir=LOG_DIR)
            self.done.emit(browser.wait_for_manual_login())
        except Exception as exc:  # report any failure back to the UI log
            self.failed.emit(str(exc))
        finally:
            if browser is not None:
                browser.quit()


class _GenerateWorker(QThread):
    """Runs one generation off the UI thread so scraping does not freeze the window."""

    done = Signal(object)
    failed = Signal(str)
    request_logged = Signal(str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._previous = load_raw_data(_RAWDATA_PATH)

    def _log_request(self, url: str) -> None:
        self.request_logged.emit(f"GET {url}")

    def run(self) -> None:
        try:
            client = SiteApiClient(self._config.site_url)
            result = self._generate_authenticated(client)
            save_raw_data(result.raw_snapshot, DATA_DIR, HISTORY_DIR)
            self.done.emit(result)
        except Exception as exc:  # report any failure back to the UI log
            self.failed.emit(str(exc))

    def _generate_authenticated(self, client: SiteApiClient) -> GenerationResult:
        """Read the leaderboards over the saved session; frozen stages skip Strava.

        Each protocol's own action (Nothing/Upload/Delete) decides what reaches the
        site, so generation always runs the publish path. A stage that needs scraping
        without a valid session fails with a clear "log in" message rather than trying
        to automate the (reCAPTCHA-guarded) sign-in.
        """
        leaderboard = StravaLeaderboard(
            self._config.strava_cookies, on_request=self._log_request
        )
        try:
            return generate(
                self._config, leaderboard, client, publish=True, previous=self._previous
            )
        except StravaAuthError as exc:
            raise RuntimeError(
                "Strava session is missing or expired -- click 'Login to Strava'."
            ) from exc


class StageTab(QWidget):
    """Editor for one stage's segments, rule, window, columns, and publishing."""

    def __init__(self, stage: StageConfig) -> None:
        super().__init__()
        self.name = QLineEdit(stage.name)
        self.segments = SegmentList(stage.segments)
        self.rule = _combo(_STAGE_RULES, stage.rule.value)
        self.date_from = DateField(stage.date_from)
        self.date_to = DateField(stage.date_to)
        self.token = QLineEdit(stage.token)
        self.is_live = QCheckBox("Live broadcast")
        self.is_live.setChecked(stage.is_live)
        self.freeze_strava_data = QCheckBox("Freeze Strava data")
        self.freeze_strava_data.setChecked(stage.freeze_strava_data)
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
        self.unregistered_group_name = QLineEdit(stage.unregistered_group_name)
        self.show_unregistered = QCheckBox("Show")
        self.show_unregistered.setChecked(stage.show_unregistered)

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
        self._left_form.addRow("Segments", self.segments)
        self._left_form.addRow("Feed to cup", self.rule)
        self._left_form.addRow("Date from (including)", self.date_from)
        self._left_form.addRow("Date to (including)", self.date_to)
        self._left_form.addRow("Broadcast token (to Site URL)", self.token)
        self._left_form.addRow("", self.is_live)
        self._left_form.addRow("", self.freeze_strava_data)
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
        self._right_form.addRow(
            "Unregistered group",
            _field_with_checkbox(self.unregistered_group_name, self.show_unregistered),
        )

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
            segments=self.segments.to_config(),
            rule=StageRule(self.rule.currentText()),
            date_from=self.date_from.iso(),
            date_to=self.date_to.iso(),
            freeze_strava_data=self.freeze_strava_data.isChecked(),
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
            unregistered_group_name=self.unregistered_group_name.text(),
            show_unregistered=self.show_unregistered.isChecked(),
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
        self.unregistered_group_name = QLineEdit(cup.unregistered_group_name)
        self.show_unregistered = QCheckBox("Show")
        self.show_unregistered.setChecked(cup.show_unregistered)

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
        form.addRow(
            "Unregistered group",
            _field_with_checkbox(self.unregistered_group_name, self.show_unregistered),
        )

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
            unregistered_group_name=self.unregistered_group_name.text(),
            show_unregistered=self.show_unregistered.isChecked(),
        )


class MainWindow(QMainWindow):
    """Main window: global settings, a tab per stage, the cup panel, and actions."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Strava Protocol Generator")
        self.setWindowIcon(QIcon(ICON_PATH))
        self._worker: _GenerateWorker | None = None
        self._login_worker: _LoginWorker | None = None
        self._timer: QTimer | None = None
        self._strava_cookies: list[dict[str, Any]] = []
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        self._main_tabs = QTabWidget()
        root.addWidget(self._main_tabs)

        # Main tab: global settings, the shared action buttons, and the log.
        main_tab = QWidget()
        main_layout = QVBoxLayout(main_tab)
        self._globals = self._build_globals()
        main_layout.addLayout(self._globals_layout)
        main_layout.addLayout(self._build_action_buttons())
        self._log_to_file = QCheckBox("Log to file")
        main_layout.addWidget(self._log_to_file)
        self._log_file: Path | None = None
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        main_layout.addWidget(self._log, stretch=1)
        self._main_tabs.addTab(main_tab, "Main")

        # Cup tab: the overall-cup protocol settings.
        cup_tab = QWidget()
        self._cup_layout = QVBoxLayout(cup_tab)
        self._cup = CupPanel(CupConfig())
        self._cup_layout.addWidget(self._cup)
        self._cup_layout.addStretch(1)
        self._main_tabs.addTab(cup_tab, "Cup")

        # Stages tab: a sub-tab per stage plus the add/delete controls.
        stages_tab = QWidget()
        stages_layout = QVBoxLayout(stages_tab)
        self._tabs = QTabWidget()
        stages_layout.addWidget(self._tabs, stretch=1)
        stages_layout.addLayout(self._build_stage_buttons())
        self._main_tabs.addTab(stages_tab, "Stages")

        self.apply_config(load_config(_CONFIG_PATH))

    # -- construction helpers ------------------------------------------------

    def _build_globals(self) -> dict[str, QLineEdit]:
        self._globals_layout = QFormLayout()
        widgets: dict[str, QLineEdit] = {
            "site_url": QLineEdit(),
            "roster_token": QLineEdit(),
            "output_dir": QLineEdit(),
        }
        self._template_file = FilePicker(existing=True)
        self._decimals = QSpinBox()
        self._decimals.setRange(0, 4)
        self._show_strava_links = QCheckBox("Add Strava links")
        self._globals_layout.addRow("Site URL", widgets["site_url"])
        self._globals_layout.addRow("Registration list token", widgets["roster_token"])
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
        login_btn = QPushButton("Login to Strava")
        login_btn.clicked.connect(self._on_login)
        generate_btn = QPushButton("Generate")
        generate_btn.clicked.connect(self._on_generate)
        self._auto_refresh = QCheckBox("Auto-refresh")
        self._auto_refresh.toggled.connect(self._on_refresh_toggled)
        self._interval = QSpinBox()
        self._interval.setRange(1, 3600)
        self._interval.setValue(30)
        save_btn = QPushButton("Save config")
        save_btn.clicked.connect(self._on_save)
        row.addWidget(login_btn)
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
            strava_cookies=self._strava_cookies,
            roster_token=self._globals["roster_token"].text().strip(),
            decimals=self._decimals.value(),
            show_strava_links=self._show_strava_links.isChecked(),
            log_to_file=self._log_to_file.isChecked(),
            template_file=self._template_file.text().strip(),
            output_dir=self._globals["output_dir"].text().strip() or "output",
            stages=stages or [StageConfig()],
            cup=self._cup.to_config(),
        )

    def apply_config(self, config: AppConfig) -> None:
        self._strava_cookies = config.strava_cookies
        self._globals["site_url"].setText(config.site_url)
        self._globals["roster_token"].setText(config.roster_token)
        self._decimals.setValue(config.decimals)
        self._show_strava_links.setChecked(config.show_strava_links)
        self._log_to_file.setChecked(config.log_to_file)
        self._template_file.setText(config.template_file)
        self._globals["output_dir"].setText(config.output_dir)
        self._tabs.clear()
        for stage in config.stages:
            self._add_stage_tab(stage)
        self._cup = self._replace_cup(config.cup)

    def _replace_cup(self, cup: CupConfig) -> CupPanel:
        new_panel = CupPanel(cup)
        self._cup_layout.replaceWidget(self._cup, new_panel)
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
        self._worker.request_logged.connect(self._append_log)
        self._worker.start()

    def _on_login(self) -> None:
        if self._login_worker is not None and self._login_worker.isRunning():
            self._append_log("A Strava login is already in progress.")
            return
        self._append_log("Opening Strava in a browser -- sign in there by hand...")
        self._login_worker = _LoginWorker()
        self._login_worker.done.connect(self._on_login_done)
        self._login_worker.failed.connect(self._on_login_failed)
        self._login_worker.start()

    def _on_login_done(self, cookies: Any) -> None:
        """Persist the manually captured Strava session so runs reuse it for weeks."""
        self._strava_cookies = cookies
        save_config(self.collect_config(), DATA_DIR, HISTORY_DIR)
        self._append_log("Logged in to Strava; the session was saved.")

    def _on_login_failed(self, message: str) -> None:
        self._append_log(f"Strava login failed: {message}")

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
