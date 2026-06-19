from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, Callable, ClassVar

from json_repair import repair_json
import requests

from ..db.evidence import canonical_request_hash
from ..domain.lap import parse_lap_time_ms
from ..exceptions import ExtractionError, ParseError
from ..pipeline.model_response import parse_and_validate_response
from ..prompts import get_system_prompt
from ..schemas import ModelExtractionAttempt, ModelRequestMetadata, ModelResponseStats
from .load_config import desired_load_config, instance_load_config, load_config_compatible, normalized_load_config
from .protocol import LLMBackend, LMSTUDIO_BACKEND_NAME, ModelExtractionResult


log = logging.getLogger("forza")

_RUNTIME_TRANSIENT_STATUS = {409, 423, 429, 500, 502, 503, 504}
_RUNTIME_MAX_ATTEMPTS = 5
_MODEL_LOCKS: dict[tuple[str, str], Lock] = {}
_MODEL_LOCKS_GUARD = Lock()
class ExtractionAttemptsError(ExtractionError):
    """Extraction failure that still carries persisted attempt metadata."""

    def __init__(self, message: str, attempts: list[ModelExtractionAttempt]):
        super().__init__(message)
        self.attempts = attempts


class LMStudioRuntimeError(ExtractionError):
    """Operational LM Studio runtime failure before image extraction."""


def _parse_or_repair_response(content: str) -> tuple[dict | None, str | None]:
    """Parse a model response, applying one deterministic json_repair pass."""
    parse_error = "Unknown parse error"
    try:
        return parse_and_validate_response(content), None
    except (json.JSONDecodeError, ParseError) as exc:
        parse_error = str(exc)
        log.debug("[extractor] strict parse failed: %s", exc)

    try:
        repaired = repair_json(content, return_objects=False)
        return parse_and_validate_response(repaired), None
    except Exception as repair_exc:
        log.debug("[extractor] json_repair parse failed: %s", repair_exc)
        return None, str(repair_exc) or parse_error


def _semantic_retry_issues(parsed: dict) -> list[str]:
    """Return issues worth a model retry without treating partial lists as bad."""
    issues: list[str] = []
    if not str(parsed.get("t") or "").strip():
        issues.append("track_empty")
    entries = parsed.get("e")
    if not isinstance(entries, list) or not entries:
        issues.append("entries_empty")
        return issues
    lap_values = [entry.get("bl") for entry in entries if isinstance(entry, dict)]
    if lap_values and all(parse_lap_time_ms(value) is None for value in lap_values):
        issues.append("all_best_laps_null")
    return issues


def _retry_user_text(reason: str, detail: str | None = None) -> str:
    base = "Extract all lap results from this image."
    if reason == "json_retry":
        return (
            base
            + " Previous response was not valid JSON for the required schema. "
            + "Return only one minified JSON object with no markdown or commentary."
        )
    if reason == "semantic_retry":
        suffix = f" Detected issue: {detail}." if detail else ""
        return (
            base
            + suffix
            + " Re-read the visible EVENT RESULTS table, keep partial driver lists if the screenshot is partial, "
            + "but do not return an empty entry list or all null best laps when lap times are visible."
        )
    return base


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None



@dataclass
class LMStudioNativeBackend:
    backend_name: ClassVar[str] = LMSTUDIO_BACKEND_NAME
    url: str
    model: str
    max_tokens: int
    temperature: float
    timeout_connect: int
    timeout_read: int
    max_retries: int
    system_prompt: str
    context_length: int = 5000
    reasoning_mode: str | None = "off"
    eval_batch_size: int | None = 1024
    physical_batch_size: int | None = None
    flash_attention: bool = True
    offload_kv_cache_to_gpu: bool = True
    performance_tps_floor: float = 20.0
    performance_reload_elapsed_s: float = 45.0
    performance_reload_streak: int = 3
    _session: requests.Session | None = None
    _instance_id: str | None = None
    _load_config: dict[str, Any] | None = None
    _slow_streak: int = 0
    _reload_before_next: bool = False
    _on_attempt: Callable[[ModelExtractionAttempt], None] | None = None
    _on_runtime_snapshot: Callable[[dict[str, Any]], str] | None = None
    _runtime_snapshot_id: str | None = None
    _prompt_snapshot_id: str | None = None
    _source_file_hash: str | None = None
    _request_metadata: ModelRequestMetadata | None = None
    _runtime_signature: str | None = None

    def __post_init__(self) -> None:
        self._session = requests.Session()

    @property
    def api_base(self) -> str:
        return _lmstudio_api_base(self.url)

    @property
    def chat_url(self) -> str:
        return f"{self.api_base}/chat"

    def __enter__(self) -> "LMStudioNativeBackend":
        self._ensure_loaded()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None

    def configure_persistence(
        self,
        *,
        on_attempt: Callable[[ModelExtractionAttempt], None] | None,
        on_runtime_snapshot: Callable[[dict[str, Any]], str] | None,
        runtime_snapshot_id: str | None,
        prompt_snapshot_id: str | None,
    ) -> None:
        self._on_attempt = on_attempt
        self._on_runtime_snapshot = on_runtime_snapshot
        if self._runtime_snapshot_id is None:
            self._runtime_snapshot_id = runtime_snapshot_id
        self._prompt_snapshot_id = prompt_snapshot_id

    def set_request_context(self, metadata: ModelRequestMetadata) -> None:
        self._request_metadata = metadata

    def extract(
        self,
        image_b64: str,
        mime: str,
        semantic_name: str,
        run_id: str,
        file_hash: str,
    ) -> ModelExtractionResult:
        self._source_file_hash = file_hash
        if self._reload_before_next:
            log.info("[lmstudio] Reloading model before next image after performance degradation")
            self._reload_model()
            self._reload_before_next = False
            self._slow_streak = 0
        self._ensure_loaded()

        attempts: list[ModelExtractionAttempt] = []
        last_exc: Exception | None = None
        next_reason = "initial"
        next_detail: str | None = None

        for attempt_no in range(1, self.max_retries + 1):
            user_text = _retry_user_text(next_reason, next_detail)
            payload = {
                "model": self._instance_id or self.model,
                "system_prompt": self.system_prompt,
                "input": [
                    {"type": "image", "data_url": f"data:{mime};base64,{image_b64}"},
                    {"type": "text", "content": user_text},
                ],
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
                "store": False,
            }
            if self.reasoning_mode:
                payload["reasoning"] = self.reasoning_mode

            started = time.monotonic()
            content = ""
            parsed: dict | None = None
            parse_error: str | None = None
            response_json: dict[str, Any] | None = None
            stats: dict[str, Any] = {}
            http_status: int | None = None
            elapsed = 0.0
            try:
                with _model_lock(self.api_base, self.model):
                    if self._session is None:
                        raise LMStudioRuntimeError("LM Studio session is closed")
                    response = self._session.post(
                        self.chat_url,
                        json=payload,
                        timeout=(self.timeout_connect, self.timeout_read),
                    )
                http_status = response.status_code
                response.raise_for_status()
                response_json = response.json()
                elapsed = time.monotonic() - started
                content = _lmstudio_output_text(response_json)
                stats = response_json.get("stats", {}) or {}
            except requests.RequestException as exc:
                elapsed = time.monotonic() - started
                last_exc = exc
                attempt = self._attempt_record(
                    attempt_no,
                    next_reason,
                    status="error",
                    accepted=False,
                    rejected_reason="transport_error",
                    duration_ms=int(elapsed * 1000),
                    http_status=http_status,
                    parse_error=str(exc),
                    error_code="transport_error",
                    error_message=str(exc),
                    retry_instruction_text=user_text,
                    request_payload=payload,
                    raw_response=content or None,
                    stats=stats,
                )
                attempts.append(attempt)
                self._notify_attempt(attempt)
                if attempt_no < self.max_retries:
                    self._reload_model()
                    next_reason = "transport_retry"
                    next_detail = str(exc)
                    continue
                break

            parsed, parse_error = _parse_or_repair_response(content)
            if parsed is None:
                last_exc = ParseError(parse_error or "Unknown parse error")
                attempt = self._attempt_record(
                    attempt_no,
                    next_reason,
                    status="error",
                    accepted=False,
                    rejected_reason="parse_error",
                    duration_ms=int(elapsed * 1000),
                    http_status=http_status,
                    parse_error=parse_error,
                    error_code="parse_error",
                    error_message=parse_error,
                    retry_instruction_text=user_text,
                    request_payload=payload,
                    raw_response=content,
                    stats=stats,
                    response_json=response_json,
                )
                attempts.append(attempt)
                self._notify_attempt(attempt)
                if attempt_no < self.max_retries:
                    next_reason = "json_retry"
                    next_detail = parse_error
                    continue
                break

            issues = _semantic_retry_issues(parsed)
            if issues and attempt_no < self.max_retries:
                attempt = self._attempt_record(
                    attempt_no,
                    next_reason,
                    status="error",
                    accepted=False,
                    rejected_reason="semantic_validation",
                    duration_ms=int(elapsed * 1000),
                    http_status=http_status,
                    error_code="semantic_validation",
                    error_message=";".join(issues),
                    retry_instruction_text=user_text,
                    request_payload=payload,
                    raw_response=content,
                    parsed_json=parsed,
                    validation_status="retry",
                    validation_issues=issues,
                    stats=stats,
                    response_json=response_json,
                )
                attempts.append(attempt)
                self._notify_attempt(attempt)
                next_reason = "semantic_retry"
                next_detail = ",".join(issues)
                continue

            attempt = self._attempt_record(
                attempt_no,
                next_reason,
                status="ok",
                accepted=True,
                duration_ms=int(elapsed * 1000),
                http_status=http_status,
                retry_instruction_text=user_text,
                request_payload=payload,
                raw_response=content,
                parsed_json=parsed,
                validation_status="accepted" if not issues else "accepted_with_issues",
                validation_issues=issues,
                stats=stats,
                response_json=response_json,
            )
            attempts.append(attempt)
            self._notify_attempt(attempt)
            self._track_performance(elapsed, stats)
            input_tokens = _int_or_none(stats.get("input_tokens"))
            output_tokens = _int_or_none(stats.get("total_output_tokens"))
            reasoning_tokens = _int_or_none(stats.get("reasoning_output_tokens"))
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
            request_config = self._request_config(payload)
            return ModelExtractionResult(
                parsed=parsed,
                raw_response=content,
                raw_response_artifact_path=None,
                request_metadata=ModelRequestMetadata(
                    endpoint_url=self.chat_url,
                    context_length=self.context_length,
                    reasoning_mode=self.reasoning_mode,
                    request_config_json=request_config,
                    model_load_config_json=self._load_config,
                ),
                response_stats=ModelResponseStats(
                    duration_ms=int(elapsed * 1000),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    reasoning_output_tokens=reasoning_tokens,
                    tokens_per_second=_float_or_none(stats.get("tokens_per_second")),
                    time_to_first_token_seconds=_float_or_none(stats.get("time_to_first_token_seconds")),
                    model_load_time_seconds=_float_or_none(stats.get("model_load_time_seconds")),
                    response_stats_json=stats,
                ),
                attempts=attempts,
            )

        raise ExtractionAttemptsError(
            f"All {self.max_retries} adaptive attempt(s) failed for {semantic_name}",
            attempts,
        ) from last_exc

    def _attempt_record(
        self,
        attempt_number: int,
        attempt_reason: str,
        *,
        status: str,
        accepted: bool,
        duration_ms: int,
        request_payload: dict[str, Any],
        rejected_reason: str | None = None,
        http_status: int | None = None,
        raw_response: str | None = None,
        parsed_json: dict | None = None,
        parse_error: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retry_instruction_text: str | None = None,
        validation_status: str | None = None,
        validation_issues: list[str] | None = None,
        stats: dict[str, Any] | None = None,
        response_json: dict[str, Any] | None = None,
    ) -> ModelExtractionAttempt:
        stats = stats or {}
        input_tokens = _int_or_none(stats.get("input_tokens"))
        output_tokens = _int_or_none(stats.get("total_output_tokens"))
        request_metadata = self._request_metadata
        return ModelExtractionAttempt(
            attempt_number=attempt_number,
            attempt_reason=attempt_reason,
            status=status,
            accepted=accepted,
            rejected_reason=rejected_reason,
            runtime_snapshot_id=self._runtime_snapshot_id,
            endpoint_url=self.chat_url,
            model=self.model,
            model_instance_id=(response_json or {}).get("model_instance_id") or self._instance_id,
            request_image_format=getattr(request_metadata, "request_image_format", None),
            request_image_mime_type=getattr(request_metadata, "request_image_mime_type", None),
            request_image_width_px=getattr(request_metadata, "request_image_width_px", None),
            request_image_height_px=getattr(request_metadata, "request_image_height_px", None),
            request_image_bytes=getattr(request_metadata, "request_image_bytes", None),
            context_length=self.context_length,
            reasoning_mode=self.reasoning_mode,
            request_config_json=self._request_config(request_payload),
            request_messages_json=_redacted_request_messages(request_payload),
            request_hash=_request_hash(
                request_payload=request_payload,
                request_config=self._request_config(request_payload),
                model=self.model,
                prompt_snapshot_id=self._prompt_snapshot_id,
                source_file_hash=self._source_file_hash,
                request_metadata=request_metadata,
            ),
            model_load_config_json=self._load_config,
            duration_ms=duration_ms,
            http_status=http_status,
            error_code=error_code,
            error_message=error_message,
            retry_instruction_text=retry_instruction_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=(input_tokens or 0) + (output_tokens or 0) if input_tokens is not None or output_tokens is not None else None,
            reasoning_output_tokens=_int_or_none(stats.get("reasoning_output_tokens")),
            tokens_per_second=_float_or_none(stats.get("tokens_per_second")),
            time_to_first_token_seconds=_float_or_none(stats.get("time_to_first_token_seconds")),
            model_load_time_seconds=_float_or_none(stats.get("model_load_time_seconds")),
            raw_response=raw_response,
            parsed_json=parsed_json,
            parse_error=parse_error,
            validation_status=validation_status,
            validation_issues_json=validation_issues or [],
            response_stats_json=stats,
        )

    def _with_artifact(
        self,
        attempt: ModelExtractionAttempt,
        path: Path,
        artifact_type: str,
        *,
        canonical: bool,
    ) -> ModelExtractionAttempt:
        return replace(
            attempt,
            artifact_path=str(path),
            artifact_type=artifact_type,
            artifact_is_canonical=canonical,
        )

    def _notify_attempt(self, attempt: ModelExtractionAttempt) -> None:
        if self._on_attempt is not None:
            self._on_attempt(attempt)

    def _request_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "temperature": payload.get("temperature"),
            "max_output_tokens": payload.get("max_output_tokens"),
            "reasoning": payload.get("reasoning"),
            "context_length": self.context_length,
            "model": payload.get("model"),
        }

    def _desired_load_config(self) -> dict[str, Any]:
        return desired_load_config(
            context_length=self.context_length,
            eval_batch_size=self.eval_batch_size,
            physical_batch_size=self.physical_batch_size,
            flash_attention=self.flash_attention,
            offload_kv_cache_to_gpu=self.offload_kv_cache_to_gpu,
        )

    def _ensure_loaded(self) -> None:
        with _model_lock(self.api_base, self.model):
            instances = self._loaded_instances()
            desired = self._desired_load_config()
            compatible = [inst for inst in instances if load_config_compatible(instance_load_config(inst), desired)]
            if compatible:
                self._instance_id = compatible[0].get("id") or self.model
                self._load_config = normalized_load_config(instance_load_config(compatible[0])) or desired
                for duplicate in compatible[1:]:
                    self._unload(duplicate.get("id"))
                for incompatible in [inst for inst in instances if inst not in compatible]:
                    self._unload(incompatible.get("id"))
                self._capture_runtime_snapshot_if_changed()
                return
            for inst in instances:
                self._unload(inst.get("id"))
            self._load_model(desired)
            self._capture_runtime_snapshot()

    def _reload_model(self) -> None:
        with _model_lock(self.api_base, self.model):
            for inst in self._loaded_instances():
                self._unload(inst.get("id"))
            self._load_model(self._desired_load_config())
            self._capture_runtime_snapshot()

    def _capture_runtime_snapshot(self) -> None:
        signature = self._runtime_observation_signature()
        if self._on_runtime_snapshot is None:
            self._runtime_signature = signature
            return
        self._runtime_snapshot_id = self._on_runtime_snapshot({
            "endpoint": self.api_base,
            "configured_model": self.model,
            "matched_model": self.model,
            "loaded_model": self.model,
            "instance_id": self._instance_id,
            "desired_config": self._desired_load_config(),
            "effective_config": self._load_config,
            "ok": True,
            "message": "Runtime observed after model load/reload",
        })
        self._runtime_signature = signature

    def _capture_runtime_snapshot_if_changed(self) -> None:
        if self._runtime_observation_signature() != self._runtime_signature:
            self._capture_runtime_snapshot()

    def _runtime_observation_signature(self) -> str:
        return json.dumps(
            {
                "instance_id": self._instance_id,
                "load_config": self._load_config or {},
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _loaded_instances(self) -> list[dict[str, Any]]:
        response = self._runtime_request(
            "GET",
            f"{self.api_base}/models",
            timeout=self.timeout_connect,
        )
        data = response.json()
        for model_info in data.get("models", []):
            if model_info.get("key") == self.model:
                return list(model_info.get("loaded_instances", []))
        return []

    def _load_model(self, config: dict[str, Any]) -> None:
        payload = {"model": self.model, "echo_load_config": True, **config}
        response = self._runtime_request(
            "POST",
            f"{self.api_base}/models/load",
            json=payload,
            timeout=(self.timeout_connect, self.timeout_read),
        )
        data = response.json()
        self._instance_id = data.get("instance_id") or self.model
        self._load_config = normalized_load_config(data.get("load_config") or data.get("config") or {}) or config
        load_time = data.get("load_time_seconds")
        if load_time is not None:
            self._load_config = {**(self._load_config or {}), "load_time_seconds": load_time}
        log.info("[lmstudio] Loaded %s with %s", self._instance_id, self._load_config)

    def _unload(self, instance_id: str | None) -> None:
        if not instance_id:
            return
        self._runtime_request(
            "POST",
            f"{self.api_base}/models/unload",
            json={"instance_id": instance_id},
            timeout=(self.timeout_connect, self.timeout_read),
        )
        if instance_id == self._instance_id:
            self._instance_id = None

    def _runtime_request(self, method: str, url: str, **kwargs) -> requests.Response:
        if self._session is None:
            raise LMStudioRuntimeError(f"LM Studio session is closed for model={self.model} endpoint={url}")
        last_exc: Exception | None = None
        for attempt in range(1, _RUNTIME_MAX_ATTEMPTS + 1):
            try:
                response = self._session.request(method, url, **kwargs)
                if response.status_code in _RUNTIME_TRANSIENT_STATUS and attempt < _RUNTIME_MAX_ATTEMPTS:
                    last_exc = requests.HTTPError(
                        f"{response.status_code} transient response from {url}",
                        response=response,
                    )
                    _runtime_backoff(attempt)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                response = getattr(exc, "response", None)
                status = response.status_code if response is not None else None
                transient = status in _RUNTIME_TRANSIENT_STATUS or status is None
                if not transient or attempt >= _RUNTIME_MAX_ATTEMPTS:
                    break
                _runtime_backoff(attempt)
        raise LMStudioRuntimeError(
            "LM Studio runtime is not ready "
            f"(model={self.model}, endpoint={url}, desired_load_config={self._desired_load_config()}): {last_exc}"
        ) from last_exc

    def _track_performance(self, elapsed_s: float, stats: dict[str, Any]) -> None:
        tps = _float_or_none(stats.get("tokens_per_second"))
        slow = False
        if tps is not None and tps < self.performance_tps_floor:
            slow = True
        if elapsed_s > self.performance_reload_elapsed_s:
            slow = True
        self._slow_streak = self._slow_streak + 1 if slow else 0
        if self._slow_streak >= self.performance_reload_streak:
            self._reload_before_next = True


def _lmstudio_api_base(url: str) -> str:
    clean = url.rstrip("/")
    if "/api/v1/" in clean:
        return clean.split("/api/v1/", 1)[0] + "/api/v1"
    if clean.endswith("/api/v1"):
        return clean
    if "/v1/" in clean:
        return clean.split("/v1/", 1)[0] + "/api/v1"
    return clean


def _lmstudio_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if item.get("type") == "message" and isinstance(item.get("content"), str):
            chunks.append(item["content"])
            continue
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "".join(chunks).strip()
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message", {})
        text = message.get("content")
        if isinstance(text, str):
            return text
    return json.dumps(data, ensure_ascii=False)


def _model_lock(api_base: str, model: str) -> Lock:
    key = (api_base, model)
    with _MODEL_LOCKS_GUARD:
        lock = _MODEL_LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _MODEL_LOCKS[key] = lock
        return lock


def _runtime_backoff(attempt: int) -> None:
    time.sleep(min(0.5 * (2 ** (attempt - 1)), 4.0))


def _redacted_request_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in payload.get("input", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image":
            messages.append({"type": "image", "data_url": "[image redacted]"})
        else:
            messages.append(dict(item))
    return messages


def _request_hash(
    *,
    request_payload: dict[str, Any],
    request_config: dict[str, Any],
    model: str,
    prompt_snapshot_id: str | None,
    source_file_hash: str | None,
    request_metadata: ModelRequestMetadata | None,
) -> str:
    return canonical_request_hash(
        request_messages_json=_redacted_request_messages(request_payload),
        request_config_json=request_config,
        prompt_snapshot_id=prompt_snapshot_id,
        model=model,
        source_file_hash=source_file_hash,
        request_image_format=getattr(request_metadata, "request_image_format", None),
        request_image_mime_type=getattr(request_metadata, "request_image_mime_type", None),
        request_image_width=getattr(request_metadata, "request_image_width_px", None),
        request_image_height=getattr(request_metadata, "request_image_height_px", None),
        request_image_bytes=getattr(request_metadata, "request_image_bytes", None),
    )


def build_backend(cfg) -> LLMBackend:
    """Instantiate the LM Studio native backend from AppConfig."""
    return LMStudioNativeBackend(
        url=cfg.llm.url,
        model=cfg.llm.model,
        max_tokens=cfg.llm.max_completion_tokens,
        temperature=cfg.llm.temperature,
        timeout_connect=cfg.llm.timeout_connect,
        timeout_read=cfg.llm.timeout_read,
        max_retries=cfg.llm.max_retries,
        system_prompt=get_system_prompt(cfg.prompt.active),
        context_length=getattr(cfg.llm, "context_length", None) or 5000,
        reasoning_mode=getattr(cfg.llm, "reasoning_mode", None) or "off",
        eval_batch_size=getattr(cfg.llm, "eval_batch_size", None),
        physical_batch_size=getattr(cfg.llm, "physical_batch_size", None),
        flash_attention=getattr(cfg.llm, "flash_attention", True),
        offload_kv_cache_to_gpu=getattr(cfg.llm, "offload_kv_cache_to_gpu", True),
        performance_tps_floor=getattr(cfg.llm, "performance_tps_floor", 20.0),
        performance_reload_elapsed_s=getattr(cfg.llm, "performance_reload_elapsed_s", 45.0),
        performance_reload_streak=getattr(cfg.llm, "performance_reload_streak", 3),
    )
