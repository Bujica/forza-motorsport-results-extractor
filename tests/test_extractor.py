from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from forza.lmstudio import backend as extractor
from forza.exceptions import ParseError
from forza.lmstudio.backend import (
    LMStudioNativeBackend,
    LMStudioRuntimeError,
    _lmstudio_api_base,
    _parse_or_repair_response,
    _semantic_retry_issues,
)
from forza.lmstudio.load_config import load_config_compatible
from forza.schemas import ModelRequestMetadata



def test_parse_or_repair_tries_strict_parse_then_json_repair(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fake_parse(content: str) -> dict:
        calls.append(content)
        if content == "broken-json":
            raise ParseError("strict parse failed")
        return {"t": "Track", "e": []}

    monkeypatch.setattr(extractor, "parse_and_validate_response", fake_parse)
    monkeypatch.setattr(extractor, "repair_json", lambda content, return_objects=False: "repaired-json")

    parsed, error = _parse_or_repair_response("broken-json")

    assert parsed == {"t": "Track", "e": []}
    assert error is None
    assert calls == ["broken-json", "repaired-json"]



def test_parse_or_repair_returns_repair_error(monkeypatch, tmp_path) -> None:
    def fake_parse(_content: str) -> dict:
        raise ParseError("strict parse failed")

    def fake_repair(_content: str, return_objects=False) -> str:
        raise RuntimeError("repair failed")

    monkeypatch.setattr(extractor, "parse_and_validate_response", fake_parse)
    monkeypatch.setattr(extractor, "repair_json", fake_repair)

    parsed, error = _parse_or_repair_response("broken-json")

    assert parsed is None
    assert error == "repair failed"


def test_lmstudio_native_base_derives_from_compat_url() -> None:
    assert (
        _lmstudio_api_base("http://127.0.0.1:1234/v1/chat/completions")
        == "http://127.0.0.1:1234/api/v1"
    )
    assert _lmstudio_api_base("http://127.0.0.1:1234/api/v1/chat") == "http://127.0.0.1:1234/api/v1"


def test_semantic_retry_does_not_flag_partial_driver_lists() -> None:
    parsed = {"t": "Maple Valley Full Circuit", "e": [{"bl": "01:34.311"}]}
    assert _semantic_retry_issues(parsed) == []


def test_semantic_retry_flags_empty_or_all_null_laps() -> None:
    assert "entries_empty" in _semantic_retry_issues({"t": "Track", "e": []})
    assert "all_best_laps_null" in _semantic_retry_issues(
        {"t": "Track", "e": [{"bl": None}, {"bl": None}]}
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("No fake response queued")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        pass


def _native_backend(tmp_path: Path, session) -> LMStudioNativeBackend:
    backend = LMStudioNativeBackend(
        url="http://127.0.0.1:1234/api/v1/chat",
        model="qwen/qwen3.5-9b",
        max_tokens=800,
        temperature=0.0,
        timeout_connect=10,
        timeout_read=180,
        max_retries=3,
        system_prompt="system",
        context_length=5000,
        reasoning_mode="off",
        eval_batch_size=1024,
        physical_batch_size=512,
        flash_attention=True,
        offload_kv_cache_to_gpu=True,
    )
    backend._session = session
    return backend


def test_lmstudio_runtime_retries_transient_models_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(extractor, "_runtime_backoff", lambda _attempt: None)
    session = _FakeSession(
        [
            _FakeResponse(500),
            _FakeResponse(200, {"models": [{"key": "qwen/qwen3.5-9b", "loaded_instances": []}]}),
            _FakeResponse(
                200,
                {
                    "instance_id": "instance-1",
                    "load_config": {
                        "context_length": 5000,
                        "eval_batch_size": 1024,
                        "physical_batch_size": 512,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                },
            ),
        ]
    )
    backend = _native_backend(tmp_path, session)

    backend._ensure_loaded()

    assert backend._instance_id == "instance-1"
    assert [method for method, _url, _kwargs in session.calls] == ["GET", "GET", "POST"]


def test_lmstudio_runtime_request_retries_connection_error_then_returns_response(monkeypatch, tmp_path) -> None:
    backoffs: list[int] = []
    monkeypatch.setattr(extractor, "_runtime_backoff", backoffs.append)
    session = _FakeSession(
        [
            requests.ConnectionError("connection dropped"),
            _FakeResponse(200, {"ok": True}),
        ]
    )
    backend = _native_backend(tmp_path, session)

    response = backend._runtime_request("GET", "http://127.0.0.1:1234/api/v1/models")

    assert response.json() == {"ok": True}
    assert [method for method, _url, _kwargs in session.calls] == ["GET", "GET"]
    assert backoffs == [1]


def test_lmstudio_runtime_request_does_not_retry_non_transient_status(monkeypatch, tmp_path) -> None:
    def fail_backoff(_attempt: int) -> None:
        raise AssertionError("non-transient status must not back off or retry")

    monkeypatch.setattr(extractor, "_runtime_backoff", fail_backoff)
    session = _FakeSession([_FakeResponse(400)])
    backend = _native_backend(tmp_path, session)

    try:
        backend._runtime_request("GET", "http://127.0.0.1:1234/api/v1/models")
    except LMStudioRuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("LMStudioRuntimeError was not raised")

    assert "model=qwen/qwen3.5-9b" in message
    assert "400 error" in message
    assert [method for method, _url, _kwargs in session.calls] == ["GET"]


def test_lmstudio_load_config_compatible_normalizes_runtime_fields() -> None:
    existing = {
        "contextLength": "5000",
        "evalBatchSize": "1024",
        "physicalBatchSize": "512",
        "flashAttention": "true",
        "offloadKVCacheToGpu": 1,
    }
    desired = {
        "context_length": 5000,
        "eval_batch_size": 1024,
        "physical_batch_size": 512,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": True,
    }

    assert load_config_compatible(existing, desired)


def test_lmstudio_runtime_load_failure_is_operational_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(extractor, "_runtime_backoff", lambda _attempt: None)
    session = _FakeSession(
        [_FakeResponse(200, {"models": [{"key": "qwen/qwen3.5-9b", "loaded_instances": []}]})]
        + [_FakeResponse(500) for _ in range(5)]
    )
    backend = _native_backend(tmp_path, session)

    try:
        backend._ensure_loaded()
    except LMStudioRuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("LMStudioRuntimeError was not raised")

    assert "model=qwen/qwen3.5-9b" in message
    assert "/models/load" in message
    assert "desired_load_config" in message


class _SharedRuntimeSession:
    loaded = False
    load_calls = 0

    def __init__(self) -> None:
        self.calls = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "GET" and url.endswith("/models"):
            instances = []
            if type(self).loaded:
                instances = [
                    {
                        "id": "instance-1",
                        "config": {
                            "context_length": 5000,
                            "eval_batch_size": 1024,
                            "physical_batch_size": 512,
                            "flash_attention": True,
                            "offload_kv_cache_to_gpu": True,
                        },
                    }
                ]
            return _FakeResponse(200, {"models": [{"key": "qwen/qwen3.5-9b", "loaded_instances": instances}]})
        if method == "POST" and url.endswith("/models/load"):
            time.sleep(0.05)
            type(self).load_calls += 1
            type(self).loaded = True
            return _FakeResponse(
                200,
                {
                    "instance_id": "instance-1",
                    "load_config": {
                        "context_length": 5000,
                        "eval_batch_size": 1024,
                        "physical_batch_size": 512,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                },
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    def close(self) -> None:
        pass


def test_lmstudio_parallel_ensure_loaded_is_single_flight(tmp_path) -> None:
    _SharedRuntimeSession.loaded = False
    _SharedRuntimeSession.load_calls = 0
    first = _native_backend(tmp_path, _SharedRuntimeSession())
    second = _native_backend(tmp_path, _SharedRuntimeSession())

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(backend._ensure_loaded) for backend in (first, second)]
        for future in futures:
            future.result(timeout=5)

    assert _SharedRuntimeSession.load_calls == 1
    assert first._instance_id == "instance-1"
    assert second._instance_id == "instance-1"


def _loaded_models_response() -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "models": [
                {
                    "key": "qwen/qwen3.5-9b",
                    "loaded_instances": [
                        {
                            "id": "instance-1",
                            "config": {
                                "context_length": 5000,
                                "eval_batch_size": 1024,
                                "physical_batch_size": 512,
                                "flash_attention": True,
                                "offload_kv_cache_to_gpu": True,
                            },
                        }
                    ],
                }
            ]
        },
    )


def _chat_response() -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "model_instance_id": "instance-1",
            "output": [
                {
                    "type": "message",
                    "content": (
                        '{"t":"Track","e":[{"dr":"Driver","ca":"Car",'
                        '"cl":"A","bl":"01:00.000"}]}'
                    ),
                }
            ],
            "stats": {"input_tokens": 10, "total_output_tokens": 5},
        },
    )


def test_lmstudio_persists_completed_attempt_callback_with_sql_evidence(tmp_path) -> None:
    attempts = []
    backend = _native_backend(tmp_path / "raw", _FakeSession([_loaded_models_response(), _chat_response()]))
    backend.configure_persistence(
        on_attempt=attempts.append,
        on_runtime_snapshot=None,
        runtime_snapshot_id="runtime-preflight",
        prompt_snapshot_id="prompt-main",
    )
    backend.set_request_context(
        ModelRequestMetadata(
            request_image_format="png",
            request_image_mime_type="image/png",
            request_image_width_px=1600,
            request_image_height_px=900,
            request_image_bytes=123,
        )
    )

    result = backend.extract("abc", "image/png", "hash.png", "run-1", "source-hash")

    assert result.attempts == attempts
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.accepted is True
    assert attempt.runtime_snapshot_id == "runtime-preflight"
    assert attempt.request_hash
    assert attempt.raw_response
    assert attempt.parsed_json == result.parsed
    assert attempt.response_stats_json == {"input_tokens": 10, "total_output_tokens": 5}
    assert attempt.artifact_path is None
    assert attempt.artifact_type is None
    assert attempt.artifact_is_canonical is False
    assert result.raw_response_artifact_path is None
    assert not list((tmp_path / "raw").rglob("*.json"))


def test_lmstudio_reload_updates_runtime_snapshot_for_next_attempt(tmp_path) -> None:
    attempts = []
    snapshots = []
    session = _FakeSession(
        [
            _loaded_models_response(),
            _FakeResponse(500),
            _loaded_models_response(),
            _FakeResponse(200),
            _FakeResponse(
                200,
                {
                    "instance_id": "instance-2",
                    "load_config": {
                        "context_length": 5000,
                        "eval_batch_size": 1024,
                        "physical_batch_size": 512,
                        "flash_attention": True,
                        "offload_kv_cache_to_gpu": True,
                    },
                },
            ),
            _chat_response(),
        ]
    )
    backend = _native_backend(tmp_path / "raw", session)

    def record_snapshot(snapshot) -> str:
        snapshots.append(snapshot)
        return f"runtime-observed-{len(snapshots)}"

    backend.configure_persistence(
        on_attempt=attempts.append,
        on_runtime_snapshot=record_snapshot,
        runtime_snapshot_id="runtime-preflight",
        prompt_snapshot_id="prompt-main",
    )

    backend.extract("abc", "image/png", "hash.png", "run-1", "source-hash")

    assert len(snapshots) == 2
    assert [attempt.runtime_snapshot_id for attempt in attempts] == [
        "runtime-observed-1",
        "runtime-observed-2",
    ]
    assert attempts[0].artifact_path is None
    assert attempts[0].artifact_type is None
    assert attempts[0].artifact_is_canonical is False
    assert attempts[1].accepted is True
    assert attempts[1].artifact_path is None
    assert attempts[1].artifact_type is None
    assert not list((tmp_path / "raw").rglob("*.json"))


def test_lmstudio_compatible_runtime_snapshot_is_not_duplicated_per_backend(tmp_path) -> None:
    snapshots = []
    backend = _native_backend(
        tmp_path / "raw",
        _FakeSession([_loaded_models_response(), _loaded_models_response()]),
    )
    backend.configure_persistence(
        on_attempt=None,
        on_runtime_snapshot=lambda snapshot: snapshots.append(snapshot) or "runtime-observed",
        runtime_snapshot_id="runtime-preflight",
        prompt_snapshot_id="prompt-main",
    )

    backend._ensure_loaded()
    backend._ensure_loaded()
    backend.configure_persistence(
        on_attempt=None,
        on_runtime_snapshot=lambda snapshot: snapshots.append(snapshot) or "unexpected",
        runtime_snapshot_id="runtime-preflight-next-image",
        prompt_snapshot_id="prompt-main",
    )

    assert len(snapshots) == 1
    assert backend._runtime_snapshot_id == "runtime-observed"



def test_build_backend_uses_configured_prompt_without_passing_cfg(monkeypatch, tmp_path) -> None:
    cfg = type("Cfg", (), {})()
    cfg.llm = type("LLM", (), {
        "url": "http://127.0.0.1:1234/api/v1/chat",
        "model": "model-a",
        "max_completion_tokens": 800,
        "temperature": 0.0,
        "timeout_connect": 10,
        "timeout_read": 180,
        "max_retries": 3,
        "context_length": 5000,
        "reasoning_mode": "off",
        "eval_batch_size": 1024,
        "physical_batch_size": None,
        "flash_attention": True,
        "offload_kv_cache_to_gpu": True,
        "performance_tps_floor": 20.0,
        "performance_reload_elapsed_s": 45.0,
        "performance_reload_streak": 3,
    })()
    cfg.prompt = type("Prompt", (), {"active": "prompt-main"})()

    calls: list[object] = []

    def fake_get_system_prompt(*args):
        calls.append(args)
        if args != ("prompt-main",):
            raise AssertionError(f"unexpected prompt args: {args!r}")
        return "system prompt"

    monkeypatch.setattr(extractor, "get_system_prompt", fake_get_system_prompt)

    backend = extractor.build_backend(cfg)

    try:
        assert backend.system_prompt == "system prompt"
        assert calls == [("prompt-main",)]
    finally:
        backend.close()
