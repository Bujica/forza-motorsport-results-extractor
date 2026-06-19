#!/usr/bin/env python3
"""
Diagnose imported external-record car names against the canonical Forza car list.

Read-only. Does not modify the database.

Typical usage from the repository root:

    python diagnose_car_imports.py --db data/forza.sqlite3 --out car_import_diagnostic.json

Then send:
  1. the terminal summary
  2. the generated JSON file, or its contents

The script uses only Python stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def car_match_key(value: str | None) -> str:
    """Diagnostic key for likely car-name aliases.

    Normalizes smart quotes, apostrophes, model years like '19/2019, punctuation,
    spacing, and case. This script reports candidates only; it does not modify DB.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
        .replace("´", "'")
        .replace("ʹ", "'")
    )
    text = text.casefold()
    text = re.sub(r"\b(?:19|20)(\d{2})\b", r"\1", text)
    text = re.sub(r"(?<=\s)'(?=\d{2}\b)", "", text)
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def display_ratio(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio(), 4)


def key_ratio(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, car_match_key(a), car_match_key(b)).ratio(), 4)


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def column_names(con: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(con, table):
        return set()
    return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})")}


def safe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def load_reference_cars(con: sqlite3.Connection, fallback_file: Path | None = None) -> list[dict[str, Any]]:
    cars: list[dict[str, Any]] = []
    if table_exists(con, "reference_cars"):
        cols = column_names(con, "reference_cars")
        active_filter = "WHERE active = 1" if "active" in cols else ""
        aliases_col = "aliases_json" if "aliases_json" in cols else "NULL AS aliases_json"
        normalized_col = "normalized_name" if "normalized_name" in cols else "NULL AS normalized_name"
        race_class_col = "race_class" if "race_class" in cols else "NULL AS race_class"
        rows = con.execute(
            f"""
            SELECT name, {normalized_col}, {race_class_col}, {aliases_col}
            FROM reference_cars
            {active_filter}
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        for row in rows:
            aliases = []
            raw_aliases = row["aliases_json"]
            if raw_aliases:
                parsed = safe_json(raw_aliases)
                if isinstance(parsed, list):
                    aliases = [str(item) for item in parsed if str(item).strip()]
            cars.append(
                {
                    "name": str(row["name"]),
                    "normalized_name": row["normalized_name"],
                    "race_class": row["race_class"],
                    "aliases": aliases,
                    "source": "reference_cars",
                }
            )

    if not cars and fallback_file and fallback_file.exists():
        for line in fallback_file.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                cars.append({"name": name, "normalized_name": None, "race_class": None, "aliases": [], "source": str(fallback_file)})
    return cars


def load_external_cars(con: sqlite3.Connection, include_inactive: bool) -> list[dict[str, Any]]:
    if not table_exists(con, "external_lap_records"):
        return []
    cols = column_names(con, "external_lap_records")
    active_filter = "" if include_inactive or "active" not in cols else "WHERE active = 1"
    car_norm = "car_normalized" if "car_normalized" in cols else "NULL AS car_normalized"
    race_class = "race_class" if "race_class" in cols else "NULL AS race_class"
    track = "track" if "track" in cols else "NULL AS track"
    rows = con.execute(
        f"""
        SELECT car, {car_norm}, {race_class}, COUNT(*) AS row_count, COUNT(DISTINCT {track}) AS track_count
        FROM external_lap_records
        {active_filter}
        GROUP BY car, car_normalized, race_class
        ORDER BY row_count DESC, car COLLATE NOCASE
        """
    ).fetchall()
    return [dict(row) for row in rows]


def load_internal_best_cars(con: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(con, "lap_records"):
        return []
    cols = column_names(con, "lap_records")
    where = "WHERE is_best_lap = 1" if "is_best_lap" in cols else ""
    car_norm = "car_normalized" if "car_normalized" in cols else "NULL AS car_normalized"
    race_class = "race_class" if "race_class" in cols else "NULL AS race_class"
    rows = con.execute(
        f"""
        SELECT car, {car_norm}, {race_class}, COUNT(*) AS row_count
        FROM lap_records
        {where}
        GROUP BY car, car_normalized, race_class
        ORDER BY row_count DESC, car COLLATE NOCASE
        """
    ).fetchall()
    return [dict(row) for row in rows]


def load_import_issue_summary(con: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(con, "external_record_imports"):
        return {}
    cols = column_names(con, "external_record_imports")
    active_col = "active" if "active" in cols else "0 AS active"
    status_col = "status" if "status" in cols else "NULL AS status"
    totals_col = "totals" if "totals" in cols else "NULL AS totals"
    issues_col = "issues_json" if "issues_json" in cols else "NULL AS issues_json"
    rows = con.execute(
        f"""
        SELECT id, source_path, {status_col}, {active_col}, {totals_col}, {issues_col}, imported_at, created_at
        FROM external_record_imports
        ORDER BY created_at DESC
        LIMIT 5
        """
    ).fetchall()
    imports = []
    for row in rows:
        issues = safe_json(row["issues_json"])
        imports.append(
            {
                "id": row["id"],
                "source_path": row["source_path"],
                "status": row["status"],
                "active": bool(row["active"]),
                "totals": safe_json(row["totals"]),
                "issue_count": len(issues) if isinstance(issues, list) else None,
                "imported_at": row["imported_at"],
                "created_at": row["created_at"],
            }
        )
    return {"recent_imports": imports}


def build_canonical_indexes(reference_cars: list[dict[str, Any]]) -> dict[str, Any]:
    name_to_car = {row["name"]: row for row in reference_cars}
    key_to_names: dict[str, list[str]] = defaultdict(list)
    alias_to_name: dict[str, str] = {}

    for row in reference_cars:
        name = row["name"]
        key_to_names[car_match_key(name)].append(name)
        normalized_name = row.get("normalized_name")
        if normalized_name:
            key_to_names[car_match_key(str(normalized_name))].append(name)
        for alias in row.get("aliases") or []:
            alias_key = car_match_key(alias)
            if alias_key:
                alias_to_name[alias_key] = name
                key_to_names[alias_key].append(name)

    key_to_names = {key: sorted(set(names)) for key, names in key_to_names.items() if key}
    collisions = {key: names for key, names in key_to_names.items() if len(names) > 1}
    return {"name_to_car": name_to_car, "key_to_names": key_to_names, "alias_to_name": alias_to_name, "collisions": collisions}


def classify_external_car(imported_name: str, indexes: dict[str, Any], canonical_names: list[str], high_threshold: float, review_threshold: float) -> dict[str, Any]:
    key = car_match_key(imported_name)
    key_to_names = indexes["key_to_names"]
    alias_to_name = indexes["alias_to_name"]

    if imported_name in indexes["name_to_car"]:
        return {"status": "canonical_exact", "match_type": "exact_name", "canonical": imported_name, "score": 1.0, "key": key, "suggestions": []}

    if key in alias_to_name:
        canonical = alias_to_name[key]
        return {"status": "alias_known", "match_type": "reference_alias", "canonical": canonical, "score": 1.0, "key": key, "suggestions": []}

    key_matches = key_to_names.get(key, [])
    if len(key_matches) == 1:
        return {"status": "likely_alias", "match_type": "normalizer_key", "canonical": key_matches[0], "score": 1.0, "key": key, "suggestions": []}
    if len(key_matches) > 1:
        return {
            "status": "ambiguous_key_collision",
            "match_type": "normalizer_key_collision",
            "canonical": None,
            "score": 1.0,
            "key": key,
            "suggestions": [{"canonical": name, "key_score": 1.0, "display_score": display_ratio(imported_name, name)} for name in key_matches],
        }

    suggestions = []
    for canonical in canonical_names:
        ks = key_ratio(imported_name, canonical)
        ds = display_ratio(imported_name, canonical)
        score = max(ks, ds)
        if score >= review_threshold:
            suggestions.append({"canonical": canonical, "key_score": ks, "display_score": ds, "score": score})
    suggestions.sort(key=lambda item: (-item["score"], item["canonical"]))

    if suggestions and suggestions[0]["score"] >= high_threshold:
        return {"status": "fuzzy_high_confidence", "match_type": "fuzzy", "canonical": suggestions[0]["canonical"], "score": suggestions[0]["score"], "key": key, "suggestions": suggestions[:5]}
    if suggestions:
        return {"status": "needs_review", "match_type": "fuzzy_review", "canonical": suggestions[0]["canonical"], "score": suggestions[0]["score"], "key": key, "suggestions": suggestions[:5]}
    return {"status": "new_or_unmapped", "match_type": "none", "canonical": None, "score": None, "key": key, "suggestions": []}


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    con = connect_readonly(args.db)
    try:
        reference_cars = load_reference_cars(con, args.canonical_cars_file)
        external_cars = load_external_cars(con, include_inactive=args.include_inactive_external)
        internal_best_cars = load_internal_best_cars(con)
        import_summary = load_import_issue_summary(con)
    finally:
        con.close()

    indexes = build_canonical_indexes(reference_cars)
    canonical_names = sorted({row["name"] for row in reference_cars})

    analyzed_external = []
    for row in external_cars:
        car = str(row["car"] or "")
        classification = classify_external_car(car, indexes, canonical_names, high_threshold=args.high_threshold, review_threshold=args.review_threshold)
        analyzed_external.append(
            {
                "imported_car": car,
                "imported_car_normalized": row.get("car_normalized"),
                "race_class": row.get("race_class"),
                "row_count": int(row.get("row_count") or 0),
                "track_count": int(row.get("track_count") or 0),
                **classification,
            }
        )

    bucket_members: dict[str, dict[str, Any]] = {}
    for canonical in canonical_names:
        key = car_match_key(canonical)
        bucket_members.setdefault(key, {"canonical_names": set(), "external_names": Counter(), "internal_best_names": Counter()})
        bucket_members[key]["canonical_names"].add(canonical)
    for row in external_cars:
        key = car_match_key(str(row["car"] or ""))
        bucket_members.setdefault(key, {"canonical_names": set(), "external_names": Counter(), "internal_best_names": Counter()})
        bucket_members[key]["external_names"][str(row["car"] or "")] += int(row.get("row_count") or 0)
    for row in internal_best_cars:
        key = car_match_key(str(row["car"] or ""))
        bucket_members.setdefault(key, {"canonical_names": set(), "external_names": Counter(), "internal_best_names": Counter()})
        bucket_members[key]["internal_best_names"][str(row["car"] or "")] += int(row.get("row_count") or 0)

    visible_splits = []
    for key, members in bucket_members.items():
        canonical_set = sorted(members["canonical_names"])
        external_names = dict(members["external_names"])
        internal_names = dict(members["internal_best_names"])
        distinct_names = set(canonical_set) | set(external_names) | set(internal_names)
        if len(distinct_names) > 1 and external_names:
            visible_splits.append({"key": key, "canonical_names": canonical_set, "external_names": external_names, "internal_best_names": internal_names})
    visible_splits.sort(key=lambda item: (-sum(item["external_names"].values()), item["key"]))

    status_counts = Counter(item["status"] for item in analyzed_external)
    return {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "database": str(args.db),
        "scope": {
            "external_records": "active only" if not args.include_inactive_external else "all external rows",
            "canonical_source": "reference_cars table" if reference_cars else str(args.canonical_cars_file or ""),
            "normalizer": "diagnostic car_match_key v1",
            "high_threshold": args.high_threshold,
            "review_threshold": args.review_threshold,
        },
        "counts": {
            "canonical_cars": len(reference_cars),
            "distinct_external_car_rows": len(external_cars),
            "distinct_internal_best_car_rows": len(internal_best_cars),
            "external_status_counts": dict(sorted(status_counts.items())),
            "canonical_key_collisions": len(indexes["collisions"]),
            "visible_split_buckets": len(visible_splits),
        },
        "canonical_key_collisions": [{"key": key, "canonical_names": names} for key, names in sorted(indexes["collisions"].items())],
        "external_cars": analyzed_external,
        "likely_aliases": [item for item in analyzed_external if item["status"] in {"likely_alias", "alias_known", "fuzzy_high_confidence"} and item.get("canonical") and item["canonical"] != item["imported_car"]],
        "needs_review": [item for item in analyzed_external if item["status"] in {"needs_review", "ambiguous_key_collision"}],
        "new_or_unmapped": [item for item in analyzed_external if item["status"] == "new_or_unmapped"],
        "visible_split_buckets": visible_splits[: args.max_visible_splits],
        "recent_imports": import_summary.get("recent_imports", []),
    }


def print_summary(report: dict[str, Any]) -> None:
    counts = report["counts"]
    print("=== Car import diagnostic summary ===")
    print(f"Generated: {report['generated_at']}")
    print(f"Database:  {report['database']}")
    print("")
    print(f"Canonical cars:              {counts['canonical_cars']}")
    print(f"Distinct external car rows:  {counts['distinct_external_car_rows']}")
    print(f"Distinct internal best cars: {counts['distinct_internal_best_car_rows']}")
    print(f"Canonical key collisions:    {counts['canonical_key_collisions']}")
    print(f"Visible split buckets:       {counts['visible_split_buckets']}")
    print("")
    print("External status counts:")
    for key, value in counts["external_status_counts"].items():
        print(f"  {key}: {value}")

    def print_items(title: str, items: list[dict[str, Any]], limit: int = 20) -> None:
        print("")
        print(title)
        if not items:
            print("  none")
            return
        for item in items[:limit]:
            canonical = item.get("canonical") or "-"
            score = item.get("score")
            score_text = "" if score is None else f" score={score}"
            print(f"  {item['imported_car']} [{item.get('race_class') or '-'}] rows={item.get('row_count', 0)} -> {canonical} ({item['status']}/{item['match_type']}{score_text})")
        if len(items) > limit:
            print(f"  ... {len(items) - limit} more")

    print_items("Likely aliases to canonize:", report["likely_aliases"])
    print_items("Needs review:", report["needs_review"])
    print_items("New or unmapped cars:", report["new_or_unmapped"])

    print("")
    print("Top visible split buckets:")
    if not report["visible_split_buckets"]:
        print("  none")
    else:
        for bucket in report["visible_split_buckets"][:10]:
            print(f"  key={bucket['key']}")
            print(f"    canonical: {bucket['canonical_names']}")
            print(f"    external:  {bucket['external_names']}")
            if bucket["internal_best_names"]:
                print(f"    internal:  {bucket['internal_best_names']}")

    if report.get("recent_imports"):
        print("")
        print("Recent external imports:")
        for item in report["recent_imports"]:
            print(f"  active={item['active']} status={item['status']} source={item['source_path']} totals={item['totals']} issues={item['issue_count']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose external-record car-name canonicalization.")
    parser.add_argument("--db", type=Path, default=Path("data/forza.sqlite3"), help="SQLite database path.")
    parser.add_argument("--canonical-cars-file", type=Path, default=None, help="Fallback canonical cars file if reference_cars is empty.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output") / "dev_tools" / "car_import_diagnostic.json",
        help="JSON output path.",
    )
    parser.add_argument("--include-inactive-external", action="store_true", help="Include inactive external_lap_records.")
    parser.add_argument("--high-threshold", type=float, default=0.94, help="Fuzzy score treated as high confidence.")
    parser.add_argument("--review-threshold", type=float, default=0.88, help="Fuzzy score included for review.")
    parser.add_argument("--max-visible-splits", type=int, default=100, help="Max split buckets saved to JSON.")
    args = parser.parse_args(argv)

    try:
        report = analyze(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print_summary(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("")
    print(f"JSON written to: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
