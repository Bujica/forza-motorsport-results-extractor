from __future__ import annotations

from pathlib import Path

from tests._db_entity_source import db_entity_source

ROOT = Path(__file__).resolve().parents[1]


def _class_block(source: str, class_name: str) -> str:
    start = source.index(f"class {class_name}")
    next_class = source.find("\nclass ", start + 1)
    return source[start:] if next_class == -1 else source[start:next_class]


def _create_table_block(sql: str, table_name: str) -> str:
    start = sql.index(f"CREATE TABLE {table_name}")
    end = sql.index(");", start)
    return sql[start:end]


def test_image_file_duplicate_and_file_modified_are_promoted_to_columns() -> None:
    models = db_entity_source(ROOT)
    block = _class_block(models, "ImageFileEntity")
    result_block = _class_block(models, "ExtractionResult")
    repo = (ROOT / "forza" / "db" / "repositories" / "images.py").read_text(encoding="utf-8")
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    source_block = _create_table_block(baseline, "image_files")

    assert "duplicate_of_image_file_id: str | None = Field(" in block
    assert "ForeignKey(\"image_files.id\", ondelete=\"SET NULL\")" in block
    assert "file_modified_at: datetime | None = None" in block
    assert 'Index("idx_image_files_duplicate_of", "duplicate_of_image_file_id")' in block
    assert 'Index("idx_image_files_file_modified_at", "file_modified_at")' in block
    assert 'Index("idx_image_files_hash", "file_hash")' in block
    assert "original_name:" not in block
    assert "original_path:" not in block
    assert "original_source_file:" not in result_block
    assert "original_path:" not in result_block
    assert "original_name" not in repo
    assert "original_path" not in repo
    assert "file_name: str | None = None" in repo

    assert "duplicate_of_image_file_id=duplicate_of_image_file_id" in repo
    assert "existing.duplicate_of_image_file_id = duplicate_of_image_file_id" in repo
    assert "entity.file_modified_at = metadata.file_modified_at" in repo
    assert 'metadata_json["duplicate_of_image_file_id"]' not in repo
    assert 'metadata_json["file_modified_at"]' not in repo
    assert "duplicate_of_image_file_id=entity.duplicate_of_image_file_id" in repo
    assert "file_modified_at=entity.file_modified_at" in repo

    assert "duplicate_of_image_file_id VARCHAR" in source_block
    assert "file_modified_at DATETIME" in source_block
    assert "original_name" not in source_block
    assert "original_path" not in source_block
    assert "FOREIGN KEY(duplicate_of_image_file_id) REFERENCES image_files (id) ON DELETE SET NULL" in source_block
    assert "UNIQUE (file_hash)" not in source_block
    assert "CREATE INDEX idx_image_files_hash ON image_files" in baseline
    assert "CREATE INDEX idx_image_files_duplicate_of ON image_files" in baseline
    assert "CREATE INDEX idx_image_files_file_modified_at ON image_files" in baseline
