from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _name(*parts: str) -> str:
    return "".join(parts)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _combined_sources(*roots: str) -> str:
    chunks: list[str] = []
    this_file = Path(__file__).resolve()
    for root_name in roots:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path == this_file:
                continue
            if path.is_file() and path.suffix in {".py", ".sql", ".md", ".txt", ".json"}:
                chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_removed_development_gui_files_do_not_return() -> None:
    removed_paths = (
        ("forza", "gui", "controllers", _name("cal", "ibration_controller.py")),
        ("forza", "gui", "controllers", _name("cal", "ibration_run_controller.py")),
        ("forza", "gui", "controllers", _name("prompt", "_bench_controller.py")),
        ("forza", "gui", "controllers", _name("config", "_bench_controller.py")),
        ("forza", "gui", "controllers", _name("sample", "_builder_controller.py")),
        ("forza", "gui", "controllers", _name("ground", "_truth_manager_controller.py")),
        ("forza", "gui", "views", _name("cal", "ibration_view.py")),
        ("forza", "gui", "views", _name("cal", "ibration_run_view.py")),
        ("forza", "gui", "views", _name("prompt", "_bench_view.py")),
        ("forza", "gui", "views", _name("config", "_bench_view.py")),
        ("forza", "gui", "views", _name("sample", "_builder_view.py")),
        ("forza", "gui", "views", _name("ground", "_truth_manager_view.py")),
        ("forza", "gui", "views", _name("lab", "_workbench_view.py")),
        ("forza", "gui", "views", "artifacts_view.py"),
        ("forza", "gui", "workers", _name("cal", "ibration_worker.py")),
        ("forza", "gui", "workers", _name("prompt", "_bench_worker.py")),
        ("forza", "gui", "workers", _name("config", "_bench_worker.py")),
        ("forza", "gui", "workers", _name("sample", "_builder_worker.py")),
    )

    for parts in removed_paths:
        path = ROOT.joinpath(*parts)
        assert not path.exists(), path.relative_to(ROOT)


def test_removed_development_package_and_retention_files_do_not_return() -> None:
    removed_paths = (
        ("forza", "application", _name("retention", "_service.py")),
        ("forza", "application", _name("review", "_identity_repair.py")),
        ("forza", "application", _name("db", "_maintenance_service.py")),
        ("forza", "application", "db_doctor", _name("ground", "_truth_checks.py")),
        ("forza", "application", "db_doctor", _name("retention", "_lab_checks.py")),
        ("forza", "db", _name("artifact", "_retention_contract.py")),
        ("forza", "db", "entities", _name("ground", "_truth.py")),
        ("forza", "db", "entities", _name("lab", ".py")),
        ("forza", "db", "migrations", "versions", _name("0001_artifact", "_retention_contract.sql")),
        ("forza", _name("lab"), "__init__.py"),
        ("forza", _name("lab"), _name("workbench", "_service.py")),
        ("forza", _name("lab"), _name("dataset", "_service.py")),
        ("forza", _name("lab"), _name("ground", "_truth.py")),
        ("forza", _name("lab"), _name("prompt", "_bench.py")),
        ("tests", _name("test_retention", "_service.py")),
        ("tests", _name("test_cli_maintenance", "_retention.py")),
        ("tests", _name("test_ground", "_truth_expected_payload_policy.py")),
        ("tests", _name("test_db_doctor_ground", "_truth_checks_static.py")),
    )

    for parts in removed_paths:
        path = ROOT.joinpath(*parts)
        assert not path.exists(), path.relative_to(ROOT)


def test_removed_command_and_tab_wiring_does_not_return() -> None:
    parser = _read("forza/cli/parser.py")
    maintenance = _read("forza/cli/maintenance.py")
    main_window = _read("forza/gui/main_window.py")
    app_init = _read("forza/application/__init__.py")

    absent_by_source = {
        parser: (
            _name("maintenance_sub.add_parser(\"", "ret", "ention", "\""),
            _name("cmd_", "ret", "ention"),
            "DB Maintenance",
        ),
        maintenance: (
            _name("def cmd_", "ret", "ention"),
            _name("_ret", "ention_preview_payload"),
            _name("_ret", "ention_apply_payload"),
        ),
        main_window: (
            _name("Lab", "Workbench", "View"),
            _name("Config", "Bench", "Controller"),
            _name("Config", "Bench", "View"),
            _name("Config", "Bench", "Worker"),
            _name("_build_lab", "_workbench_tab"),
            _name("_build_config", "_bench_tab"),
            "output_dir_ready",
            "set_output_dir",
            "open_output",
        ),
        app_init: (
            _name("Retention", "Service"),
            _name("Retention", "Candidate"),
        ),
    }

    for source, tokens in absent_by_source.items():
        for token in tokens:
            assert token not in source, token


def test_removed_schema_metadata_stays_outside_product_sources() -> None:
    source = _combined_sources("forza", "tests")
    forbidden = (
        _name("retention", "_class"),
        "pinned_at",
        "prunable_after",
        "pruned_at",
        "prune_reason",
        _name("summary", "_json"),
        _name("retention", "_prunable_due"),
        _name("retention", "_metadata_invalid"),
        _name("ck_model_artifacts_", "retention", "_class_vocab"),
        _name("ck_export_artifacts_", "retention", "_class_vocab"),
        _name("ground", "_truth"),
        _name("Ground", "Truth"),
        _name("ck_ground", "_truth_datasets_status_vocab"),
        _name("ck_ground", "_truth_cases_status_vocab"),
        _name("trg_ground", "_truth_cases_final_expected_nonempty"),
    )

    for token in forbidden:
        assert token not in source, token


def test_product_artifact_integrity_checks_remain() -> None:
    checks = _read("forza/application/db_doctor/artifact_checks.py")
    result_entity = _read("forza/db/entities/result.py")
    export_entity = _read("forza/db/entities/export.py")
    schema = _read("forza/db/migrations/versions/0001_db_vnext_schema.sql")

    for token in (
        "model_artifacts_invalid",
        "export_artifacts_invalid",
        "sha256",
        "size_bytes",
        "ck_model_artifacts_size_nonnegative",
        "ck_export_artifacts_size_nonnegative",
    ):
        assert token in checks or token in result_entity or token in export_entity or token in schema
