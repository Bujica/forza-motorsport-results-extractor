from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"
APPLICATION_ROOT = ROOT / "forza" / "application"


def test_image_controller_uses_public_services_and_no_session() -> None:
    source = (GUI_ROOT / "controllers" / "image_controller.py").read_text(encoding="utf-8")

    assert "GuiReadService" in source
    assert "GuiWriteService" in source
    assert "ImageRenameService" in source
    assert "def sync_input_folder" in source
    assert "ImageInventoryWorker" in source
    assert "def _start_input_folder_scan" in source
    assert "scan_running_changed" in source
    assert "def _scan_input_folder" not in source
    assert "DatabaseService" not in source
    assert "ImageInventoryService" not in source
    assert "plan_rename" in source
    assert "rename_file" in source
    assert "export_images" in source
    assert "delete_images" in source
    assert "delete_image_file" in source
    assert "rescan_images" in source
    assert "def set_hidden(" not in source
    assert "def exclude_from_best_laps(" not in source
    assert "def reset_best_lap_status(" not in source


def test_image_view_has_filters_multiselect_preview_and_batch_actions() -> None:
    source = (GUI_ROOT / "views" / "image_browser_view.py").read_text(encoding="utf-8")

    for token in (
        "ExtendedSelection",
        "ImagePreview",
        "BatchActionBar",
        "scan_requested",
        "process_selected_requested",
        "best_filter",
        "file_filter",
        "Duplicate",
        "duplicate groups",
        "Inventory",
        "inventory_filter",
        "track_filter",
        "run_filter",
        "Scan folder",
        "Delete Images",
        "Image inventory",
        "Image details",
    ):
        assert token in source

    assert "QFileDialog.getExistingDirectory" in source
    model_source = (GUI_ROOT / "models" / "image_table_model.py").read_text(encoding="utf-8")
    assert "_race_date_label(image)" in model_source
    assert "_race_date_sort_value(image)" in model_source
    assert "file modification date" in model_source
    assert "confirm_rename_plan" in source
    assert "plans[:12]" not in source
    assert "if item.would_change" in source
    assert "combo.currentTextChanged.connect(lambda _text: self._emit_refresh())" in source
    assert "_combo_value(self.run_filter)" in source
    assert "duplicate_of_image_file_id" in source
    for review_reason in ("dirty_lap", "weather", "race_class", "gamertag", "driver_name"):
        assert review_reason not in source
    assert "disposable" not in source
    assert "Disposable files" not in source
    assert "lab_sample_candidate" not in source
    assert ("difficult" + "_image") not in source


def test_production_code_does_not_reintroduce_removed_lab_flag_values() -> None:
    production_paths = (
        ROOT / "forza" / "schemas" / "enums.py",
        ROOT / "forza" / "db" / "repositories" / "image_flags.py",
        ROOT / "forza" / "application" / "gui_read_service.py",
        ROOT / "forza" / "application" / "gui_write_service.py",
        ROOT / "forza" / "gui" / "views" / "image_browser_view.py",
        ROOT / "forza" / "gui" / "widgets" / "batch_action_bar.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in production_paths)

    for quote in ('"', "'"):
        assert f"{quote}lab_sample_candidate{quote}" not in combined
        assert f"{quote}{'difficult' + '_image'}{quote}" not in combined
    assert "Calibration candidate" not in combined
    assert "Difficult image" not in combined
    enum_source = production_paths[0].read_text(encoding="utf-8")
    assert "LAB_SELECTION_FLAGS" not in enum_source
    assert "CALIBRATION_FLAGS" not in enum_source
    assert "LAB_SELECTION_FLAGS" not in production_paths[1].read_text(encoding="utf-8")


def test_gui_write_service_does_not_expose_raw_image_flag_status_surface() -> None:
    source = (APPLICATION_ROOT / "gui_write_service.py").read_text(encoding="utf-8")

    assert "ImageFlagStatus.OPEN" not in source
    assert "def add_image_flag(" not in source
    assert "def resolve_image_flag(" not in source
    assert "def ignore_image_flag(" not in source
    assert "def reopen_image_flag(" not in source
    assert "def _set_image_flag_status(" not in source
    assert 'return self._set_image_flag_status(flag_id, "active")' not in source
    assert 'return self._set_image_flag_status(flag_id, "open")' not in source
    assert 'entity.status = "open" if entity.status == "active" else entity.status' not in source
    assert 'db_status = "active" if status == "open" else status' not in source
    assert "_sync_review_flags(" in source
    assert "_ensure_active_duplicate_flag(" in source

def test_gui_write_service_does_not_expose_manual_best_lap_exclusion() -> None:
    source = (APPLICATION_ROOT / "gui_write_service.py").read_text(encoding="utf-8")

    assert "def exclude_from_best_laps(" not in source
    assert "def reset_best_lap_status(" not in source
    assert "def set_best_lap_status(" not in source
    assert "excluded" not in source


def test_gui_read_service_does_not_expose_raw_image_flag_surface() -> None:
    source = "\n".join(
        (
            (APPLICATION_ROOT / "gui_read_service.py").read_text(encoding="utf-8"),
            (APPLICATION_ROOT / "gui_read" / "image_reads.py").read_text(encoding="utf-8"),
            (APPLICATION_ROOT / "gui_read" / "dashboard_reads.py").read_text(encoding="utf-8"),
        )
    )

    assert "def list_image_flags(" not in source
    assert "return self._image_reads.list_image_flags(" not in source
    assert "GuiImageFlag" not in source
    assert 'status: str | None = "active"' not in source
    assert 'ImageFlagEntity.status.in_(["active", "open"])' not in source
    assert 'return "open" if status == "active" else status' not in source
    assert 'return "active" if status == "open" else status' not in source
    assert 'if status == "open":\n        return ["active", "open"]' not in source

def test_production_code_does_not_query_legacy_open_image_flag_status() -> None:
    production_paths = (
        ROOT / "forza" / "application" / "db_doctor_service.py",
        ROOT / "forza" / "application" / "gui_read_service.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in production_paths)
    read_source = production_paths[1].read_text(encoding="utf-8")

    assert 'ImageFlagEntity.status.in_(["active", "open"])' not in combined
    assert "_flag_status_ui" not in read_source
    assert "_flag_status_db" not in read_source


def test_image_management_deletes_selected_asset_and_database_records() -> None:
    controller = (GUI_ROOT / "controllers" / "image_controller.py").read_text(encoding="utf-8")
    view = (GUI_ROOT / "views" / "image_browser_view.py").read_text(encoding="utf-8")
    service = (APPLICATION_ROOT / "gui_write_service.py").read_text(encoding="utf-8")

    combined = controller + view
    assert "delete_images" in controller
    assert "delete_image_file" in service
    assert "path.unlink()" in controller
    assert "database records" in controller
    assert "_resolved_image_path" in controller
    assert "delete_requested" in view
    assert "permanently delete the selected files and their database records" in view
    assert "remove(" not in combined
    assert "rmtree" not in combined


def test_batch_action_bar_contains_required_stage_four_actions() -> None:
    source = (GUI_ROOT / "widgets" / "batch_action_bar.py").read_text(encoding="utf-8")

    for token in (
        "process_requested",
        "Process selected",
        "Rename",
        "Export",
        "Delete",
        "Rescan selected",
    ):
        assert token in source

    assert "flag_toggled" not in source
    assert "Calibration candidate" not in source
    assert "Difficult image" not in source
    assert "lab_sample_candidate" not in source
    assert ("difficult" + "_image") not in source
    assert "QMenu" not in source


def test_main_window_wires_image_management_page() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "ImageController" in source
    assert "ImageBrowserView" in source
    nav_block = source.split("NAV_ITEMS", 1)[1].split(")", 1)[0]
    assert 'NavItem("images", "Images",' in nav_block
    assert "\"images\": self._build_images_section" in source
    assert "self.select_section(\"images\")" in source
    assert "self._image_view.scan_requested.connect(self._image_controller.scan_input_folder)" in source
    assert "self._image_view.process_selected_requested.connect(self._process_selected_images)" in source
    assert "self._image_view.rescan_selected_requested.connect(self._image_controller.rescan_images)" in source
    assert "self._process_view.run_all_requested.connect(self._process_all_images)" in source
    assert "self._process_view.select_images_requested.connect(self._redirect_process_start_to_images)" in source
    assert "self._process_view.run_options()" in source
    assert "self._image_controller.sync_input_folder()" in source
    assert "elif key == \"images\" and was_loaded" in source
    assert "selected_image_file_ids=selected_ids" in source
    assert "selected_image_file_ids=None" in source
    assert "_rename_images_with_confirmation" in source
    assert "self._image_controller," in source
    assert "self._process_controller.event_received.connect(self._handle_runtime_event)" in source
    assert "self._image_controller.handle_event(event)" in source
    assert "flag_toggled_requested" not in source


def test_image_table_model_exposes_race_date_column() -> None:
    source = (GUI_ROOT / "models" / "image_table_model.py").read_text(encoding="utf-8")

    for token in (
        '"Race Date"',
        "getattr(image, \"race_date\", None)",
        "getattr(image, \"race_datetime\", None)",
        "_race_date_label",
        "_race_date_sort_value",
        "Race date derived from race metadata, not the file modification date.",
    ):
        assert token in source

    assert "file_modified_at" not in source
