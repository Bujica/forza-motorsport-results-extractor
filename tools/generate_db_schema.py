"""Generate the Rust DDL module from the audited Python schema inventory.

Reads `forza-rust/fixtures/python_outputs/schema_inventory.json` (captured
from a real 0.21.0-beta.1 database) and writes
`forza-rust/crates/forza-db/src/schema_ddl.rs`.

Tables are emitted in dependency order (parents before children) so the list
can be executed under `PRAGMA foreign_keys=ON`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "forza-rust" / "fixtures" / "python_outputs" / "schema_inventory.json"
OUTPUT = ROOT / "forza-rust" / "crates" / "forza-db" / "src" / "schema_ddl.rs"

HEADER = """//! Generated DDL for the Rust port — DO NOT EDIT BY HAND.
//!
//! Source of truth: `fixtures/python_outputs/schema_inventory.json`,
//! captured from a real 0.21.0-beta.1 SQLite database.
//! Regenerate with: `py -3.11 tools/generate_db_schema.py`

/// CREATE TABLE statements in dependency order (parents first).
pub const TABLE_DDL: &[&str] = &[
"""

MID = """];

/// Standalone CREATE INDEX statements (including partial unique indexes).
pub const INDEX_DDL: &[&str] = &[
"""

FOOTER = """];

/// Schema version stamped into `PRAGMA user_version` after a full build.
pub const SCHEMA_VERSION: i64 = 1;
"""


def rust_string(sql: str) -> str:
    body = sql.replace('"#', '"\u0023')
    return f'r#"{body}"#'


def topological(tables: dict[str, dict]) -> list[str]:
    names = sorted(tables)
    parents: dict[str, set[str]] = {}
    for name in names:
        refs = {
            fk["table"]
            for fk in tables[name]["foreign_keys"]
            if fk["table"] in tables and fk["table"] != name
        }
        parents[name] = refs

    ordered: list[str] = []
    remaining = set(names)
    while remaining:
        ready = sorted(n for n in remaining if not (parents[n] & remaining))
        if not ready:
            raise RuntimeError(f"circular dependencies among: {sorted(remaining)}")
        ordered.extend(ready)
        remaining -= set(ready)
    return ordered


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    tables = inventory["tables"]

    # Alphabetical order: the schema contains a mutual reference
    # (extraction_attempts <-> extraction_results), so the migration runner
    # creates everything under PRAGMA foreign_keys=OFF inside one transaction.
    lines: list[str] = [HEADER]
    for name in sorted(tables):
        lines.append(f"    // {name}\n")
        lines.append(f"    {rust_string(tables[name]['create_sql'])},\n\n")
    lines.append(MID)

    for entry in inventory["index_sql"]:
        sql = entry["sql"]
        if sql.lower().startswith("create unique index") is False:
            continue
        lines.append(f"    // {entry['name']}\n")
        lines.append(f"    {rust_string(sql)},\n\n")

    non_unique = [
        entry for entry in inventory["index_sql"]
        if not entry["sql"].lower().startswith("create unique index")
    ]
    for entry in non_unique:
        lines.append(f"    // {entry['name']}\n")
        lines.append(f"    {rust_string(entry['sql'])},\n\n")
    lines.append(FOOTER)

    OUTPUT.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(inventory['index_sql'])} index statements)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
