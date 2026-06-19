from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_line_loading_helper_is_canonical_domain_export() -> None:
    text_utils = (ROOT / "forza" / "domain" / "text_utils.py").read_text(encoding="utf-8")
    domain_init = (ROOT / "forza" / "domain" / "__init__.py").read_text(encoding="utf-8")

    assert "def load_nonempty_lines(" in text_utils
    assert "load_nonempty_lines" in domain_init


def test_duplicate_line_loading_helpers_are_removed_from_runtime_code() -> None:
    files = {
        "forza/domain/normalizer.py": "load_nonempty_lines(",
    }

    for relative_path, required_token in files.items():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert required_token in source, relative_path

    reference_source = (ROOT / "forza" / "application" / "reference_data_service.py").read_text(encoding="utf-8")
    review_source = (ROOT / "forza" / "gui" / "controllers" / "review_controller.py").read_text(encoding="utf-8")
    assert "load_nonempty_lines(" not in reference_source
    assert "load_nonempty_lines(" not in review_source
    assert "def _load_lines(" not in (ROOT / "forza" / "domain" / "normalizer.py").read_text(encoding="utf-8")
    assert "def _load_lines(" not in (ROOT / "forza" / "gui" / "controllers" / "review_controller.py").read_text(encoding="utf-8")


def test_load_nonempty_lines_runtime_contract(tmp_path: Path) -> None:
    from forza.domain import load_nonempty_lines

    source = tmp_path / "values.txt"
    source.write_text("\n  Alpha  \n\nBeta\n   \nGamma  \n", encoding="utf-8")

    assert load_nonempty_lines(source) == ["Alpha", "Beta", "Gamma"]
    assert load_nonempty_lines(tmp_path / "missing.txt") == []
