from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_images_first_contract_documents_physical_file_identity() -> None:
    images = _read("docs/contracts/images_and_files.md")
    database = _read("docs/contracts/database.md")
    core_tables = _read("docs/architecture/database/02-5-core-tables/01-5-1-extraction-runs.md")

    combined = "\n".join((images, database, core_tables))

    assert "`image_files.id` is the stable identity of one observed physical file" in images
    assert "`image_files` stores one observed physical file per row" in database
    assert "CREATE TABLE image_files" in core_tables
    assert "file_hash             TEXT NOT NULL," in core_tables
    assert "file_hash             TEXT NOT NULL UNIQUE" not in core_tables
    assert "Duplicate" not in images or "without collapsing into one row" in images
    assert "stable content identity" not in combined


def test_images_first_contract_documents_current_name_and_delete_semantics() -> None:
    images = _read("docs/contracts/images_and_files.md")
    developer = _read("docs/developer/guide/04-11-images-screen-query-contract.md")

    assert "`image_files.current_name` is the operational display/source name" in images
    assert "`semantic_name` is a suggested/presentation filename" in images
    assert "`missing` means the file disappeared outside an explicit app deletion action" in images
    assert "There is no persistent `deleted` file status" in images
    assert "removes the related image database records" in developer
    assert "file status becomes `deleted`" not in developer
    assert "file status becomes `missing`" not in developer
