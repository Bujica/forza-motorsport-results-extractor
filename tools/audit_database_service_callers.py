from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DATABASE_SERVICE_PATH = Path("forza/application/database_service.py")

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "scripts",
    "venv",
}


@dataclass(frozen=True)
class MethodRecord:
    method: str
    line: int
    proposed_owner: str


@dataclass(frozen=True)
class CallerRecord:
    method: str
    caller_path: str
    caller_line: int
    caller_symbol: str
    proposed_owner: str
    confidence: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory DatabaseService public methods and likely callers.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root. Defaults to this tool's parent root.")
    parser.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help="Output format.",
    )
    parser.add_argument(
        "--method",
        help="Restrict output to a single DatabaseService public method.",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    methods = public_database_service_methods(root)
    if args.method:
        methods = [method for method in methods if method.method == args.method]
        if not methods:
            raise SystemExit(f"DatabaseService method not found: {args.method}")

    callers = find_callers(root, {method.method: method.proposed_owner for method in methods})

    if args.format == "json":
        print(json.dumps({"methods": [asdict(method) for method in methods], "callers": [asdict(caller) for caller in callers]}, indent=2, sort_keys=True))
    elif args.format == "csv":
        _write_csv(callers)
    else:
        _print_table(methods, callers)
    return 0


def public_database_service_methods(root: Path) -> list[MethodRecord]:
    path = root / DATABASE_SERVICE_PATH
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DatabaseService":
            methods = [
                MethodRecord(
                    method=child.name,
                    line=child.lineno,
                    proposed_owner=proposed_owner_for_method(child.name),
                )
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not child.name.startswith("_")
                and child.name not in {"__enter__", "__exit__"}
            ]
            return sorted(methods, key=lambda method: method.line)
    raise SystemExit(f"DatabaseService class not found in {path}")


def find_callers(root: Path, methods: dict[str, str]) -> list[CallerRecord]:
    records: list[CallerRecord] = []
    for path in iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method_name = None
            confidence = None
            if isinstance(node.func, ast.Attribute) and node.func.attr in methods:
                method_name = node.func.attr
                confidence = "attribute_call"
            elif isinstance(node.func, ast.Name) and node.func.id == "DatabaseService":
                method_name = "__constructor__"
                confidence = "constructor"
            if method_name is None or confidence is None:
                continue
            records.append(
                CallerRecord(
                    method=method_name,
                    caller_path=rel,
                    caller_line=node.lineno,
                    caller_symbol=enclosing_symbol(node, parents),
                    proposed_owner=methods.get(method_name, "DatabaseService"),
                    confidence=confidence,
                )
            )
    return sorted(records, key=lambda record: (record.method, record.caller_path, record.caller_line))


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def enclosing_symbol(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return current.name
    return "<module>"


def proposed_owner_for_method(method: str) -> str:
    name = method.lower()
    if name == "image_inventory":
        return "ImageInventoryReadService"
    if name in {"list_failed_images_for_retry", "register_source_image"}:
        return "ImageRetryRegistrationService"
    if name == "recompute_best_laps":
        return "BestLapRecomputeService"
    if name in {"count_lap_records", "count_best_laps"}:
        return "BestLapRecomputeService"
    if name == "upsert_image_and_laps":
        return "ExtractionPersistenceService"
    if name in {"list_full_flat", "list_clean_flat"}:
        return "ExportReadService"
    if name == "list_external_records":
        return "ExternalRecordReadService"
    if name == "replace_external_records":
        return "ExternalRecordPersistenceService"
    if name == "record_artifact":
        return "ExportArtifactService"
    if name in {"list_reference_tracks", "list_reference_cars"}:
        return "ReferenceDataService"
    if name == "seed_references":
        return "ReferenceDataService"
    if name == "load_reference_data":
        return "ReferenceDataService"
    if name == "refresh_review_cases":
        return "ReviewService"
    if name in {"list_open_review_cases", "count_review_cases"}:
        return "ReviewReadService"
    if name == "record_discovery_inputs":
        return "ImageDiscoveryInputService"
    if "runtime_snapshot" in name:
        return "RuntimeSnapshotService"
    if any(token in name for token in ("begin_run", "complete_run", "fail_preflight_run", "reconcile_interrupted_run", "reconcile_abandoned_runs", "reconcile_", "finish_run", "cancel_run", "fail_run", "latest_completed_run", "run_status", "runtime_snapshot", "mark_run")):
        return "RunService"
    if any(token in name for token in ("prepare_extraction", "record_result", "record_attempt", "attempt", "extraction_result", "model_artifact", "raw_response")):
        return "ExtractionPersistenceService"
    if any(token in name for token in ("source_image", "image", "duplicate", "metadata")):
        return "ImageService"
    if any(token in name for token in ("best_lap", "frontier", "lap")):
        return "BestLapService"
    if any(token in name for token in ("external", "import")):
        return "ExternalRecordService"
    if any(token in name for token in ("export", "pdf", "csv")):
        return "ExportService"
    if "rebuild" in name:
        return "RebuildService"
    if any(token in name for token in ("status", "summary", "engine", "session", "close")):
        return "DbSessionProvider"
    return "DatabaseService"


def _write_csv(records: list[CallerRecord]) -> None:
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=["method", "caller_path", "caller_line", "caller_symbol", "proposed_owner", "confidence"],
        lineterminator="\n",
    )
    writer.writeheader()
    for record in records:
        writer.writerow(asdict(record))


def _print_table(methods: list[MethodRecord], callers: list[CallerRecord]) -> None:
    print("DatabaseService public methods:")
    print(f"{'line':>5} {'proposed_owner':<28} method")
    for method in methods:
        print(f"{method.line:>5} {method.proposed_owner:<28} {method.method}")

    print()
    print("Likely callers:")
    print(f"{'line':>5} {'confidence':<14} {'proposed_owner':<28} method caller")
    for record in callers:
        location = f"{record.caller_path}:{record.caller_line}::{record.caller_symbol}"
        print(f"{record.caller_line:>5} {record.confidence:<14} {record.proposed_owner:<28} {record.method} {location}")

    print()
    print(f"methods: {len(methods)}")
    print(f"caller hits: {len(callers)}")


if __name__ == "__main__":
    raise SystemExit(main())
