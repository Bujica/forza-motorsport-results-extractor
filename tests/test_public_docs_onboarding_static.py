
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_readme_declares_public_product_scope() -> None:
    text = _read("README.md")
    assert "Forza Motorsport Results Extractor" in text
    assert "Forza Motorsport, 2023 release" in text
    assert "post-race Results screen" in text
    assert "Forza Horizon" in text
    assert "not affiliated" in text.lower()
    assert "QUICK_GUIDE.md" in text


def test_beta_guide_documents_first_run_and_bundle_root() -> None:
    text = _read("README_BETA.md")
    for token in (
        "fmre-cli.exe maintenance db-upgrade",
        "fmre-cli.exe maintenance db-doctor --json",
        r"data\input",
        "bundle-local input folder",
        "LM Studio",
        "Model weights",
        "build_info.json",
        "tools/",
        "scripts/",
        "tests/",
        ".git/",
        ".github/",
        "DataFM.xlsx",
    ):
        assert token in text


def test_quick_guide_has_source_and_beta_commands() -> None:
    text = _read("QUICK_GUIDE.md")
    assert "python -m forza maintenance db-upgrade" in text
    assert "fmre-cli.exe maintenance db-upgrade" in text
    assert "Forza Motorsport, 2023 release" in text
    assert "post-race Results screen" in text


def test_public_roadmap_has_beta_boundaries() -> None:
    text = _read("docs/roadmap.md")
    assert "public beta" in text
    assert "Forza Horizon support" in text
    assert "Bundling model weights" in text
    assert "Cloud OCR" in text


def test_public_docs_do_not_use_old_product_name() -> None:
    public_docs = [
        "README.md",
        "README_BETA.md",
        "QUICK_GUIDE.md",
        "docs/roadmap.md",
        "CHANGELOG.md",
    ]
    for relative in public_docs:
        text = _read(relative)
        assert "Forza Motorsport Screenshot Extractor" not in text
        assert "ForzaExtractor-0.20.0-beta.1" not in text
