from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_FLAT_RESULT_METRIC_FIELDS = (
    "model_elapsed_s",
    "model_total_tokens",
    "model_input_tokens",
    "model_output_tokens",
    "model_reasoning_output_tokens",
    "model_tokens_per_second",
    "model_time_to_first_token_seconds",
    "model_load_time_seconds",
)


def _class_block(source: str, class_name: str) -> str:
    start = source.index(f"class {class_name}")
    next_class = source.find("\nclass ", start + 1)
    return source[start:] if next_class == -1 else source[start:next_class]


def test_extraction_result_uses_model_response_stats_not_flat_metric_fields() -> None:
    domain = (ROOT / "forza" / "schemas" / "domain.py").read_text(encoding="utf-8")
    extraction_result = _class_block(domain, "ExtractionResult")

    assert "model_response_stats: ModelResponseStats | None = None" in extraction_result
    for field in _FLAT_RESULT_METRIC_FIELDS:
        assert field not in extraction_result


def test_result_metric_callers_use_model_response_stats() -> None:
    process = (ROOT / "forza" / "pipeline" / "process.py").read_text(encoding="utf-8")
    repository = (ROOT / "forza" / "db" / "repositories" / "model_results.py").read_text(encoding="utf-8")

    assert "backend_output.response_stats" in process
    assert "backend_output.parsed" in process
    assert "_canonical_response_stats" not in process
    assert "_coerce_backend_output" not in process
    assert "result.model_response_stats" in repository

    for source in (process, repository):
        for field in _FLAT_RESULT_METRIC_FIELDS:
            assert f"result.{field}" not in source
