from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from forza.domain.normalizer import load_reference_seed_text_data
from forza.db.migrate import upgrade_database


STATIC_SOURCE_TESTS = {
    "test_gui_architecture_boundaries.py",
    "test_raw_evidence_policy.py",
}

DB_FILE_NAMES = {
    "test_database_service_repository_flows.py",
    "test_db_doctor_artifact_service.py",
    "test_db_doctor_core_service.py",
    "test_db_doctor_image_lap_service.py",
    "test_db_doctor_review_service.py",
    "test_db_doctor_run_input_service.py",
    "test_db_doctor_schema_service.py",
    "test_db_external_records_repository.py",
    "test_db_lap_repository.py",
    "test_db_repositories_core.py",
    "test_db_review_repository.py",
    "test_db_image_file_repository.py",
    "test_db_vnext_runtime_contracts.py",
    "test_gui_read_and_rename.py",
    "test_gui_read_extended.py",
    "test_gui_write_dirty_decisions.py",
    "test_gui_write_field_decisions.py",
    "test_gui_write_flags_cases.py",
    "test_gui_write_image_status.py",
    "test_gui_write_standalone.py",
    "test_raw_response_and_review_linkage.py",
    "test_schemas_services.py",
}

DB_SOURCE_TOKENS = (
    "create_sqlite_engine",
    "upgrade_database(",
    "Session(",
    "sqlite3",
)

INTEGRATION_FILE_NAMES = {
    "test_rebuild_integration.py",
}

SLOW_FILE_NAMES = {
    "test_database_service_repository_flows.py",
    "test_db_doctor_artifact_service.py",
    "test_db_repositories_core.py",
    "test_db_vnext_runtime_contracts.py",
    "test_rebuild_integration.py",
    "test_schemas_services.py",
}

GUI_CONTRACT_FILES = {
    "test_gui_database_state.py",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Apply conservative test-profile markers without editing every test file.

    The marker policy is documented in docs/developer/testing-policy.md. This
    hook intentionally classifies by file and obvious DB tokens only; individual
    tests can still add explicit pytest marks later when a file needs finer
    granularity.
    """

    source_cache: dict[Path, str] = {}

    for item in items:
        path = _item_path(item)
        name = path.name
        source = _source_for(path, source_cache)

        is_static = name.endswith("_static.py") or name in STATIC_SOURCE_TESTS
        is_integration = name in INTEGRATION_FILE_NAMES or name.endswith("_integration.py")
        is_db = name in DB_FILE_NAMES or any(token in source for token in DB_SOURCE_TOKENS)
        is_gui_contract = (
            (is_static and "gui" in name)
            or "tests/gui/" in path.as_posix().replace("\\", "/")
            or name in GUI_CONTRACT_FILES
        )
        is_slow = name in SLOW_FILE_NAMES

        if is_static:
            item.add_marker("static")
        if is_gui_contract:
            item.add_marker("gui_contract")
        if is_db:
            item.add_marker("db")
        if is_integration:
            item.add_marker("integration")
        if is_slow:
            item.add_marker("slow")
        if not (is_static or is_db or is_integration):
            item.add_marker("unit")


def _item_path(item: pytest.Item) -> Path:
    path = getattr(item, "path", None)
    if path is not None:
        return Path(path)
    return Path(str(item.fspath))


def _source_for(path: Path, cache: dict[Path, str]) -> str:
    if path not in cache:
        try:
            cache[path] = path.read_text(encoding="utf-8")
        except OSError:
            cache[path] = ""
    return cache[path]


@pytest.fixture(scope="session")
def refs():
    """Load reference data if files exist, otherwise use empty lists."""
    tracks_file = Path("tracks.txt")
    cars_file = Path("cars.txt")
    return load_reference_seed_text_data(tracks_file, cars_file)

@pytest.fixture(scope="session")
def migrated_db_template_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create one migrated SQLite template for DB-heavy tests.

    Tests must copy this file into their own tmp_path before mutating it. The
    template itself is session-scoped and must remain read-only after creation.
    """

    db_path = tmp_path_factory.mktemp("db_templates") / "forza_migrated.sqlite3"
    upgrade_database(db_path)
    return db_path


@pytest.fixture
def migrated_db_path(tmp_path: Path, migrated_db_template_path: Path) -> Path:
    """Return an isolated migrated SQLite database for one test."""

    db_path = tmp_path / "forza.sqlite3"
    shutil.copy2(migrated_db_template_path, db_path)
    return db_path

