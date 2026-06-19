import dataclasses

from forza.config import load_config
from forza.output import generate_pdf
from forza.schemas import ExportLap


def test_generate_pdf_creates_missing_parent_directory(tmp_path):
    cfg = dataclasses.replace(load_config(tmp_path / "missing.ini"), gamertag="Bujica89")
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
    pdf_path = tmp_path / "missing" / "reports" / "forza_bestlaps.pdf"

    used_files = generate_pdf(
        [result],
        pdf_path,
        cfg,
        ["Lime Rock Park Full Circuit"],
    )

    assert pdf_path.exists()
    assert used_files == {"Lime Rock Park Full Circuit - D #1.png"}

