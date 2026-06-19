from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_model_extraction_result_has_no_flat_metric_fields() -> None:
    protocol = (ROOT / "forza" / "lmstudio" / "protocol.py").read_text(encoding="utf-8")
    start = protocol.index("class ModelExtractionResult:")
    end = protocol.index("\n\n@runtime_checkable", start)
    model_result_block = protocol[start:end]

    forbidden_fields = (
        "    elapsed_s:",
        "    tokens:",
        "    input_tokens:",
        "    output_tokens:",
        "    reasoning_output_tokens:",
        "    tokens_per_second:",
        "    time_to_first_token_seconds:",
        "    model_load_time_seconds:",
    )
    for token in forbidden_fields:
        assert token not in model_result_block

    assert "response_stats: ModelResponseStats | None = None" in model_result_block



def test_lmstudio_backend_contract_lives_in_protocol_module() -> None:
    backend = (ROOT / "forza" / "lmstudio" / "backend.py").read_text(encoding="utf-8")
    protocol = (ROOT / "forza" / "lmstudio" / "protocol.py").read_text(encoding="utf-8")
    package_init = (ROOT / "forza" / "lmstudio" / "__init__.py").read_text(encoding="utf-8")

    assert "class ModelExtractionResult:" not in backend
    assert "class LLMBackend(Protocol):" not in backend
    assert "from .protocol import LLMBackend, LMSTUDIO_BACKEND_NAME, ModelExtractionResult" in backend
    assert 'LMSTUDIO_BACKEND_NAME = "lmstudio"' in protocol
    assert "class ModelExtractionResult:" in protocol
    assert "class LLMBackend(Protocol):" in protocol
    assert "from .protocol import LLMBackend, LMSTUDIO_BACKEND_NAME, ModelExtractionResult" in package_init

def test_process_image_requires_model_extraction_result_envelope() -> None:
    source = (ROOT / "forza" / "pipeline" / "process.py").read_text(encoding="utf-8")

    assert "ModelExtractionResult | dict" not in source
    assert "legacy dict-only" not in source
    assert "def _coerce_backend_output" not in source
    assert "def _canonical_response_stats" not in source
    assert "if not isinstance(backend_output, ModelExtractionResult):" in source
    assert "LLMBackend.extract() must return ModelExtractionResult" in source


def test_process_image_uses_ms_lap_parser_and_backend_constant() -> None:
    source = (ROOT / "forza" / "pipeline" / "process.py").read_text(encoding="utf-8")

    assert "parse_lap_time_ms" in source
    assert "parse_lap_time" + "(" not in source
    assert "int(round(lap_sec * 1000))" not in source
    assert 'model_backend="lmstudio"' not in source
    assert "model_backend=LMSTUDIO_BACKEND_NAME" in source


def test_review_identity_does_not_parse_lap_time_for_identity() -> None:
    source = (ROOT / "forza" / "db" / "review_identity.py").read_text(encoding="utf-8")

    assert "parse_lap_time_ms" not in source
    assert "parse_lap_time" + "(" not in source
    assert "int(round(seconds * 1000))" not in source
