"""Extract the Python baseline used by Rust-migration fixtures (Fase 0).

Versioned outputs (safe for Git): schema inventory, row counts, reference data,
per-run performance aggregates.

Local-only outputs (keep out of Git): best-laps CSV/PDF generated through the
real ExportService, and sampled LM Studio raw responses.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VERSIONED_FILES = (
    "schema_inventory.json",
    "counts.json",
    "reference_data.json",
    "runs_performance_summary.json",
)


def open_readonly(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def dump_schema(conn: sqlite3.Connection) -> dict:
    inventory: dict = {"tables": {}, "triggers": []}
    for table in table_names(conn):
        columns = []
        for cid, name, ctype, notnull, dflt, pk in conn.execute(
            f"PRAGMA table_info([{table}])"
        ):
            columns.append(
                {
                    "name": name,
                    "type": ctype,
                    "notnull": bool(notnull),
                    "default": dflt,
                    "pk": pk,
                }
            )
        indexes = []
        for info in conn.execute(f"PRAGMA index_list([{table}])").fetchall():
            _, iname, iunique, iorigin, ipartial = info[:5]
            cols = [r[2] for r in conn.execute(f"PRAGMA index_info([{iname}])")]
            where = None
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                (iname,),
            ).fetchone()
            if row and row[0] and "WHERE" in row[0].upper():
                where = row[0][row[0].upper().index("WHERE") :].strip()
            indexes.append(
                {
                    "name": iname,
                    "unique": bool(iunique),
                    "origin": iorigin,
                    "columns": cols,
                    "partial_where": where,
                }
            )
        fks = [
            {
                "from": r[3],
                "table": r[2],
                "to": r[4],
                "on_update": r[5],
                "on_delete": r[6],
            }
            for r in conn.execute(f"PRAGMA foreign_key_list([{table}])")
        ]
        create_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        checks = [
            line.strip()
            for line in create_sql.splitlines()
            if "CHECK" in line.upper()
        ]
        inventory["tables"][table] = {
            "columns": columns,
            "indexes": indexes,
            "foreign_keys": fks,
            "checks": checks,
            "create_sql": create_sql,
        }
    index_statements = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='index' AND sql IS NOT NULL ORDER BY name"
    ).fetchall()
    inventory["index_sql"] = [
        {"name": name, "sql": sql} for name, sql in index_statements
    ]
    triggers = conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
    ).fetchall()
    inventory["triggers"] = [
        {"name": n, "table": t, "sql": s} for n, t, s in triggers
    ]
    return inventory


def dump_counts(conn: sqlite3.Connection) -> dict:
    return {t: conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0] for t in table_names(conn)}


def dump_references(conn: sqlite3.Connection) -> dict:
    out = {}
    for table in ("reference_tracks", "reference_cars"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{table}])")]
        rows = conn.execute(f"SELECT * FROM [{table}] ORDER BY id").fetchall()
        out[table] = [dict(zip(cols, row)) for row in rows]
    return out


RUN_PERF_COLUMNS = (
    "id",
    "status",
    "started_at",
    "finished_at",
    "performance_tps_floor",
    "performance_reload_elapsed_s",
    "performance_reload_streak",
)


def dump_runs_performance(conn: sqlite3.Connection) -> dict:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(extraction_runs)")]
    selected = [c for c in RUN_PERF_COLUMNS if c in cols]
    runs = []
    for row in conn.execute(
        f"SELECT {', '.join(selected)} FROM extraction_runs ORDER BY id"
    ):
        runs.append(dict(zip(selected, row)))
    agg = conn.execute(
        "SELECT run_id, COUNT(*), SUM(CASE WHEN accepted THEN 1 ELSE 0 END), "
        "AVG(tokens_per_second), MAX(tokens_per_second), "
        "SUM(CASE WHEN parse_error IS NOT NULL AND parse_error != '' THEN 1 ELSE 0 END) "
        "FROM extraction_attempts GROUP BY run_id ORDER BY run_id"
    ).fetchall()
    attempts = {
        r[0]: {
            "attempts": r[1],
            "accepted": r[2],
            "avg_tps": r[3],
            "max_tps": r[4],
            "parse_errors": r[5],
        }
        for r in agg
    }
    malformed = conn.execute(
        "SELECT COUNT(*) FROM extraction_attempts "
        "WHERE raw_response IS NOT NULL AND ("
        "(parse_error IS NOT NULL AND parse_error != '') OR "
        "(validation_status IS NOT NULL AND validation_status NOT IN ('', 'ok')))"
    ).fetchone()[0]
    return {"runs": runs, "attempt_aggregates": attempts, "malformed_responses": malformed}


def dump_responses(
    conn: sqlite3.Connection, out_dir: Path, sample: int
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {"accepted": 0, "malformed": 0}
    query_accepted = (
        "SELECT a.id, a.raw_response, a.parsed_json, a.model "
        "FROM extraction_attempts a "
        "WHERE a.accepted AND a.raw_response IS NOT NULL "
        "ORDER BY a.id LIMIT ?"
    )
    for row in conn.execute(query_accepted, (sample,)):
        aid, raw, parsed, model = row
        payload = {
            "kind": "accepted",
            "attempt_id": aid,
            "model": model,
            "raw_response": raw,
            "parsed_json": json.loads(parsed) if isinstance(parsed, str) else parsed,
        }
        (out_dir / f"accepted_{aid}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written["accepted"] += 1
    query_malformed = (
        "SELECT a.id, a.raw_response, a.parsed_json, a.parse_error, "
        "a.validation_status, a.validation_issues_json "
        "FROM extraction_attempts a "
        "WHERE a.raw_response IS NOT NULL AND ("
        "(a.parse_error IS NOT NULL AND a.parse_error != '') OR "
        "(a.validation_status IS NOT NULL AND a.validation_status NOT IN ('', 'ok')))"
        " ORDER BY a.id LIMIT ?"
    )
    for row in conn.execute(query_malformed, (sample,)):
        aid, raw, parsed, perr, vstatus, vissues = row
        payload = {
            "kind": "malformed",
            "attempt_id": aid,
            "parse_error": perr,
            "validation_status": vstatus,
            "validation_issues": json.loads(vissues) if vissues else [],
            "raw_response": raw,
            "parsed_json": json.loads(parsed) if isinstance(parsed, str) else None,
        }
        (out_dir / f"malformed_{aid}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written["malformed"] += 1
    return written


def generate_exports(db: Path, out_dir: Path) -> dict:
    from forza.application import ExportService
    from forza.config import load_config
    from forza.application.database_service import DatabaseService

    cfg = load_config(ROOT / "forza_config.ini")
    cfg.database_file = db
    service = ExportService()
    csv_path = out_dir / "best_laps.csv"
    pdf_path = out_dir / "best_laps.pdf"
    count = service.clean_csv(cfg, csv_path)
    result = {"csv_rows": count}
    if count:
        database = DatabaseService(db)
        try:
            results = database.list_clean_flat()
        finally:
            database.close() if hasattr(database, "close") else None
        seen: list[str] = []
        for lap in results:
            if lap.track not in seen:
                seen.append(lap.track)
        service.pdf(results, pdf_path, cfg, seen)
        result["pdf_sections"] = len(seen)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "forza.sqlite3")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "forza-rust" / "fixtures" / "python_outputs"
    )
    parser.add_argument(
        "--responses-dir",
        type=Path,
        default=ROOT / "forza-rust" / "fixtures" / "model_responses",
    )
    parser.add_argument("--sample", type=int, default=25)
    parser.add_argument("--skip-exports", action="store_true")
    ns = parser.parse_args()

    ns.out.mkdir(parents=True, exist_ok=True)
    conn = open_readonly(ns.db)
    try:
        payloads = {
            "schema_inventory.json": dump_schema(conn),
            "counts.json": dump_counts(conn),
            "reference_data.json": dump_references(conn),
            "runs_performance_summary.json": dump_runs_performance(conn),
        }
        for name, data in payloads.items():
            (ns.out / name).write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        print(f"versioned artifacts -> {ns.out}")
        responses = dump_responses(conn, ns.responses_dir, ns.sample)
        print(f"responses -> {ns.responses_dir}: {responses}")
    finally:
        conn.close()

    if not ns.skip_exports:
        exports = generate_exports(ns.db.resolve(), ns.out)
        print(f"exports -> {exports}")
    else:
        print("exports skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
