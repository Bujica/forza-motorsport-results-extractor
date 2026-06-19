from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def test_runtime_reference_loads_do_not_seed_from_text_files() -> None:
    runtime_files = (
        "forza/cli/run.py",
        "forza/cli/rebuild.py",
        "forza/gui/workers/run_worker.py",
        "forza/gui/workers/rebuild_worker.py",
    )
    forbidden = ("tracks_file=", "cars_file=", "seed_missing")

    for relpath in runtime_files:
        source = _source(relpath)
        assert "database.load_reference_data()" in source
        for token in forbidden:
            assert token not in source, f"{token!r} leaked into {relpath}"


def test_reference_data_service_has_no_implicit_text_file_seed() -> None:
    source = _source("forza/application/reference_data_service.py")

    assert "load_nonempty_lines" not in source
    assert "seed_missing" not in source
    assert "tracks_file" not in source
    assert "cars_file" not in source


def test_external_record_import_uses_sql_reference_tracks_only() -> None:
    source = _source("forza/application/external_record_service.py")
    gui_best_laps = _source("forza/gui/controllers/best_laps_controller.py")
    gui_performance = _source("forza/gui/controllers/performance_controller.py")

    assert "tracks_file: Path" not in source
    assert "self.tracks_file" not in source
    assert "_load_known_tracks" not in source
    assert "load_nonempty_lines" not in source
    assert "known_tracks=database.list_reference_tracks()" in source
    assert "ExternalRecordService(tracks_file" not in gui_best_laps
    assert "ExternalRecordService(tracks_file" not in gui_performance
    assert 'changes.affects("paths.tracks_file")' not in gui_performance

def test_review_track_options_use_sql_reference_tracks_only() -> None:
    review_source = _source("forza/gui/controllers/review_controller.py")
    read_source = _source("forza/application/gui_read_service.py")
    main_source = _source("forza/gui/main_window.py")
    best_laps_source = _source("forza/gui/controllers/best_laps_controller.py")

    assert "load_nonempty_lines" not in review_source
    assert "cfg.tracks_file" not in review_source
    assert 'changes.affects("paths.tracks_file")' not in review_source
    assert "self._reader.list_reference_tracks()" in review_source
    assert "def list_reference_tracks" in read_source
    assert "ReferenceRepository" in read_source
    assert 'changes.affects("paths.tracks_file")' not in main_source
    assert 'changes.affects("paths.tracks_file")' not in best_laps_source

def test_product_config_no_longer_exposes_reference_text_file_paths() -> None:
    config_source = _source("forza/config.py")
    config_service_source = _source("forza/application/config_service.py")
    settings_source = _source("forza/gui/controllers/settings_controller.py")
    config_state_source = _source("forza/gui/config_state.py")
    config_example = _source("forza_config.ini.example")
    install_source = _source("install.py")

    for source in (
        config_source,
        settings_source,
        config_state_source,
        config_example,
        install_source,
    ):
        assert "tracks_file" not in source
        assert "cars_file" not in source

    assert '"tracks_file": str(cfg.tracks_file)' not in config_service_source
    assert '"cars_file": str(cfg.cars_file)' not in config_service_source
    assert '"tracks_file",' not in config_service_source
    assert '"cars_file",' not in config_service_source
    # Legacy cleanup remains behavioral, not a product-facing config surface.
    # tests/test_config_file_service.py verifies old INI keys are removed on save.
    assert '"tracks_file"' not in config_service_source
    assert '"cars_file"' not in config_service_source
    assert 'parser["paths"].pop(obsolete_key, None)' in config_service_source

def test_seed_text_reference_loader_is_not_runtime_reference_api() -> None:
    domain_init = _source("forza/domain/__init__.py")
    normalizer_source = _source("forza/domain/normalizer.py")
    runtime_files = (
        "forza/cli/run.py",
        "forza/cli/rebuild.py",
        "forza/gui/workers/run_worker.py",
        "forza/gui/workers/rebuild_worker.py",
        "forza/application/database_service.py",
        "forza/application/reference_data_service.py",
    )

    assert "def load_reference_seed_text_data(" in normalizer_source
    assert "def load_reference_data(" not in normalizer_source
    assert "load_reference_seed_text_data" in domain_init
    assert '"load_reference_data"' not in domain_init

    for relpath in runtime_files:
        source = _source(relpath)
        assert "load_reference_seed_text_data" not in source, relpath
        assert "from forza.domain.normalizer import load_reference_data" not in source, relpath

