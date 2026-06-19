from __future__ import annotations

from pathlib import Path

from forza.application.gui_read.image_reads import GuiImageReadQueries
from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]


def test_gui_image_reads_move_image_inventory_methods_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    image_source = (ROOT / "forza" / "application" / "gui_read" / "image_reads.py").read_text(encoding="utf-8")

    assert "self._image_reads = GuiImageReadQueries(self._session_provider)" in service_source
    assert "return self._image_reads.list_images(" in service_source
    assert "return self._image_reads.image_filter_values(" in service_source
    assert "return self._image_reads.get_image(image_file_id)" in service_source
    assert "list_image_flags" not in service_source

    moved_method_tokens = (
        "ImageFileRepository(session).to_schema(entity)",
        "select(ImageFileEntity.id)",
        "_apply_duplicate_group_filter(",
        "LapRecordEntity.image_file_id.in_(track_image_file_ids)",
    )
    for token in moved_method_tokens:
        assert token not in service_source
        assert token in image_source

    assert "def _image_ids_query(" not in service_source
    assert "def _image_ids_query(" in image_source
    assert "flag_subq =" not in image_source
    assert "flag: str | None = None" not in service_source
    assert "flag: str | None = None" not in image_source
    assert "inventory_filter: str | None = None" in service_source
    assert "inventory_filter: str | None = None" in image_source
    assert "def list_image_flags(" not in image_source
    assert "class GuiImageFlag" not in image_source


def test_images_run_filter_uses_run_inputs_contract() -> None:
    source = (ROOT / "forza" / "application" / "gui_read" / "image_reads.py").read_text(encoding="utf-8")

    assert "RunInputEntity" in source
    assert ".join(RunInputEntity, RunInputEntity.run_id == ExtractionRunEntity.id)" in source
    assert "RunInputEntity.run_id == run_id" in source
    assert "LapRecordEntity.run_id == run_id" not in source


def test_gui_image_reads_keep_public_service_facade_methods() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def list_images(" in source
    assert "def image_filter_values(" in source
    assert "def get_image(" in source
    assert "def list_image_flags(" not in source


def test_gui_image_read_queries_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))
    queries = GuiImageReadQueries(provider)

    assert queries.list_images() == []
    assert queries.image_filter_values() == ([], [])
    assert queries.get_image("missing") is None
    assert not hasattr(queries, "list_image_flags")
