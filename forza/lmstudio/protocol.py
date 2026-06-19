from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..schemas import ModelExtractionAttempt, ModelRequestMetadata, ModelResponseStats


LMSTUDIO_BACKEND_NAME = "lmstudio"


@dataclass(frozen=True)
class ModelExtractionResult:
    """LLM extraction envelope.

    ``parsed`` is the short-key JSON used by the extraction pipeline.
    ``raw_response`` is the exact model text before parse/repair, preserved for
    prompt/model debugging and comparisons.
    ``raw_response_artifact_path`` is an optional registered/debug artifact path. Runtime
    consumers must prefer database evidence over scanning raw-response folders.
    """

    parsed: dict
    raw_response: str
    raw_response_artifact_path: str | None = None
    request_metadata: ModelRequestMetadata | None = None
    response_stats: ModelResponseStats | None = None
    attempts: list[ModelExtractionAttempt] | None = None


@runtime_checkable
class LLMBackend(Protocol):
    """Runtime contract for LLM backends."""

    backend_name: str

    def extract(
        self,
        image_b64: str,
        mime: str,
        semantic_name: str,
        run_id: str,
        file_hash: str,
    ) -> ModelExtractionResult: ...

    def close(self) -> None: ...
