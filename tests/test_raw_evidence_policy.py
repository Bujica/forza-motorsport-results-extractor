from pathlib import Path


GUI_READ_SERVICE = Path("forza/application/gui_read_service.py")
GUI_READ_ARTIFACTS = Path("forza/application/gui_read/artifact_reads.py")
IMAGE_DEBUG_CONTROLLER = Path("forza/gui/controllers/image_debug_controller.py")
CONFIG = Path("forza/config.py")
EXAMPLE_CONFIG = Path("forza_config.ini.example")


def test_gui_read_service_has_no_default_raw_response_roots() -> None:
    source = "\n".join(
        (
            GUI_READ_SERVICE.read_text(encoding="utf-8"),
            GUI_READ_ARTIFACTS.read_text(encoding="utf-8"),
        )
    )
    legacy_raw_root = "debug/" + "raw_" + "responses"
    legacy_failed_root = "debug/" + "failed_attempts"

    assert f'Path("{legacy_raw_root}")' not in source
    assert f'Path("{legacy_failed_root}")' not in source
    assert "if raw_response_roots is None:" in source
    assert "return ()" in source


def test_image_debug_controller_does_not_pass_raw_artifact_roots_for_normal_reads() -> None:
    source = IMAGE_DEBUG_CONTROLLER.read_text(encoding="utf-8")

    assert "raw_response_roots" not in source
    assert ("raw_" + "artifacts_dir") not in source
    assert "return GuiReadService(cfg.database_file)" in source


def test_artifact_text_read_is_explicit_and_registered() -> None:
    source = "\n".join(
        (
            GUI_READ_SERVICE.read_text(encoding="utf-8"),
            GUI_READ_ARTIFACTS.read_text(encoding="utf-8"),
        )
    )

    assert "def read_registered_artifact_text" in source
    assert "allowed_roots: Sequence[Path]" in source
    assert "_canonical_artifact(session, extraction_result_id" in source
    assert "return _read_text_file(artifact.file_path if artifact is not None else None, roots)" in source


def test_config_has_no_legacy_debug_raw_response_default() -> None:
    source = "\n".join((
        CONFIG.read_text(encoding="utf-8"),
        EXAMPLE_CONFIG.read_text(encoding="utf-8"),
    ))

    assert ("debug/" + "raw_" + "responses") not in source
    assert ("output/model_artifacts/" + "raw_" + "responses") not in source
    assert ("raw_" + "artifacts_dir") not in source
