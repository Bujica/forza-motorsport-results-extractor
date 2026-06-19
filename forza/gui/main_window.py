from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..app_info import (
    APP_NAME,
    APP_RELEASE,
    APP_SHORT_NAME,
    BUILD_INFO_FILENAME,
    ISSUES_URL,
    LEGAL_NOTICE,
    LICENSE_NAME,
    MAINTAINER_NAME,
    REPOSITORY_URL,
    TARGET_GAME,
    TARGET_SCREEN,
    load_build_info,
)
from ..version import APP_DISPLAY_VERSION, __version__
from . import theme
from .config_state import ConfigChangeSet, GuiConfigState, connect_config_aware, connect_many_config_aware
from .controllers.best_laps_controller import BestLapsController
from .controllers.developer_overview_controller import DeveloperOverviewController
from .controllers.db_doctor_controller import DbDoctorController
from .controllers.image_controller import ImageController
from .controllers.image_detail_controller import ImageDetailController
from .controllers.image_debug_controller import ImageDebugController
from .controllers.performance_controller import PerformanceController
from .controllers.process_controller import ProcessController
from .controllers.rebuild_controller import RebuildController
from .controllers.review_controller import ReviewController
from .controllers.settings_controller import SettingsController
from .views.best_laps_view import BestLapsView
from .views.developer_overview_view import DeveloperOverviewView
from .views.db_doctor_view import DbDoctorView
from .views.diagnostics_view import DiagnosticsView
from .views.image_browser_view import ImageBrowserView
from .views.image_detail_view import ImageDetailDialog
from .views.logs_view import LogsView
from .views.image_debug_view import ImageDebugView
from .views.records_view import RecordsView
from .views.process_view import ProcessView
from .views.review_queue_view import ReviewQueueView
from .views.settings_view import SettingsView


T = TypeVar("T")


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    description: str


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("images", "Images", "Browsing, multi-selection, and safe image asset management."),
    NavItem("process", "Process", "Input, database, options, and pipeline progress."),
    NavItem("review", "Review", "Case queue with large image preview and decision actions."),
    NavItem("best_laps", "Best Laps", "Relational frontier equivalent to the PDF/CSV output."),
    NavItem("records", "Records", "Comparable records, coverage, cars, and improvement targets."),
    NavItem("diagnostics", "Diagnostics", "Image debug, DB Doctor, and logs."),
    NavItem("settings", "Settings", "Paths, backend, model, prompt, and validation."),
)

_EVENT_REFRESH_SECTIONS = ("review", "images", "diagnostics", "records", "best_laps")


class MainWindow(QMainWindow):
    def __init__(self, *, cfg: Any, config_path: str, debug: bool, database_path: str, schema_state: str) -> None:
        super().__init__()
        self.setWindowTitle(APP_DISPLAY_VERSION)
        self.resize(1280, 820)

        self._config_state = GuiConfigState(cfg=cfg, config_path=config_path, parent=self)
        self._cfg = self._config_state.current
        self._config_path = config_path
        self._debug = debug
        self._buttons: dict[str, QPushButton] = {}
        self._stack = QStackedWidget()
        self._section_title = QLabel()
        self._section_title.setObjectName("sectionTitle")
        self._section_description = QLabel()
        self._section_description.setObjectName("mutedLabel")
        self._database_path = database_path
        self._schema_state = schema_state
        self._active_section = ""

        self._process_controller = ProcessController(config_state=self._config_state, debug=debug, parent=self)
        self._rebuild_controller = RebuildController(config_state=self._config_state, debug=debug, parent=self)
        self._review_controller = ReviewController(cfg=self._cfg, parent=self)
        self._image_controller = ImageController(cfg=self._cfg, parent=self)
        self._developer_overview_controller = DeveloperOverviewController(cfg=self._cfg, parent=self)
        self._db_doctor_controller = DbDoctorController(cfg=self._cfg, parent=self)
        self._image_debug_controller = ImageDebugController(cfg=self._cfg, parent=self)
        self._performance_controller = PerformanceController(cfg=self._cfg, parent=self)
        self._best_laps_controller = BestLapsController(cfg=self._cfg, parent=self)
        self._settings_controller = SettingsController(
            config_state=self._config_state,
            debug=debug,
            parent=self,
        )
        self._image_detail_controller = ImageDetailController(cfg=self._cfg, parent=self)
        self._controllers: list[Any] = [
            self._process_controller,
            self._rebuild_controller,
            self._review_controller,
            self._image_controller,
            self._developer_overview_controller,
            self._db_doctor_controller,
            self._image_debug_controller,
            self._performance_controller,
            self._best_laps_controller,
            self._settings_controller,
            self._image_detail_controller,
        ]
        connect_many_config_aware(self._config_state, self._controllers)
        connect_config_aware(self._config_state, self, initialize=False)

        self._refresh_pending: dict[str, bool] = {item.key: False for item in NAV_ITEMS}
        self._loaded_sections: set[str] = set()
        self._loaded_diagnostics_tabs: set[str] = set()
        self._process_view: ProcessView | None = None
        self._review_view: ReviewQueueView | None = None
        self._image_view: ImageBrowserView | None = None
        self._developer_overview_view: DeveloperOverviewView | None = None
        self._db_doctor_view: DbDoctorView | None = None
        self._image_debug_view: ImageDebugView | None = None
        self._logs_view: LogsView | None = None
        self._diagnostics_view: DiagnosticsView | None = None
        self._records_view: RecordsView | None = None
        self._best_laps_view: BestLapsView | None = None
        self._settings_view: SettingsView | None = None
        self._image_detail_dialog: ImageDetailDialog | None = None
        self._image_detail_navigation_ids: list[str] = []
        self._image_detail_current_id: str | None = None

        self.setCentralWidget(self._build_root())
        self.setStatusBar(self._build_statusbar())
        self.select_section("images")

    def on_config_changed(self, cfg: Any, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        self._mark_sections_stale("review", "images", "diagnostics", "records", "best_laps")
        self._loaded_diagnostics_tabs.discard("debug")
        self._show_status_message("Configuration applied to open GUI components.")

    def _register_config_aware(self, component: T) -> T:
        connect_config_aware(self._config_state, component)
        return component

    def _build_root(self) -> QWidget:
        root = QWidget()
        root.setObjectName("centralRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_main_area(), 1)
        return root

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(theme.SIDEBAR_WIDTH)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(8)
        title = QLabel(APP_SHORT_NAME)
        title.setObjectName("appTitle")
        layout.addWidget(title)
        version = QLabel(f"v{__version__}")
        version.setObjectName("appSubtitle")
        layout.addWidget(version)
        layout.addSpacing(14)
        for item in NAV_ITEMS:
            if item.key == "diagnostics":
                layout.addStretch(1)
            button = QPushButton(item.label)
            button.setObjectName("navButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(_callback_for(self.select_section, item.key))
            self._buttons[item.key] = button
            layout.addWidget(button)
        layout.addSpacing(8)
        about_button = QPushButton("About")
        about_button.setObjectName("navButton")
        about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        about_button.clicked.connect(self._show_about_dialog)
        layout.addWidget(about_button)
        return sidebar


    def _about_diagnostics_text(self) -> str:
        build_info = load_build_info()
        build_commit = str(build_info.get("commit") or "source")
        built_at = str(build_info.get("built_at_utc") or "source")
        build_platform = str(build_info.get("platform") or "source")
        return "\n".join(
            [
                f"App: {APP_NAME}",
                f"Version: {APP_RELEASE}",
                "Channel: beta",
                f"Target game: {TARGET_GAME}",
                f"Target screen: {TARGET_SCREEN}",
                f"Build info file: {BUILD_INFO_FILENAME}",
                f"Build commit: {build_commit}",
                f"Built at UTC: {built_at}",
                f"Bundle platform: {build_platform}",
                f"Database schema: {self._schema_state}",
                f"Database file: {self._database_path}",
                f"Repository: {REPOSITORY_URL}",
                f"Issues: {ISSUES_URL}",
            ]
        )

    def _copy_about_diagnostics(self) -> None:
        QApplication.clipboard().setText(self._about_diagnostics_text())
        self._show_status_message("Application diagnostics copied to clipboard.")

    def _open_repository(self) -> None:
        QDesktopServices.openUrl(QUrl(REPOSITORY_URL))

    def _show_about_dialog(self) -> None:
        message = QMessageBox(self)
        message.setWindowTitle(f"About {APP_NAME}")
        message.setTextFormat(Qt.TextFormat.RichText)
        message.setText(
            f"<b>{APP_NAME}</b><br>"
            f"Version: {APP_RELEASE}<br>"
            f"Target game: {TARGET_GAME}<br>"
            f"Target screen: {TARGET_SCREEN}<br><br>"
            f"Repository: {REPOSITORY_URL}<br>"
            f"Issues: {ISSUES_URL}<br>"
            f"License: {LICENSE_NAME}<br>"
            f"Maintainer: {MAINTAINER_NAME}<br><br>"
            f"{LEGAL_NOTICE}"
        )
        message.setDetailedText(self._about_diagnostics_text())
        copy_button = message.addButton("Copy Diagnostics", QMessageBox.ButtonRole.ActionRole)
        repository_button = message.addButton("Open Repository", QMessageBox.ButtonRole.ActionRole)
        message.addButton(QMessageBox.StandardButton.Ok)
        message.exec()
        clicked = message.clickedButton()
        if clicked is copy_button:
            self._copy_about_diagnostics()
        elif clicked is repository_button:
            self._open_repository()

    def _build_main_area(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_command_bar())
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 22, 24, 22)
        content_layout.setSpacing(18)
        content_layout.addWidget(self._stack, 1)
        for _item in NAV_ITEMS:
            self._stack.addWidget(QWidget())
        layout.addWidget(content, 1)
        return area

    def _build_command_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("commandBar")
        bar.setFixedHeight(theme.TOPBAR_HEIGHT)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self._section_title)
        titles.addWidget(self._section_description)
        layout.addLayout(titles, 1)
        return bar

    def _build_statusbar(self) -> QStatusBar:
        status = QStatusBar()
        status.showMessage(f"v{__version__} · Database: {self._database_path} · schema={self._schema_state}")
        return status

    def _page_for(self, item: NavItem) -> QWidget:
        builders = {
            "process": self._build_process_section,
            "review": self._build_review_section,
            "images": self._build_images_section,
            "diagnostics": self._build_diagnostics_section,
            "records": self._build_records_section,
            "best_laps": self._build_best_laps_section,
            "settings": self._build_settings_section,
        }
        return builders[item.key]()

    def _ensure_section_loaded(self, key: str, index: int) -> None:
        if key in self._loaded_sections:
            return
        item = NAV_ITEMS[index]
        page = self._page_for(item)
        placeholder = self._stack.widget(index)
        self._stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self._stack.insertWidget(index, page)
        self._loaded_sections.add(key)

    def _build_process_section(self) -> QWidget:
        self._process_view = self._register_config_aware(ProcessView(cfg=self._cfg))
        self._process_view.run_all_requested.connect(self._process_all_images)
        self._process_view.select_images_requested.connect(self._redirect_process_start_to_images)
        self._process_view.pause_requested.connect(self._process_controller.pause_run)
        self._process_view.resume_requested.connect(self._process_controller.resume_run)
        self._process_view.cancel_requested.connect(self._process_controller.cancel_run)
        self._process_controller.run_started.connect(lambda: self._process_view.set_running(True))
        self._process_controller.run_finished.connect(lambda _result: self._process_view.set_running(False))
        self._process_controller.pause_state_changed.connect(self._process_view.set_paused)
        self._process_controller.log_line_received.connect(self._process_view.append_log_line)
        self._process_controller.event_received.connect(self._process_view.append_event)
        self._process_controller.summary_changed.connect(self._process_view.update_summary)
        self._process_controller.event_received.connect(self._handle_runtime_event)
        self._process_controller.run_finished.connect(lambda _result: self._refresh_loaded_or_mark_stale(*_EVENT_REFRESH_SECTIONS))
        return self._process_view

    def _build_review_section(self) -> QWidget:
        self._review_view = ReviewQueueView()
        self._review_view.refresh_requested.connect(self._review_controller.refresh)
        self._review_view.filters_changed.connect(self._review_controller.apply_filters)
        self._review_view.case_selected.connect(self._review_controller.select_case)
        self._review_view.confirm_dirty_requested.connect(self._review_controller.confirm_dirty)
        self._review_view.mark_clean_requested.connect(self._review_controller.mark_clean)
        self._review_view.set_track_requested.connect(self._review_controller.set_track)
        self._review_view.set_weather_requested.connect(self._review_controller.set_weather)
        self._review_view.set_race_class_requested.connect(self._review_controller.set_race_class)
        self._review_view.set_car_requested.connect(self._review_controller.set_car)
        self._review_view.set_driver_name_requested.connect(self._review_controller.set_driver_name)
        self._review_view.ignore_requested.connect(self._review_controller.ignore_current)
        self._review_view.reopen_requested.connect(self._review_controller.reopen_current)
        self._review_view.next_requested.connect(self._review_controller.select_next)
        self._review_view.previous_requested.connect(self._review_controller.select_previous)
        self._review_view.open_image_detail_requested.connect(self._show_image_detail)
        self._review_controller.queue_changed.connect(self._review_view.set_cases)
        self._review_controller.filter_options_changed.connect(self._review_view.set_filter_options)
        self._review_controller.run_options_changed.connect(self._review_view.set_run_options)
        self._review_controller.selection_changed.connect(self._review_view.show_selection)
        self._review_controller.action_completed.connect(self._show_status_message)
        self._review_controller.action_completed.connect(lambda _message: self._refresh_loaded_or_mark_stale("images", "diagnostics", "records", "best_laps"))
        self._review_controller.action_failed.connect(self._show_status_message)
        self._review_controller.queue_empty.connect(lambda: self._show_status_message("Review queue is clear."))
        self._review_view.set_track_options(self._review_controller.track_options())
        self._review_view.refresh_current_filters()
        return self._review_view

    def _build_images_section(self) -> QWidget:
        self._image_view = ImageBrowserView()
        self._image_view.refresh_requested.connect(self._image_controller.refresh)
        self._image_view.scan_requested.connect(self._image_controller.scan_input_folder)
        self._image_view.process_selected_requested.connect(self._process_selected_images)
        self._image_view.selection_changed.connect(self._image_controller.select_images)
        self._image_view.rename_requested.connect(self._rename_images_with_confirmation)
        self._image_view.export_requested.connect(self._image_controller.export_images)
        self._image_view.delete_requested.connect(self._image_controller.delete_images)
        self._image_view.rescan_selected_requested.connect(self._image_controller.rescan_images)
        self._image_view.open_detail_requested.connect(self._show_image_detail_from_inventory)
        self._image_controller.images_changed.connect(self._image_view.set_images)
        self._image_controller.filter_options_changed.connect(self._image_view.set_filter_options)
        self._image_controller.selection_detail_changed.connect(self._image_view.show_selection)
        self._image_controller.action_completed.connect(self._show_status_message)
        self._image_controller.action_completed.connect(lambda _message: self._refresh_loaded_or_mark_stale("diagnostics", "records", "best_laps"))
        self._image_controller.action_failed.connect(self._show_status_message)
        self._image_controller.scan_running_changed.connect(self._image_view.set_syncing)
        self._image_controller.sync_input_folder()
        return self._image_view

    def _process_selected_images(self, image_ids: object) -> None:
        if image_ids is None:
            selected_ids = ()
        elif isinstance(image_ids, str):
            selected_ids = (image_ids,)
        else:
            try:
                selected_ids = tuple(str(image_id) for image_id in image_ids if str(image_id))
            except TypeError:
                selected_ids = (str(image_ids),)
        if not selected_ids:
            return
        self.select_section("process")
        dry_run = False
        force = False
        retry_errors = False
        debug = self._debug
        if self._process_view is not None:
            dry_run, force, retry_errors, view_debug = self._process_view.run_options()
            debug = bool(view_debug or self._debug)
            self._process_view.event_log.clear_log()
        started = self._process_controller.start_run(
            dry_run=dry_run,
            force=force,
            retry_errors=retry_errors,
            debug=debug,
            selected_image_file_ids=selected_ids,
        )
        if not started:
            self._show_status_message("Could not start selected image run.")

    def _process_all_images(self) -> None:
        if self._process_view is None:
            return
        dry_run, force, retry_errors, view_debug = self._process_view.run_options()
        debug = bool(view_debug or self._debug)
        self._process_view.event_log.clear_log()
        started = self._process_controller.start_run(
            dry_run=dry_run,
            force=force,
            retry_errors=retry_errors,
            debug=debug,
            selected_image_file_ids=None,
        )
        if not started:
            self._show_status_message("Could not start full image run.")

    def _redirect_process_start_to_images(self) -> None:
        self.select_section("images")
        self._show_status_message("Select image files in Images, then use Process selected.")

    def _build_diagnostics_section(self) -> QWidget:
        self._diagnostics_view = DiagnosticsView(
            tab_factories=[
                ("overview", "Overview", self._build_developer_overview_tab),
                ("debug", "Image Debug", self._build_image_debug_tab),
                ("db_doctor", "DB Doctor", self._build_db_doctor_tab),
                ("logs", "Logs", self._build_logs_tab),
            ]
        )
        self._diagnostics_view.tab_activated.connect(self._refresh_diagnostics_tab)
        return self._diagnostics_view

    def _refresh_diagnostics_tab(self, key: str) -> None:
        if key == "overview" and self._developer_overview_view is not None:
            if self._refresh_pending.get("diagnostics"):
                self._developer_overview_controller.refresh()
                self._refresh_pending["diagnostics"] = False
        elif key == "debug" and self._image_debug_view is not None:
            if key not in self._loaded_diagnostics_tabs or self._refresh_pending.get("diagnostics"):
                self._image_debug_controller.refresh()
                self._loaded_diagnostics_tabs.add(key)
                self._refresh_pending["diagnostics"] = False
        elif key == "db_doctor" and self._db_doctor_view is not None:
            if key not in self._loaded_diagnostics_tabs or self._refresh_pending.get("diagnostics"):
                self._db_doctor_controller.refresh()
                self._loaded_diagnostics_tabs.add(key)
                self._refresh_pending["diagnostics"] = False
        elif key == "logs" and self._logs_view is not None:
            self._logs_view.reload_files()

    def _build_developer_overview_tab(self) -> QWidget:
        self._developer_overview_view = DeveloperOverviewView()
        self._developer_overview_view.refresh_requested.connect(self._developer_overview_controller.refresh)
        self._developer_overview_controller.overview_changed.connect(self._developer_overview_view.show_snapshot)
        self._developer_overview_controller.action_failed.connect(self._developer_overview_view.show_error)
        self._developer_overview_controller.refresh()
        return self._developer_overview_view

    def _build_logs_tab(self) -> QWidget:
        self._logs_view = self._register_config_aware(LogsView(cfg=self._cfg))
        return self._logs_view

    def _build_db_doctor_tab(self) -> QWidget:
        self._db_doctor_view = DbDoctorView()
        self._db_doctor_view.refresh_button.clicked.connect(self._db_doctor_controller.refresh)
        self._db_doctor_controller.report_changed.connect(self._db_doctor_view.show_report)
        self._db_doctor_controller.action_failed.connect(self._db_doctor_view.show_error)
        return self._db_doctor_view

    def _build_image_debug_tab(self) -> QWidget:
        self._image_debug_view = ImageDebugView()
        self._image_debug_view.refresh_requested.connect(self._image_debug_controller.refresh)
        self._image_debug_view.case_selected.connect(self._image_debug_controller.select_image)
        self._image_debug_view.result_selected.connect(self._image_debug_controller.select_result)
        self._image_debug_view.open_image_detail_requested.connect(self._show_image_detail)
        self._image_debug_controller.cases_changed.connect(self._image_debug_view.set_cases)
        self._image_debug_controller.detail_loaded.connect(self._image_debug_view.show_detail)
        self._image_debug_controller.detail_failed.connect(self._image_debug_view.show_error)
        return self._image_debug_view

    def _build_records_section(self) -> QWidget:
        self._records_view = RecordsView()
        self._records_view.refresh_requested.connect(self._performance_controller.refresh)
        self._performance_controller.dashboard_changed.connect(self._records_view.show_dashboard)
        self._performance_controller.loading_changed.connect(self._records_view.set_loading)
        self._performance_controller.action_completed.connect(self._show_status_message)
        self._performance_controller.action_failed.connect(self._show_status_message)
        self._performance_controller.refresh()
        return self._records_view

    def _build_best_laps_section(self) -> QWidget:
        self._best_laps_view = self._register_config_aware(BestLapsView(cfg=self._cfg))
        self._best_laps_view.refresh_requested.connect(self._best_laps_controller.refresh)
        self._best_laps_view.filters_changed.connect(self._best_laps_controller.apply_filters)
        self._best_laps_view.import_external_records_requested.connect(self._best_laps_controller.import_external_records)
        self._best_laps_view.export_requested.connect(self._best_laps_controller.export_csv)
        self._best_laps_view.generate_pdf_requested.connect(self._best_laps_controller.generate_pdf)
        self._best_laps_view.open_pdf_requested.connect(self._rebuild_controller.open_last_pdf)
        self._rebuild_controller.action_failed.connect(self._show_status_message)
        self._best_laps_view.open_detail_requested.connect(self._show_image_detail)
        self._best_laps_controller.rows_changed.connect(self._best_laps_view.set_rows)
        self._best_laps_controller.filter_options_changed.connect(self._best_laps_view.set_filter_options)
        self._best_laps_controller.external_records_imported.connect(self._performance_controller.refresh)
        self._best_laps_controller.action_completed.connect(self._best_laps_view.show_message)
        self._best_laps_controller.action_failed.connect(self._best_laps_view.show_message)
        self._best_laps_controller.action_completed.connect(self._show_status_message)
        self._best_laps_controller.action_failed.connect(self._show_status_message)
        self._best_laps_controller.refresh()
        return self._best_laps_view

    def _build_settings_section(self) -> QWidget:
        self._settings_view = SettingsView()
        self._settings_view.refresh_requested.connect(self._settings_controller.refresh)
        self._settings_view.preview_requested.connect(self._settings_controller.preview_changes)
        self._settings_view.save_requested.connect(self._settings_controller.save_changes)
        self._settings_controller.settings_changed.connect(self._settings_view.show_settings)
        self._settings_controller.action_completed.connect(self._settings_view.show_message)
        self._settings_controller.action_failed.connect(self._settings_view.show_warning)
        self._settings_controller.refresh()
        return self._settings_view

    def select_section(self, key: str) -> None:
        index = next((i for i, item in enumerate(NAV_ITEMS) if item.key == key), 0)
        item = NAV_ITEMS[index]
        was_loaded = item.key in self._loaded_sections
        self._ensure_section_loaded(item.key, index)
        self._stack.setCurrentIndex(index)
        self._active_section = item.key
        self._section_title.setText(item.label)
        self._section_description.setText(item.description)
        if key == "review" and self._review_view is not None:
            self._review_view.refresh_current_filters()
        elif key == "images" and was_loaded and self._image_view is not None:
            self._image_controller.sync_input_folder()
        elif self._refresh_pending.get(key):
            self._refresh_section_now(key)
        self._refresh_pending[key] = False
        for button_key, button in self._buttons.items():
            button.setProperty("active", button_key == key)
            button.style().unpolish(button)
            button.style().polish(button)

    def _handle_runtime_event(self, event) -> None:
        for key in _EVENT_REFRESH_SECTIONS:
            if key == self._active_section and key in self._loaded_sections:
                self._dispatch_event_to_section(key, event)
            else:
                self._refresh_pending[key] = True

    def _dispatch_event_to_section(self, key: str, event) -> None:
        if key == "review":
            self._review_controller.handle_event(event)
        elif key == "images":
            self._image_controller.handle_event(event)
        elif key == "records":
            self._performance_controller.handle_event(event)
        elif key == "best_laps":
            self._best_laps_controller.handle_event(event)
        elif key == "diagnostics":
            self._refresh_pending[key] = True
            self._loaded_diagnostics_tabs.discard("debug")

    def _refresh_loaded_or_mark_stale(self, *keys: str) -> None:
        for key in keys:
            if key == self._active_section and key in self._loaded_sections:
                self._refresh_section_now(key)
            else:
                self._refresh_pending[key] = True

    def _refresh_section_now(self, key: str) -> None:
        if key == "review" and self._review_view is not None:
            self._review_view.refresh_current_filters()
        elif key == "images" and self._image_view is not None:
            self._image_controller.sync_input_folder()
        elif key == "diagnostics" and self._developer_overview_view is not None:
            self._developer_overview_controller.refresh()
        elif key == "records" and self._records_view is not None:
            self._performance_controller.refresh()
        elif key == "best_laps" and self._best_laps_view is not None:
            self._best_laps_controller.reload()
        elif key == "settings" and self._settings_view is not None:
            self._settings_controller.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        for controller in self._controllers:
            close = getattr(controller, "close", None)
            if callable(close):
                close()
        super().closeEvent(event)

    def _rename_images_with_confirmation(self, image_ids: list[str]) -> None:
        if self._image_view is None:
            return
        plan = self._image_controller.plan_rename(image_ids)
        if self._image_view.confirm_rename_plan(plan):
            self._image_controller.rename_images(image_ids)

    def _ensure_image_detail_dialog(self) -> ImageDetailDialog:
        if self._image_detail_dialog is None:
            dialog = ImageDetailDialog(self)
            dialog.open_debug_requested.connect(self._image_detail_controller.request_open_debug)
            dialog.previous_image_requested.connect(self._show_previous_image_detail)
            dialog.next_image_requested.connect(self._show_next_image_detail)
            self._image_detail_controller.detail_loaded.connect(dialog.show_detail)
            self._image_detail_controller.detail_failed.connect(dialog.show_error)
            self._image_detail_controller.open_debug_requested.connect(self._show_image_debug_result)
            self._image_detail_dialog = dialog
        return self._image_detail_dialog

    def _show_image_detail_from_inventory(self, image_file_id: str) -> None:
        navigation_ids = self._image_view.visible_image_ids() if self._image_view is not None else [image_file_id]
        self._show_image_detail(image_file_id, navigation_ids=navigation_ids)

    def _show_image_detail(self, image_file_id: str, *, navigation_ids: list[str] | None = None) -> None:
        if navigation_ids is not None:
            clean_ids = [str(candidate) for candidate in navigation_ids if str(candidate)]
            if image_file_id not in clean_ids:
                clean_ids.append(image_file_id)
            self._image_detail_navigation_ids = clean_ids
        elif image_file_id not in self._image_detail_navigation_ids:
            self._image_detail_navigation_ids = [image_file_id]
        self._image_detail_current_id = image_file_id

        dialog = self._ensure_image_detail_dialog()
        self._update_image_detail_navigation_state(dialog)
        self._image_detail_controller.load_image(image_file_id)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _show_previous_image_detail(self) -> None:
        self._show_adjacent_image_detail(-1)

    def _show_next_image_detail(self) -> None:
        self._show_adjacent_image_detail(1)

    def _show_adjacent_image_detail(self, step: int) -> None:
        image_file_id = self._adjacent_image_detail_id(step)
        if image_file_id is None:
            return
        self._show_image_detail(image_file_id)

    def _adjacent_image_detail_id(self, step: int) -> str | None:
        if self._image_detail_current_id is None:
            return None
        try:
            index = self._image_detail_navigation_ids.index(self._image_detail_current_id)
        except ValueError:
            return None
        next_index = index + step
        if 0 <= next_index < len(self._image_detail_navigation_ids):
            return self._image_detail_navigation_ids[next_index]
        return None

    def _update_image_detail_navigation_state(self, dialog: ImageDetailDialog) -> None:
        dialog.set_navigation_state(
            has_previous=self._adjacent_image_detail_id(-1) is not None,
            has_next=self._adjacent_image_detail_id(1) is not None,
        )

    def _show_image_debug_result(self, extraction_result_id: str) -> None:
        if self._image_detail_dialog is not None:
            self._image_detail_dialog.hide()
        self.select_section("diagnostics")
        if self._diagnostics_view is not None:
            self._diagnostics_view.select_debug()
        self._image_debug_controller.load_result(extraction_result_id)
        if self._image_debug_view is not None:
            self._image_debug_view.select_result(extraction_result_id)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _mark_sections_stale(self, *keys: str) -> None:
        for key in keys:
            self._refresh_pending[key] = True

    def _show_status_message(self, message: str) -> None:
        if self.statusBar() is not None:
            self.statusBar().showMessage(message, 5000)


def _callback_for(fn: Callable[[str], None], value: str):
    def _callback() -> None:
        fn(value)
    return _callback
