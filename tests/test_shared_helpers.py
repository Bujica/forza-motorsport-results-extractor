from __future__ import annotations

from forza.pipeline.image import find_images
from forza.domain.text_utils import (
    normalize_ascii_compare,
    normalize_whitespace_lower,
    strip_dirty_lap_marker,
)


def test_find_images_returns_supported_files_sorted_by_name(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "b.JPG").write_text("x", encoding="utf-8")
    (tmp_path / "nested" / "A.png").write_text("x", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")

    assert [path.name for path in find_images(tmp_path)] == ["A.png", "b.JPG"]


def test_find_images_missing_root_returns_empty_list(tmp_path) -> None:
    assert find_images(tmp_path / "missing") == []


def test_text_comparison_helpers_preserve_previous_semantics() -> None:
    assert normalize_whitespace_lower("  A   B  ") == "a b"
    assert normalize_ascii_compare("São Paulo") == "sao paulo"
    assert normalize_ascii_compare("A-700", spaces=False) == "a700"
    assert strip_dirty_lap_marker("01:23.456▲") == "01:23.456"
    assert strip_dirty_lap_marker("01:23.456⚠️") == "01:23.456"

