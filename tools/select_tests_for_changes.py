from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

SMOKE_TESTS = (
    "tests/test_config.py",
    "tests/test_schemas_services.py",
    "tests/test_pipeline.py",
    "tests/test_db_doctor_core_service.py",
)

RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("forza/config.py", "forza/application/config_service.py", "forza/gui/config_state.py"), (
        "tests/test_config.py",
        "tests/test_config_file_service.py",
        "tests/gui/test_config_state_diff.py",
        "tests/test_process_controller_config_reload.py",
        "tests/test_schemas_services.py",
    )),
    (("forza/db/models.py", "forza/db/repositories/", "forza/db/migrations/", "forza/db/review_identity.py"), (
        "tests/test_models.py",
        "tests/test_models_full.py",
        "tests/test_db_repositories_core.py",
        "tests/test_db_lap_repository.py",
        "tests/test_db_review_repository.py",
        "tests/test_db_source_image_repository.py",
        "tests/test_db_external_records_repository.py",
        "tests/test_db_entities_facade_static.py",
        "tests/test_db_vnext_runtime_contracts.py",
        "tests/test_db_doctor_core_service.py",
        "tests/test_db_doctor_schema_service.py",
        "tests/test_orm_aliases_static.py",
        "tests/test_vocabulary_check_constraints_static.py",
        "tests/test_review_case_number_column_static.py",
        "tests/test_schemas_services.py",
    )),
    (("forza/application/db_doctor_service.py", "forza/application/db_doctor/"), (
        "tests/test_db_doctor_artifact_service.py",
        "tests/test_db_doctor_core_service.py",
        "tests/test_db_doctor_image_lap_service.py",
        "tests/test_db_doctor_modular_contracts_static.py",
        "tests/test_db_doctor_review_checks_static.py",
        "tests/test_db_doctor_review_service.py",
        "tests/test_db_doctor_run_checks_static.py",
        "tests/test_db_doctor_run_input_service.py",
        "tests/test_db_doctor_schema_checks_static.py",
        "tests/test_db_doctor_schema_service.py",
        "tests/test_db_doctor_source_image_checks_static.py",
        "tests/test_db_doctor_sqlite_checks_static.py",
        "tests/test_db_doctor_status_checks_static.py",
        "tests/test_schemas_services.py",
    )),
    (("forza/cli/maintenance.py", "forza/cli/parser.py"), (
        "tests/test_cli.py",
        "tests/test_cli_main.py",
        "tests/test_cli_maintenance.py",
        "tests/test_config.py",
        "tests/test_db_doctor_core_service.py",
    )),
    (("forza/domain/lap.py", "forza/application/best_lap_service.py", "forza/application/external_record_service.py", "forza/db/repositories/laps.py", "forza/db/repositories/external_records.py"), (
        "tests/test_best_lap_service.py",
        "tests/test_best_lap_service_integration.py",
        "tests/test_community_records_service.py",
        "tests/test_db_lap_repository.py",
        "tests/test_db_external_records_repository.py",
        "tests/test_export.py",
        "tests/test_report.py",
    )),
    (("forza/lmstudio/backend.py", "forza/pipeline/", "forza/application/database_service.py"), (
        "tests/test_pipeline.py",
        "tests/test_extractor.py",
        "tests/test_lmstudio_client.py",
        "tests/test_lmstudio_load_config.py",
        "tests/test_raw_evidence_policy.py",
        "tests/test_raw_response_record_static.py",
        "tests/test_raw_response_and_review_linkage.py",
        "tests/test_schemas_services.py",
    )),
    (("forza/gui/", "forza/application/gui_write_service.py"), (
        "tests/test_gui_read_extended.py",
        "tests/test_gui_write_dirty_decisions.py",
        "tests/test_gui_write_event_contract.py",
        "tests/test_gui_write_field_decisions.py",
        "tests/test_gui_write_flags_cases.py",
        "tests/test_gui_write_image_status.py",
        "tests/test_gui_write_location_static.py",
        "tests/test_gui_write_standalone.py",
        "tests/test_gui_image_management_static.py",
        "tests/test_gui_best_laps_static.py",
        "tests/test_gui_architecture_boundaries.py",
        "tests/test_gui_database_state.py",
        "tests/gui/test_config_state_diff.py",
    )),
    (("forza/output/",), (
        "tests/test_export.py",
        "tests/test_report.py",
        "tests/test_pdf_export_structure.py",
    )),
    (("forza/schemas/",), (
        "tests/test_schemas_services.py",
        "tests/test_models.py",
        "tests/test_gui_write_standalone.py",
    )),
    (("tools/run_release_audit.py", "tools/select_tests_for_changes.py"), (
        "tests/test_config.py",
    )),
)


def _run_git(args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def changed_files(*, base: str | None, include_working_tree: bool) -> list[str]:
    files: set[str] = set()

    if base:
        files.update(_run_git(["diff", "--name-only", f"{base}...HEAD"]))
    else:
        files.update(_run_git(["diff", "--name-only", "HEAD"]))

    if include_working_tree:
        files.update(_run_git(["diff", "--name-only"]))
        files.update(_run_git(["diff", "--name-only", "--cached"]))
        files.update(_run_git(["ls-files", "--others", "--exclude-standard"]))

    return sorted(path for path in files if path)


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(path == pattern or path.startswith(pattern) for pattern in patterns)


def select_tests(paths: Iterable[str], *, unknown_forza_policy: str = "smoke") -> dict[str, object]:
    changed = sorted({path.replace("\\", "/") for path in paths if path})
    tests: set[str] = set()
    reasons: list[dict[str, object]] = []
    unknown_forza: list[str] = []

    for path in changed:
        if path.startswith("tests/") and path.endswith(".py"):
            tests.add(path)
            reasons.append({"path": path, "reason": "changed test file", "tests": [path]})
            continue

        matched_for_path: set[str] = set()
        for patterns, rule_tests in RULES:
            if _matches(path, patterns):
                matched_for_path.update(rule_tests)

        if matched_for_path:
            tests.update(matched_for_path)
            reasons.append({"path": path, "reason": "mapped source rule", "tests": sorted(matched_for_path)})
        elif path.startswith("forza/"):
            unknown_forza.append(path)

    fallback = None
    if unknown_forza:
        if unknown_forza_policy == "full":
            fallback = "full"
        elif unknown_forza_policy == "smoke":
            tests.update(SMOKE_TESTS)
            fallback = "smoke"
            reasons.append({
                "path": "<unknown-forza>",
                "reason": "unknown forza/* change; selected smoke tests",
                "tests": list(SMOKE_TESTS),
                "files": unknown_forza,
            })
        elif unknown_forza_policy == "none":
            fallback = "none"

    existing_tests = [test for test in sorted(tests) if (ROOT / test).exists()]
    missing_tests = [test for test in sorted(tests) if not (ROOT / test).exists()]

    return {
        "changed_files": changed,
        "tests": existing_tests,
        "missing_tests": missing_tests,
        "fallback": fallback,
        "unknown_forza_files": unknown_forza,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a focused pytest set from changed files.")
    parser.add_argument("--base", default=None, help="Git base ref for branch diff, e.g. origin/main.")
    parser.add_argument("--include-working-tree", action="store_true", default=True)
    parser.add_argument("--no-working-tree", action="store_false", dest="include_working_tree")
    parser.add_argument("--unknown-forza-policy", choices=("smoke", "full", "none"), default="smoke")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--print-pytest-args", action="store_true")
    args = parser.parse_args()

    files = changed_files(base=args.base, include_working_tree=args.include_working_tree)
    selection = select_tests(files, unknown_forza_policy=args.unknown_forza_policy)

    if args.print_pytest_args:
        if selection["fallback"] == "full":
            print("")
        else:
            print(" ".join(selection["tests"]))
        return 0

    if args.json:
        print(json.dumps(selection, indent=2, sort_keys=True))
    else:
        print("Changed files:")
        for path in selection["changed_files"]:
            print(f"- {path}")
        print("\nSelected tests:")
        if selection["fallback"] == "full":
            print("- <full pytest required>")
        elif selection["tests"]:
            for test in selection["tests"]:
                print(f"- {test}")
        else:
            print("- <none>")
        if selection["missing_tests"]:
            print("\nMissing mapped tests:")
            for test in selection["missing_tests"]:
                print(f"- {test}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
