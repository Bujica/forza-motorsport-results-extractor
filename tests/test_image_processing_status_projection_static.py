from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _class_block(source: str, class_name: str) -> str:
    marker = f"class {class_name}:"
    start = source.index(marker)
    next_class = source.find("\n@dataclass", start + len(marker))
    return source[start:] if next_class == -1 else source[start:next_class]


def test_processing_status_is_not_persisted_image_file_domain_field() -> None:
    domain_source = (ROOT / "forza" / "schemas" / "domain.py").read_text(encoding="utf-8")
    entity_source = (ROOT / "forza" / "db" / "entities" / "image.py").read_text(encoding="utf-8")

    image_file_block = _class_block(domain_source, "ImageFile")

    assert "processing_status" not in image_file_block
    assert "ImageProcessingStatus" not in domain_source
    assert "processing_status" not in entity_source


def test_processing_status_is_gui_inventory_projection() -> None:
    types_source = (ROOT / "forza" / "application" / "gui_read" / "types.py").read_text(encoding="utf-8")
    image_reads_source = (ROOT / "forza" / "application" / "gui_read" / "image_reads.py").read_text(encoding="utf-8")

    gui_image_block = _class_block(types_source, "GuiImage")

    assert "processing_status: str" in gui_image_block
    assert "def _to_gui_image(" in image_reads_source
    assert "processing_by_image.get(row.id" in image_reads_source
    assert "_latest_processing_statuses" in image_reads_source
