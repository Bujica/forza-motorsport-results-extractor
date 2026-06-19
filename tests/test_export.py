import csv

from forza.output import export_csv
from forza.schemas import ExportLap


def test_export_csv_works_without_pipeline_meta(tmp_path):
    result = ExportLap(
        image_file_id="img-1",
        source_file="Lime Rock Park Full Circuit - D #1.png",
        file_hash="hash",
        lap_index=0,
        semantic_name="Lime Rock Park Full Circuit - D #1.png",
        race_datetime=None,
        race_date=None,
        image_format=None,
        width_px=None,
        height_px=None,
        track="Lime Rock Park Full Circuit",
        race_class="D",
        weather="dry",
        temp_f=76.0,
        temp_c=24.4,
        driver="Bujica89",
        car="Mazda MX-5 '90",
        car_class="D",
        best_lap="00:56.092",
        best_lap_ms=56092,
        dirty=False,
        is_best_lap=True,
    )
    out = tmp_path / "results.csv"

    rows = export_csv([result], out)

    assert rows == 1
    with out.open("r", encoding="utf-8-sig", newline="") as fh:
        exported = list(csv.DictReader(fh))
    assert exported[0]["driver"] == "Bujica89"
    assert "pipeline_version" not in exported[0]
    assert "model" not in exported[0]

