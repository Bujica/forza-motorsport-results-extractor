from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import ParseError as XmlParseError

from sqlmodel import Session

from ..db.repositories import ExternalRecordRepository
from ..domain.car_names import canonicalize_car_name, car_canonical_map
from ..schemas import ExternalLapRecord
from .db_session_provider import DbSessionProvider


DEFAULT_SPREADSHEET = Path("data/external/DataFM.xlsx")
DEFAULT_ALIASES = Path("data/external/track_aliases.json")
DEFAULT_SHEET = "MAIN LEADERBOARD"
REQUIRED_COLUMNS = frozenset({"Track", "Class", "Gamertag", "Vehicle", "Laptime"})
REQUIRED_XLSX_PARTS = frozenset({"xl/workbook.xml", "xl/_rels/workbook.xml.rels"})
MAX_XLSX_ROWS = 100_000
REJECTED_ROW_ISSUE_KINDS = frozenset({"missing_required_fields", "unmapped_track", "invalid_lap"})

log = logging.getLogger("forza")


class ExternalImportError(ValueError):
    """Raised when a external records import file is structurally invalid."""


@dataclass(frozen=True)
class ExternalRecord:
    track: str
    race_class: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int
    source: str = "External"


@dataclass(frozen=True)
class ExternalRecordIssue:
    kind: str
    value: str
    detail: str = ""


@dataclass(frozen=True)
class ExternalImportResult:
    source_path: Path
    total_rows: int
    records: list[ExternalRecord]
    issues: list[ExternalRecordIssue] = field(default_factory=list)

    @property
    def unmapped_tracks(self) -> int:
        return sum(1 for issue in self.issues if issue.kind == "unmapped_track")

    @property
    def invalid_laps(self) -> int:
        return sum(1 for issue in self.issues if issue.kind == "invalid_lap")

    @property
    def missing_required_fields(self) -> int:
        return sum(1 for issue in self.issues if issue.kind == "missing_required_fields")

    @property
    def invalid_aliases(self) -> int:
        return sum(1 for issue in self.issues if issue.kind == "invalid_alias")

    @property
    def rejected_rows(self) -> int:
        return sum(1 for issue in self.issues if issue.kind in REJECTED_ROW_ISSUE_KINDS)

    @property
    def warning_count(self) -> int:
        return len(self.issues) - self.rejected_rows

    @property
    def canonicalized_cars(self) -> int:
        return sum(1 for issue in self.issues if issue.kind == "car_alias_canonicalized")

    @property
    def new_car_names(self) -> list[str]:
        return sorted({issue.value for issue in self.issues if issue.kind == "new_car"})

    @property
    def new_cars(self) -> int:
        return len(self.new_car_names)

    @property
    def ambiguous_cars(self) -> int:
        return len({issue.value for issue in self.issues if issue.kind == "ambiguous_car"})

class ExternalRecordReadService:
    """Owns database-backed external record reads."""

    def __init__(self, session_provider: DbSessionProvider, database_file: Path):
        self._session_provider = session_provider
        self.database_file = Path(database_file)

    def list_external_records(self) -> list[ExternalLapRecord]:
        if not self.database_file.exists():
            return []
        with Session(self._session_provider.engine_for_db()) as session:
            return ExternalRecordRepository(session).active_records()



class ExternalRecordPersistenceService:
    """Owns database-backed external record snapshot replacement."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def replace_external_records(
        self,
        records: list[ExternalLapRecord],
        *,
        source_path: Path | str,
        source_hash: str | None = None,
        total_rows: int | None = None,
        issues: list[dict] | None = None,
        rejected_rows: int | None = None,
    ) -> int:
        with Session(self._session_provider.engine_for_db()) as session:
            repo = ExternalRecordRepository(session)
            repo.replace_active_snapshot(
                records,
                source_path=str(source_path),
                source_hash=source_hash,
                total_rows=total_rows,
                issues=issues,
                rejected_rows=rejected_rows,
            )
            session.commit()
            return len(records)

class ExternalRecordService:
    """Import explicit community-record CSV/XLSX files into SQL snapshots."""

    def __init__(
        self,
        *,
        aliases_file: Path | None = None,
    ) -> None:
        self.aliases_file = Path(aliases_file) if aliases_file is not None else DEFAULT_ALIASES

    def import_spreadsheet(
        self,
        source_path: Path | None = None,
        *,
        sheet_name: str = DEFAULT_SHEET,
        known_tracks: list[str] | tuple[str, ...] | set[str] | None = None,
        canonical_cars: list[str] | tuple[str, ...] | None = None,
    ) -> ExternalImportResult:
        source = Path(source_path) if source_path is not None else DEFAULT_SPREADSHEET
        if source.suffix.lower() == ".csv":
            raw_rows = _read_csv_rows(source)
        else:
            raw_rows = _read_xlsx_rows(source, sheet_name=sheet_name)

        known_track_set = {str(track).strip() for track in (known_tracks or ()) if str(track).strip()}
        aliases, alias_issues = _load_aliases(self.aliases_file, known_tracks=known_track_set)
        canonical_by_key, car_collisions = car_canonical_map(tuple(canonical_cars or ()))
        best_by_group: dict[tuple[str, str], ExternalRecord] = {}
        issues: list[ExternalRecordIssue] = list(alias_issues)
        seen_car_issues: set[tuple[str, str, str]] = set()

        def append_car_issue(kind: str, value: str, detail: str) -> None:
            key = (kind, value, detail)
            if key in seen_car_issues:
                return
            seen_car_issues.add(key)
            issues.append(ExternalRecordIssue(kind, value, detail))

        for row_number, row in enumerate(raw_rows, start=1):
            raw_track = str(row.get("Track", "")).strip()
            race_class = _normalize_class(str(row.get("Class", "")))
            driver = str(row.get("Gamertag", "")).strip()
            raw_car = str(row.get("Vehicle", "")).strip()
            raw_lap = str(row.get("Laptime", "")).strip()
            missing = [
                label
                for label, value in (
                    ("Track", raw_track),
                    ("Class", race_class),
                    ("Gamertag", driver),
                    ("Vehicle", raw_car),
                    ("Laptime", raw_lap),
                )
                if not value or value == "Unknown"
            ]
            if missing:
                issues.append(
                    ExternalRecordIssue(
                        "missing_required_fields",
                        f"row {row_number}",
                        ", ".join(missing),
                    )
                )
                continue

            track = aliases.get(raw_track)
            if track is None and raw_track in known_track_set:
                track = raw_track
            if track is None:
                issues.append(ExternalRecordIssue("unmapped_track", raw_track, f"row {row_number}"))
                continue

            try:
                best_lap = _normalize_lap(raw_lap)
                best_lap_ms = int(round(_lap_to_seconds(best_lap) * 1000))
            except ValueError as exc:
                issues.append(ExternalRecordIssue("invalid_lap", raw_lap, f"row {row_number}: {exc}"))
                continue

            car_result = canonicalize_car_name(raw_car, canonical_by_key, car_collisions)
            car = car_result.canonical
            if car_result.status == "car_alias_canonicalized":
                append_car_issue("car_alias_canonicalized", raw_car, car)
            elif car_result.status == "new_car":
                append_car_issue("new_car", raw_car, f"row {row_number}")
            elif car_result.status == "ambiguous_car":
                append_car_issue("ambiguous_car", raw_car, f"row {row_number}: {car_result.key}")

            record = ExternalRecord(
                track=track,
                race_class=race_class,
                driver=driver,
                car=car,
                best_lap=best_lap,
                best_lap_ms=best_lap_ms,
            )
            key = (track, race_class)
            current = best_by_group.get(key)
            if current is None or record.best_lap_ms < current.best_lap_ms:
                best_by_group[key] = record

        records = sorted(best_by_group.values(), key=lambda r: (r.track.lower(), r.race_class, r.best_lap_ms))
        return ExternalImportResult(
            source_path=source,
            total_rows=len(raw_rows),
            records=records,
            issues=issues,
        )

    def import_to_db(
        self,
        database,
        source_path: Path | None = None,
        *,
        sheet_name: str = DEFAULT_SHEET,
    ) -> ExternalImportResult:
        """Import spreadsheet/CSV and atomically activate the normalized DB snapshot."""
        result = self.import_spreadsheet(
            source_path,
            sheet_name=sheet_name,
            known_tracks=database.list_reference_tracks(),
            canonical_cars=database.list_reference_cars(),
        )
        if result.new_car_names:
            database.seed_references(tracks=[], cars=result.new_car_names)
        from ..schemas import ExternalLapRecord

        database.replace_external_records(
            [
                ExternalLapRecord(
                    track=record.track,
                    race_class=record.race_class,
                    driver=record.driver,
                    car=record.car,
                    best_lap=record.best_lap,
                    best_lap_ms=record.best_lap_ms,
                    source=record.source,
                )
                for record in result.records
            ],
            source_path=result.source_path,
            source_hash=_file_sha256(result.source_path),
            total_rows=result.total_rows,
            issues=[issue.__dict__ for issue in result.issues],
            rejected_rows=result.rejected_rows,
        )
        return result


def _file_sha256(path: Path) -> str | None:
    try:
        sha = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
        return sha.hexdigest()
    except OSError:
        return None


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ExternalImportError(f"CSV has no header row: {path}")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ExternalImportError(f"CSV missing required columns: {sorted(missing)}")
        return list(reader)


def _read_xlsx_rows(path: Path, *, sheet_name: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        with zipfile.ZipFile(path) as archive:
            _validate_xlsx_parts(archive, path)
            shared_strings = _shared_strings(archive)
            sheet_path = _sheet_path(archive, sheet_name)
            try:
                root = ET.fromstring(archive.read(sheet_path))
            except KeyError as exc:
                raise ExternalImportError(f"Worksheet part missing from XLSX: {sheet_path}") from exc
            except XmlParseError as exc:
                raise ExternalImportError(f"Worksheet XML is malformed: {sheet_path}: {exc}") from exc
            rows = [
                _xlsx_row_values(row, shared_strings)
                for row in root.findall(f".//{{{_NS_MAIN}}}sheetData/{{{_NS_MAIN}}}row")
            ]
    except zipfile.BadZipFile as exc:
        raise ExternalImportError(f"Not a valid XLSX/ZIP file: {path}") from exc
    if len(rows) > MAX_XLSX_ROWS:
        raise ExternalImportError(f"XLSX row limit exceeded: {len(rows)} > {MAX_XLSX_ROWS}")

    headers: list[str] | None = None
    result: list[dict[str, str]] = []
    for values in rows:
        if headers is None:
            if REQUIRED_COLUMNS.issubset(set(values)):
                headers = values
            continue
        mapped = {headers[index]: value for index, value in enumerate(values) if index < len(headers)}
        if any(mapped.get(key) for key in REQUIRED_COLUMNS):
            result.append(mapped)
    if headers is None:
        raise ExternalImportError(f"Worksheet '{sheet_name}' is missing required headers: {sorted(REQUIRED_COLUMNS)}")
    return result


_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _validate_xlsx_parts(archive: zipfile.ZipFile, path: Path) -> None:
    names = set(archive.namelist())
    missing = REQUIRED_XLSX_PARTS - names
    if missing:
        raise ExternalImportError(f"XLSX missing required part(s) in {path}: {sorted(missing)}")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except XmlParseError as exc:
        raise ExternalImportError(f"sharedStrings.xml is malformed: {exc}") from exc
    strings: list[str] = []
    for item in root.findall(f"{{{_NS_MAIN}}}si"):
        pieces = [node.text or "" for node in item.iter(f"{{{_NS_MAIN}}}t")]
        strings.append("".join(pieces))
    return strings


def _sheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise ExternalImportError(f"XLSX missing required workbook part: {exc}") from exc
    except XmlParseError as exc:
        raise ExternalImportError(f"Workbook XML is malformed: {exc}") from exc
    targets = {}
    for rel in rels.findall(f"{{{_NS_PKG_REL}}}Relationship"):
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            targets[rel_id] = f"xl/{target}"
    for sheet in workbook.findall(f".//{{{_NS_MAIN}}}sheet"):
        if sheet.attrib.get("name") == sheet_name:
            rel_id = sheet.attrib.get(f"{{{_NS_REL}}}id")
            if not rel_id or rel_id not in targets:
                raise ExternalImportError(f"Worksheet relationship missing for: {sheet_name}")
            return targets[rel_id]
    raise ExternalImportError(f"Worksheet not found: {sheet_name}")


def _xlsx_row_values(row: ET.Element, shared_strings: list[str]) -> list[str]:
    values: list[str] = []
    for cell in row.findall(f"{{{_NS_MAIN}}}c"):
        index = _column_index(cell.attrib.get("r", "A1"))
        while len(values) <= index:
            values.append("")
        raw = cell.find(f"{{{_NS_MAIN}}}v")
        if raw is None:
            value = ""
        elif cell.attrib.get("t") == "s":
            try:
                value = shared_strings[int(raw.text or 0)]
            except (ValueError, IndexError) as exc:
                raise ExternalImportError(f"Invalid shared string reference: {raw.text!r}") from exc
        else:
            value = raw.text or ""
        values[index] = value
    return values


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + ord(char.upper()) - 64
    return max(0, value - 1)


def _load_aliases(
    path: Path,
    *,
    known_tracks: set[str] | None = None,
) -> tuple[dict[str, str], list[ExternalRecordIssue]]:
    issues: list[ExternalRecordIssue] = []
    if not path.exists():
        log.info("[external-records] Track aliases file not found: %s", path)
        return {}, issues
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warning("[external-records] Invalid alias JSON in %s: %s", path, exc)
        return {}, issues
    if not isinstance(payload, dict):
        log.warning("[external-records] Expected alias JSON object in %s", path)
        return {}, issues
    return _validated_aliases(payload, known_tracks)


def _validated_aliases(payload: dict, known_tracks: set[str] | None) -> tuple[dict[str, str], list[ExternalRecordIssue]]:
    aliases: dict[str, str] = {}
    issues: list[ExternalRecordIssue] = []
    for key, value in payload.items():
        source = str(key).strip()
        target = str(value).strip()
        if not source or not target:
            issues.append(ExternalRecordIssue("invalid_alias", source or "<blank>", "blank source or target"))
            continue
        if known_tracks is not None and target not in known_tracks:
            log.warning("[external-records] Alias target not found in tracks reference: %s -> %s", source, target)
            issues.append(ExternalRecordIssue("invalid_alias", source, target))
            continue
        aliases[source] = target
    return aliases, issues


def _normalize_class(value: str) -> str:
    value = str(value).strip().upper()
    if not value:
        return "Unknown"
    if value.startswith("TCR"):
        return "TCR"
    return value[0]


def _normalize_lap(raw: str) -> str:
    lap = re.sub(r"[^0-9:.]", "", str(raw).strip())
    if ":" not in lap:
        raise ValueError(f"No colon in lap time: {raw!r}")
    mins, rest = lap.split(":", 1)
    return f"{int(mins):02d}:{float(rest):06.3f}"


def _lap_to_seconds(lap: str) -> float:
    mins, rest = lap.split(":")
    return int(mins) * 60 + float(rest)
