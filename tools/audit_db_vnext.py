from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuditSection:
    key: str
    title: str
    runner: Callable[[sqlite3.Connection], None]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a db_vnext SQLite runtime database.")
    parser.add_argument("database", nargs="?", default="data/forza.sqlite3")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Run only selected section(s). Comma-separated values are accepted.",
    )
    parser.add_argument("--list-sections", action="store_true", help="List available section keys and exit.")
    parser.add_argument("--json", action="store_true", help="Emit JSON keyed by section instead of text.")
    parser.add_argument("--out", type=Path, help="Write output to this file instead of stdout.")
    args = parser.parse_args()

    sections = _sections()

    if args.list_sections:
        text = "\n".join(f"{section.key}\t{section.title}" for section in sections) + "\n"
        _write_or_print(text, args.out)
        return 0

    selected_keys = _selected_keys(args.only, sections)
    db = Path(args.database)
    if not db.exists():
        _write_or_print(f"ERROR database not found: {db}\n", args.out)
        return 2

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    try:
        selected = [section for section in sections if section.key in selected_keys]
        if args.json:
            payload = {
                "database": str(db),
                "sections": {section.key: _capture_section(con, section) for section in selected},
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        else:
            chunks = [
                f"Database: {db}",
                f"SQLite integrity_check: {_scalar(con, 'PRAGMA integrity_check')}",
                f"Foreign key violations: {len(con.execute('PRAGMA foreign_key_check').fetchall())}",
                "",
            ]
            for section in selected:
                chunks.append(_capture_section(con, section).rstrip())
                chunks.append("")
            text = "\n".join(chunks).rstrip() + "\n"
    finally:
        con.close()

    _write_or_print(text, args.out)
    return 0


def _sections() -> list[AuditSection]:
    return [
        AuditSection("schema", "Schema", _print_revision),
        AuditSection("counts", "Table counts", _print_counts),
        AuditSection("runs", "Runs", _print_runs),
        AuditSection("run-inputs", "Run inputs by decision/reason", _print_run_inputs),
        AuditSection("results", "Extraction results", _print_results),
        AuditSection("attempts", "Attempts", _print_attempts),
        AuditSection("artifacts", "Artifacts", _print_artifacts),
        AuditSection("reviews", "Review cases", _print_reviews),
        AuditSection("doctor-equivalents", "Focused invariant checks", _print_doctor_equivalents),
        AuditSection("suspicious", "Suspicious rows", _print_suspicious_rows),
    ]


def _selected_keys(raw_values: Iterable[str], sections: list[AuditSection]) -> set[str]:
    valid = {section.key for section in sections}
    selected: set[str] = set()
    for raw_value in raw_values:
        for item in raw_value.split(","):
            value = item.strip()
            if value:
                selected.add(value)
    if not selected:
        return valid
    unknown = sorted(selected - valid)
    if unknown:
        raise SystemExit(f"Unknown section(s): {', '.join(unknown)}. Use --list-sections.")
    return selected


def _capture_section(con: sqlite3.Connection, section: AuditSection) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        section.runner(con)
    return buffer.getvalue()


def _write_or_print(text: str, out: Path | None) -> None:
    if out is None:
        print(text, end="")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}")


def _scalar(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return con.execute(sql, params).fetchone()[0]


def _rows(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(con.execute(sql, params).fetchall())


def _section(title: str) -> None:
    print(f"== {title} ==")


def _print_revision(con: sqlite3.Connection) -> None:
    _section("Schema")
    if _table_exists(con, "alembic_version"):
        print(f"alembic_version: {_scalar(con, 'SELECT version_num FROM alembic_version')}")
    else:
        print("alembic_version: MISSING")


def _print_counts(con: sqlite3.Connection) -> None:
    _section("Table counts")
    tables = [
        "source_images", "extraction_runs", "run_inputs", "model_runtime_snapshots",
        "extraction_results", "extraction_attempts", "model_artifacts", "lap_records",
        "review_cases", "image_flags", "export_artifacts", "prompt_snapshots",
        "reference_tracks", "reference_cars", "external_record_imports",
        "external_lap_records", "lab_runs", "lab_run_cases", "lab_artifacts",
        "lab_samples", "lab_sample_images", "ground_truth_datasets", "ground_truth_cases",
    ]
    for table in tables:
        if _table_exists(con, table):
            print(f"{table}: {_scalar(con, f'SELECT COUNT(*) FROM {table}')}")


def _print_runs(con: sqlite3.Connection) -> None:
    _section("Runs")
    if not _table_exists(con, "extraction_runs"):
        print("extraction_runs: MISSING")
        return
    for row in _rows(con, """
        SELECT id, status, mode, total_inputs, to_process, processed, succeeded, failed,
               skipped, duplicate_count, review_case_count, config_extra_json,
               operational_error_message
        FROM extraction_runs
        ORDER BY created_at
        """):
        print(dict(row))


def _print_run_inputs(con: sqlite3.Connection) -> None:
    _section("Run inputs by decision/reason")
    if not _table_exists(con, "run_inputs"):
        print("run_inputs: MISSING")
        return
    for row in _rows(con, """
        SELECT run_id, decision, COALESCE(process_reason, '-') AS process_reason,
               COALESCE(skip_reason, '-') AS skip_reason,
               COALESCE(duplicate_kind, '-') AS duplicate_kind,
               COUNT(*) AS count
        FROM run_inputs
        GROUP BY run_id, decision, process_reason, skip_reason, duplicate_kind
        ORDER BY run_id, decision, process_reason, skip_reason, duplicate_kind
        """):
        print(dict(row))


def _print_results(con: sqlite3.Connection) -> None:
    _section("Extraction results")
    if not _table_exists(con, "extraction_results"):
        print("extraction_results: MISSING")
        return
    for row in _rows(con, """
        SELECT status, COUNT(*) AS count,
               SUM(CASE WHEN accepted_attempt_id IS NULL THEN 1 ELSE 0 END) AS without_accepted_attempt,
               SUM(CASE WHEN prompt_snapshot_id IS NULL THEN 1 ELSE 0 END) AS without_prompt_snapshot
        FROM extraction_results
        GROUP BY status
        ORDER BY status
        """):
        print(dict(row))


def _print_attempts(con: sqlite3.Connection) -> None:
    _section("Attempts")
    if not _table_exists(con, "extraction_attempts"):
        print("extraction_attempts: MISSING")
        return
    for row in _rows(con, """
        SELECT status, accepted, COUNT(*) AS count,
               SUM(CASE WHEN raw_response IS NULL OR raw_response = '' THEN 1 ELSE 0 END) AS missing_raw_response,
               SUM(CASE WHEN request_hash IS NULL OR request_hash = '' THEN 1 ELSE 0 END) AS missing_request_hash
        FROM extraction_attempts
        GROUP BY status, accepted
        ORDER BY status, accepted
        """):
        print(dict(row))


def _print_artifacts(con: sqlite3.Connection) -> None:
    _section("Artifacts")
    if not _table_exists(con, "model_artifacts"):
        print("model_artifacts: MISSING")
        return
    for row in _rows(con, """
        SELECT artifact_type, is_canonical, COUNT(*) AS count,
               SUM(CASE WHEN attempt_id IS NULL THEN 1 ELSE 0 END) AS without_attempt
        FROM model_artifacts
        GROUP BY artifact_type, is_canonical
        ORDER BY artifact_type, is_canonical
        """):
        print(dict(row))


def _print_reviews(con: sqlite3.Connection) -> None:
    _section("Review cases")
    if not _table_exists(con, "review_cases"):
        print("review_cases: MISSING")
        return
    for row in _rows(con, """
        SELECT status, reason, COUNT(*) AS count
        FROM review_cases
        GROUP BY status, reason
        ORDER BY status, reason
        """):
        print(dict(row))


def _print_doctor_equivalents(con: sqlite3.Connection) -> None:
    _section("Focused invariant checks (DB Doctor is authoritative)")
    checks = {
        "run_inputs_process_without_source_image": """
            SELECT COUNT(*) FROM run_inputs
            WHERE decision = 'process' AND source_image_id IS NULL
        """,
        "run_inputs_process_without_one_result": """
            SELECT COUNT(*) FROM (
                SELECT ri.id
                FROM run_inputs ri
                LEFT JOIN extraction_results er ON er.run_input_id = ri.id
                WHERE ri.decision = 'process'
                GROUP BY ri.id
                HAVING COUNT(er.id) <> 1
            )
        """,
        "ok_results_without_accepted_attempt": """
            SELECT COUNT(*) FROM extraction_results
            WHERE status = 'ok' AND accepted_attempt_id IS NULL
        """,
        "accepted_attempt_pointer_invalid": """
            SELECT COUNT(*)
            FROM extraction_results er
            LEFT JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
            WHERE er.accepted_attempt_id IS NOT NULL
              AND (a.id IS NULL OR a.accepted <> 1 OR a.status <> 'ok')
        """,
        "error_results_with_laps": """
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN lap_records lr ON lr.extraction_result_id = er.id
            WHERE er.status = 'error'
        """,
        "runs_after_preflight_missing_runtime_snapshot": """
            SELECT COUNT(*)
            FROM extraction_runs r
            WHERE r.status IN ('completed', 'cancelled')
              AND r.mode <> 'dry_run'
              AND (r.to_process > 0 OR r.processed > 0 OR r.succeeded > 0 OR r.failed > 0)
              AND NOT EXISTS (
                  SELECT 1 FROM model_runtime_snapshots s
                  WHERE s.run_id = r.id AND s.snapshot_kind = 'preflight'
              )
        """,
        "request_messages_contain_image_payload": """
            SELECT COUNT(*) FROM extraction_attempts
            WHERE lower(CAST(request_messages_json AS TEXT)) LIKE '%data:image%'
               OR lower(CAST(request_messages_json AS TEXT)) LIKE '%base64%'
        """,
        "canonical_artifacts_without_attempt": """
            SELECT COUNT(*) FROM model_artifacts
            WHERE is_canonical = 1 AND attempt_id IS NULL
        """,
        "review_business_key_uses_lap_record_id": """
            SELECT COUNT(*) FROM review_cases
            WHERE lap_record_id IS NOT NULL AND instr(business_key, lap_record_id) > 0
        """,
        "flag_key_uses_lap_record_id": """
            SELECT COUNT(*) FROM image_flags
            WHERE lap_record_id IS NOT NULL AND instr(flag_key, lap_record_id) > 0
        """,
    }
    for key, sql in checks.items():
        try:
            print(f"{key}: {_scalar(con, sql)}")
        except sqlite3.OperationalError as exc:
            print(f"{key}: skipped ({exc})")


def _print_suspicious_rows(con: sqlite3.Connection) -> None:
    _section("Suspicious rows")
    queries = {
        "source_images_without_results": """
            SELECT si.current_name, si.file_hash
            FROM source_images si
            WHERE NOT EXISTS (
                SELECT 1 FROM extraction_results er WHERE er.source_image_id = si.id
            )
            ORDER BY si.created_at
            LIMIT 20
        """,
        "process_inputs_without_results": """
            SELECT run_id, file_name, file_hash
            FROM run_inputs ri
            WHERE decision = 'process'
              AND NOT EXISTS (SELECT 1 FROM extraction_results er WHERE er.run_input_id = ri.id)
            ORDER BY id
            LIMIT 20
        """,
        "results_without_laps": """
            SELECT er.id, er.status, si.current_name
            FROM extraction_results er
            JOIN source_images si ON si.id = er.source_image_id
            WHERE er.status = 'ok'
              AND NOT EXISTS (SELECT 1 FROM lap_records lr WHERE lr.extraction_result_id = er.id)
            ORDER BY er.created_at
            LIMIT 20
        """,
    }
    for title, sql in queries.items():
        try:
            rows = _rows(con, sql)
        except sqlite3.OperationalError as exc:
            print(f"{title}: skipped ({exc})")
            continue
        print(f"{title}: {len(rows)} shown")
        for row in rows:
            print("  " + json.dumps(dict(row), ensure_ascii=False))


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone())


if __name__ == "__main__":
    raise SystemExit(main())
