from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _class_block(source: str, class_name: str) -> str:
    start = source.index(f"class {class_name}")
    next_class = source.find("\nclass ", start + 1)
    return source[start:] if next_class == -1 else source[start:next_class]


def test_extraction_run_domain_uses_canonical_prompt_and_error_names() -> None:
    domain = (ROOT / "forza" / "schemas" / "domain.py").read_text(encoding="utf-8")
    extraction_run = _class_block(domain, "ExtractionRun")

    assert '    prompt_name: str = ""' in extraction_run
    assert "    operational_error_message: str | None = None" in extraction_run
    legacy_prompt_field = "prompt" + "_version"
    assert f"    {legacy_prompt_field}:" not in extraction_run
    assert "    error_message:" not in extraction_run
