from __future__ import annotations

from forza.lmstudio.client import LMStudioRuntimeClient


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self.payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return _FakeResponse(self.payload)

    def close(self) -> None:
        pass


def _client(payload) -> tuple[LMStudioRuntimeClient, _FakeSession]:
    session = _FakeSession(payload)
    return LMStudioRuntimeClient("http://127.0.0.1:1234/api/v1/chat", session=session), session


def test_list_models_accepts_native_models_payload() -> None:
    client, session = _client({
        "models": [
            {
                "key": "qwen/qwen3.5-9b",
                "display_name": "Qwen 3.5 9B",
                "publisher": "Qwen",
                "architecture": "qwen3",
                "format": "gguf",
                "params_string": "9B",
                "size_bytes": 10_737_418_240,
                "max_context_length": 32768,
                "quantization": {"name": "Q4_K_M", "bits_per_weight": 4.5},
                "capabilities": {
                    "vision": True,
                    "trained_for_tool_use": False,
                    "reasoning": {"allowed_options": ["off", "auto"], "default": "off"},
                },
                "loaded_instances": [
                    {
                        "id": "instance-1",
                        "config": {
                            "contextLength": "5000",
                            "evalBatchSize": "1024",
                            "flashAttention": "true",
                            "offloadKVCacheToGpu": 1,
                        },
                    }
                ],
            }
        ]
    })

    models = client.list_models()

    assert session.calls[0][0] == "http://127.0.0.1:1234/api/v1/models"
    assert models[0].id == "qwen/qwen3.5-9b"
    assert models[0].label == "Qwen 3.5 9B"
    assert models[0].loaded_instances[0].id == "instance-1"
    assert models[0].capabilities["vision"] is True


def test_list_models_preserves_legacy_data_and_list_payloads() -> None:
    data_client, _session = _client({"data": [{"id": "model-from-data"}]})
    list_client, _session = _client([{"id": "model-from-list"}])

    assert data_client.list_model_keys() == ("model-from-data",)
    assert list_client.list_model_keys() == ("model-from-list",)


def test_runtime_status_reports_loaded_compatible_model() -> None:
    client, _session = _client({
        "models": [
            {
                "key": "qwen/qwen3.5-9b",
                "display_name": "Qwen 3.5 9B",
                "max_context_length": 32768,
                "capabilities": {"vision": True, "reasoning": {"allowed_options": ["off", "auto"]}},
                "loaded_instances": [
                    {
                        "id": "instance-1",
                        "config": {
                            "context_length": 5000,
                            "eval_batch_size": 1024,
                            "flash_attention": True,
                            "offload_kv_cache_to_gpu": True,
                        },
                    }
                ],
            }
        ]
    })

    status = client.runtime_status(
        configured_model="qwen/qwen3.5-9b",
        desired_load_config={
            "context_length": 5000,
            "eval_batch_size": 1024,
            "flash_attention": True,
            "offload_kv_cache_to_gpu": True,
        },
        reasoning_mode="off",
    )

    assert status.level == "ok"
    assert status.loaded
    assert status.instance_id == "instance-1"
    assert "ctx 5000" in status.runtime_config_summary
    assert "vision=yes" in status.capabilities_summary


def test_runtime_status_reports_not_found_and_not_loaded() -> None:
    missing_client, _session = _client({"models": [{"key": "other-model"}]})
    not_loaded_client, _session = _client({"models": [{"key": "qwen/qwen3.5-9b", "loaded_instances": []}]})

    missing = missing_client.runtime_status(configured_model="qwen/qwen3.5-9b")
    not_loaded = not_loaded_client.runtime_status(configured_model="qwen/qwen3.5-9b")

    assert missing.level == "error"
    assert "not found" in missing.message
    assert not_loaded.level == "warning"
    assert "not loaded" in not_loaded.message


def test_runtime_status_reports_config_and_capability_warnings() -> None:
    client, _session = _client({
        "models": [
            {
                "key": "qwen/qwen3.5-9b",
                "max_context_length": 4096,
                "capabilities": {"vision": False, "reasoning": {"allowed_options": ["auto"]}},
                "loaded_instances": [
                    {
                        "id": "instance-1",
                        "config": {
                            "context_length": 4096,
                            "eval_batch_size": 512,
                            "flash_attention": False,
                            "offload_kv_cache_to_gpu": False,
                        },
                    }
                ],
            }
        ]
    })

    status = client.runtime_status(
        configured_model="qwen/qwen3.5-9b",
        desired_load_config={
            "context_length": 5000,
            "eval_batch_size": 1024,
            "flash_attention": True,
            "offload_kv_cache_to_gpu": True,
        },
        reasoning_mode="off",
    )

    assert status.level == "warning"
    assert any("context_length" in warning for warning in status.warnings)
    assert any("vision" in warning for warning in status.warnings)
    assert any("Reasoning mode mismatch" in warning for warning in status.warnings)
