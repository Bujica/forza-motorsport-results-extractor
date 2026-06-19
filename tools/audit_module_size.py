from __future__ import annotations

import argparse
import ast
import csv
import fnmatch
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

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
    "forza_screenshot_extractor.egg-info",
    "scripts",
    "venv",
}

INCLUDED_SUFFIXES = {
    ".cfg",
    ".ini",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}

ALLOWLIST_PATTERNS = (
    "CHANGELOG.md",
    "docs/history/*",
    "docs/plans/*",
    "forza/db/migrations/*",
    "forza/db/migrations/versions/0001_db_vnext_schema.sql",
)

LINE_BUDGET_BY_KIND = {
    "application_service": 500,
    "db_model": 500,
    "gui": 450,
    "test": 350,
    "tool": 500,
    "migration": 900,
    "documentation": 700,
    "common": 400,
}

SYMBOL_BUDGETS = {
    "function": 60,
    "class": 250,
}


@dataclass(frozen=True)
class FileSizeRecord:
    path: str
    kind: str
    owner_area: str
    lines: int
    bytes: int
    budget: int
    allowlisted: bool
    over_budget: bool


@dataclass(frozen=True)
class SymbolSizeRecord:
    path: str
    symbol_type: str
    name: str
    owner_area: str
    start_line: int
    end_line: int
    lines: int
    budget: int
    over_budget: bool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report large files and symbols by project maintenance area.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root. Defaults to this tool's parent root.")
    parser.add_argument("--top", type=int, default=30, help="Number of largest files to print in table mode.")
    parser.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help="Output format.",
    )
    parser.add_argument(
        "--symbols",
        action="store_true",
        help="Also report Python classes/functions over the symbol budget.",
    )
    parser.add_argument(
        "--fail-on-budget",
        action="store_true",
        help="Exit non-zero when a non-allowlisted file or symbol is over budget.",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    files = collect_file_records(root)
    symbols = collect_symbol_records(root) if args.symbols else []

    if args.format == "json":
        payload = {
            "files": [asdict(record) for record in files],
            "symbols": [asdict(record) for record in symbols],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.format == "csv":
        _write_csv(files)
    else:
        _print_table(files, args.top)
        if args.symbols:
            _print_symbol_table(symbols)

    failing_files = [record for record in files if record.over_budget and not record.allowlisted]
    failing_symbols = [record for record in symbols if record.over_budget]
    if args.fail_on_budget and (failing_files or failing_symbols):
        return 1
    return 0


def collect_file_records(root: Path) -> list[FileSizeRecord]:
    records: list[FileSizeRecord] = []
    for path in iter_project_files(root):
        rel = path.relative_to(root).as_posix()
        kind = classify_path(rel)
        owner_area = owner_for_path(rel)
        lines = count_lines(path)
        bytes_count = path.stat().st_size
        budget = LINE_BUDGET_BY_KIND[kind]
        allowlisted = is_allowlisted(rel)
        records.append(
            FileSizeRecord(
                path=rel,
                kind=kind,
                owner_area=owner_area,
                lines=lines,
                bytes=bytes_count,
                budget=budget,
                allowlisted=allowlisted,
                over_budget=lines > budget,
            )
        )
    return sorted(records, key=lambda record: (record.lines, record.bytes), reverse=True)


def collect_symbol_records(root: Path) -> list[SymbolSizeRecord]:
    records: list[SymbolSizeRecord] = []
    for path in iter_project_files(root):
        if path.suffix != ".py":
            continue
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        owner_area = owner_for_path(rel)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", node.lineno)
                lines = end_line - node.lineno + 1
                budget = SYMBOL_BUDGETS["function"]
                records.append(
                    SymbolSizeRecord(
                        path=rel,
                        symbol_type="function",
                        name=node.name,
                        owner_area=owner_area,
                        start_line=node.lineno,
                        end_line=end_line,
                        lines=lines,
                        budget=budget,
                        over_budget=lines > budget,
                    )
                )
            elif isinstance(node, ast.ClassDef):
                end_line = getattr(node, "end_lineno", node.lineno)
                lines = end_line - node.lineno + 1
                budget = SYMBOL_BUDGETS["class"]
                records.append(
                    SymbolSizeRecord(
                        path=rel,
                        symbol_type="class",
                        name=node.name,
                        owner_area=owner_area,
                        start_line=node.lineno,
                        end_line=end_line,
                        lines=lines,
                        budget=budget,
                        over_budget=lines > budget,
                    )
                )
    return sorted(records, key=lambda record: record.lines, reverse=True)


def iter_project_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(root).parts[:-1]):
            continue
        if path.suffix.lower() not in INCLUDED_SUFFIXES:
            continue
        yield path


def count_lines(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text:
        return 0
    return len(text.splitlines())


def classify_path(rel: str) -> str:
    if rel.startswith("tests/"):
        return "test"
    if rel.startswith("tools/"):
        return "tool"
    if rel.startswith("docs/") or rel in {"CHANGELOG.md", "QUICK_GUIDE.md", "README.md"}:
        return "documentation"
    if rel.startswith("forza/db/migrations/"):
        return "migration"
    if rel == "forza/db/models.py" or rel.startswith("forza/db/entities/"):
        return "db_model"
    if rel.startswith("forza/application/"):
        return "application_service"
    if rel.startswith("forza/gui/"):
        return "gui"
    return "common"


def owner_for_path(rel: str) -> str:
    parts = rel.split("/")
    if rel.startswith("forza/application/gui_read"):
        return "application.gui_read"
    if rel.startswith("forza/application/db_doctor"):
        return "application.db_doctor"
    if len(parts) >= 3 and parts[0] == "forza":
        return ".".join(parts[:3]) if parts[1] in {"application", "gui", "db", "lmstudio"} else ".".join(parts[:2])
    if parts[0] in {"tests", "docs", "tools"} and len(parts) >= 2:
        return ".".join(parts[:2])
    return parts[0]


def is_allowlisted(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in ALLOWLIST_PATTERNS)


def _write_csv(records: list[FileSizeRecord]) -> None:
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=["path", "kind", "owner_area", "lines", "bytes", "budget", "allowlisted", "over_budget"],
        lineterminator="\n",
    )
    writer.writeheader()
    for record in records:
        writer.writerow(asdict(record))


def _print_table(records: list[FileSizeRecord], top: int) -> None:
    print("Largest files:")
    print(f"{'lines':>7} {'budget':>7} {'over':>5} {'allow':>5} {'kind':<20} path")
    for record in records[:top]:
        print(
            f"{record.lines:>7} {record.budget:>7} {str(record.over_budget):>5} "
            f"{str(record.allowlisted):>5} {record.kind:<20} {record.path}"
        )
    over = [record for record in records if record.over_budget and not record.allowlisted]
    print()
    print(f"files scanned: {len(records)}")
    print(f"non-allowlisted files over budget: {len(over)}")


def _print_symbol_table(records: list[SymbolSizeRecord]) -> None:
    over = [record for record in records if record.over_budget]
    print()
    print("Largest Python symbols:")
    print(f"{'lines':>7} {'budget':>7} {'over':>5} {'type':<9} location")
    for record in records[:30]:
        print(
            f"{record.lines:>7} {record.budget:>7} {str(record.over_budget):>5} "
            f"{record.symbol_type:<9} {record.path}:{record.start_line} {record.name}"
        )
    print()
    print(f"symbols scanned: {len(records)}")
    print(f"symbols over budget: {len(over)}")


if __name__ == "__main__":
    raise SystemExit(main())
