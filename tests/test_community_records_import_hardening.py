from __future__ import annotations

import zipfile

import pytest

from forza.application.external_record_service import (
    ExternalImportError,
    ExternalRecordService,
    _read_xlsx_rows,
)


def _service(tmp_path) -> ExternalRecordService:
    return ExternalRecordService(aliases_file=tmp_path / "track_aliases.json")


def _import(service: ExternalRecordService, source_path):
    return service.import_spreadsheet(source_path, known_tracks={"Known Track"})

    result = _import(_service(tmp_path), csv_path)

    assert len(result.records) == 1
    assert result.missing_required_fields == 1
    assert result.issues[-1].kind == "missing_required_fields"
    assert result.issues[-1].value == "row 2"
    assert result.issues[-1].detail == "Gamertag"


def test_import_reports_invalid_alias_target_as_issue(tmp_path) -> None:
    csv_path = tmp_path / "records.csv"
    csv_path.write_text(
        "Track,Class,Gamertag,Vehicle,Laptime\n"
        "Alias Track,A,Driver,Car,01:30.000\n",
        encoding="utf-8",
    )
    (tmp_path / "track_aliases.json").write_text('{"Alias Track": "Missing Canonical Track"}', encoding="utf-8")

    result = _import(_service(tmp_path), csv_path)

    assert result.records == []
    assert result.invalid_aliases == 1
    assert [(issue.kind, issue.value, issue.detail) for issue in result.issues] == [
        ("invalid_alias", "Alias Track", "Missing Canonical Track"),
        ("unmapped_track", "Alias Track", "row 1"),
    ]
