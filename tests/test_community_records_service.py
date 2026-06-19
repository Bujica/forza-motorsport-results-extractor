from __future__ import annotations

from forza.application.external_record_service import ExternalRecordService


def test_external_record_import_returns_best_record_per_track_class_without_json_cache(tmp_path):
    aliases = tmp_path / "aliases.json"
    aliases.write_text('{"Short Track": "Canonical Track"}', encoding="utf-8")
    source = tmp_path / "records.csv"
    source.write_text(
        "Class,Track,Gamertag,Vehicle,Laptime\n"
        "A700,Short Track,Driver One,Car One,1:02.500\n"
        "A700,Short Track,Driver Two,Car Two,1:01.250\n"
        "TCR,Missing,Driver Three,Car Three,1:03.000\n",
        encoding="utf-8",
    )

    result = ExternalRecordService(aliases_file=aliases).import_spreadsheet(
        source,
        known_tracks={"Canonical Track"},
    )

    assert result.total_rows == 3
    assert len(result.records) == 1
    assert result.records[0].track == "Canonical Track"
    assert result.records[0].race_class == "A"
    assert result.records[0].driver == "Driver Two"
    assert result.records[0].best_lap_ms == 61250
    assert result.unmapped_tracks == 1
    assert not (tmp_path / ("records" + ".json")).exists()


def test_external_record_import_canonicalizes_car_aliases_without_json_cache(tmp_path):
    source = tmp_path / "records.csv"
    source.write_text(
        "Class,Track,Gamertag,Vehicle,Laptime\n"
        "A,Canonical Track,Driver,Elemental Rp1 '19,1:02.500\n"
        "B,Canonical Track,Driver,Mini Cooper '65,1:03.500\n"
        "C,Canonical Track,Driver,Toyota Corolla '74,1:04.500\n"
        "R,Canonical Track,Driver,Mazda Furai,1:05.500\n",
        encoding="utf-8",
    )

    result = ExternalRecordService(
        aliases_file=tmp_path / "track_aliases.json",
    ).import_spreadsheet(
        source,
        known_tracks={"Canonical Track"},
        canonical_cars=(
            "Elemental Rp1 19",
            "MINI Cooper '65",
            "Toyota Corolla74",
        ),
    )

    cars = {record.car for record in result.records}
    assert "Elemental Rp1 19" in cars
    assert "MINI Cooper '65" in cars
    assert "Toyota Corolla74" in cars
    assert "Mazda Furai" in cars
    assert result.canonicalized_cars == 3
    assert result.new_cars == 1
    assert [(issue.kind, issue.value, issue.detail) for issue in result.issues] == [
        ("car_alias_canonicalized", "Elemental Rp1 '19", "Elemental Rp1 19"),
        ("car_alias_canonicalized", "Mini Cooper '65", "MINI Cooper '65"),
        ("car_alias_canonicalized", "Toyota Corolla '74", "Toyota Corolla74"),
        ("new_car", "Mazda Furai", "row 4"),
    ]
    assert not (tmp_path / ("records" + ".json")).exists()


def test_external_record_import_does_not_canonicalize_ambiguous_car_key(tmp_path):
    source = tmp_path / "records.csv"
    source.write_text(
        "Class,Track,Gamertag,Vehicle,Laptime\n"
        "A,Canonical Track,Driver,Car '19,1:02.500\n",
        encoding="utf-8",
    )

    result = ExternalRecordService(
        aliases_file=tmp_path / "track_aliases.json",
    ).import_spreadsheet(
        source,
        known_tracks={"Canonical Track"},
        canonical_cars=("Car 19", "Car '19"),
    )

    assert result.records[0].car == "Car '19"
    assert result.ambiguous_cars == 1
    assert result.issues[0].kind == "ambiguous_car"
    assert not (tmp_path / ("records" + ".json")).exists()


def test_external_record_service_loads_json_aliases(tmp_path):
    aliases = tmp_path / "aliases.json"
    aliases.write_text('{"Short Track": "Canonical Track"}', encoding="utf-8")
    source = tmp_path / "records.csv"
    source.write_text(
        "Class,Track,Gamertag,Vehicle,Laptime\n"
        "A700,Short Track,Driver One,Car One,1:02.500\n",
        encoding="utf-8",
    )

    result = ExternalRecordService(
        aliases_file=aliases,
    ).import_spreadsheet(
        source,
        known_tracks={"Canonical Track"},
    )

    assert len(result.records) == 1
    assert result.records[0].track == "Canonical Track"
    assert not (tmp_path / ("records" + ".json")).exists()

def test_external_record_import_separates_rejected_rows_from_warnings(tmp_path):
    source = tmp_path / "records.csv"
    source.write_text(
        "Class,Track,Gamertag,Vehicle,Laptime\n"
        "A,Canonical Track,Driver One,Known Car,1:02.500\n"
        "B,Canonical Track,Driver Two,New Car,1:03.500\n"
        "C,Missing Track,Driver Three,Known Car,1:04.500\n"
        "D,Canonical Track,,Known Car,1:05.500\n"
        "E,Canonical Track,Driver Five,Known Car,bad\n",
        encoding="utf-8",
    )

    result = ExternalRecordService(
        aliases_file=tmp_path / "track_aliases.json",
    ).import_spreadsheet(
        source,
        known_tracks={"Canonical Track"},
        canonical_cars=("Known Car",),
    )

    assert result.total_rows == 5
    assert len(result.records) == 2
    assert result.rejected_rows == 3
    assert result.warning_count == 1
    assert result.new_cars == 1
    assert result.unmapped_tracks == 1
    assert result.missing_required_fields == 1
    assert result.invalid_laps == 1
