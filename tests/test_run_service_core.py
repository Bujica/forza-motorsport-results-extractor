from __future__ import annotations

from tests._run_service_helpers import *


def test_make_run_id_uses_timestamp_prefix_and_uuid_suffix() -> None:
    run_id = RunService().make_run_id()

    assert re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{8}", run_id)

def test_log_discovery_preview_logs_batch_duplicate_branch(tmp_path) -> None:
    duplicate_path = tmp_path / "duplicate.png"
    plan = _plan(
        total=1,
        duplicates=[
            DuplicateImage(
                path=duplicate_path,
                file_hash="hash-dup",
                reason="batch",
                canonical_name="original.png",
                duplicate_of_hash="hash-original",
            )
        ],
    )
    log = _FakeLog()

    RunService()._log_discovery_preview(log, plan, [])

    assert any(
        level == "info"
        and "duplicate (batch): duplicate.png matches original.png" in message
        for level, message in log.messages
    )

def test_checkpoint_delegates_to_run_control() -> None:
    calls = []

    class _RunControl:
        def checkpoint(self) -> None:
            calls.append("checkpoint")

    RunService(run_control=_RunControl())._checkpoint()

    assert calls == ["checkpoint"]

def test_begin_run_kwargs_keeps_force_and_retry_out_of_persisted_mode(tmp_path) -> None:
    cfg = _cfg(tmp_path)

    force_kwargs = run_module._begin_run_kwargs(
        cfg,
        "run-force",
        RunOptions(force=True, max_images=10),
    )
    retry_kwargs = run_module._begin_run_kwargs(
        cfg,
        "run-retry",
        RunOptions(retry_errors=True),
    )

    assert "mode" not in force_kwargs
    assert force_kwargs["config"] == {"selection_limit": 10, "force": True}
    assert "mode" not in retry_kwargs
    assert retry_kwargs["config"] == {"retry_errors": True}

def test_run_mode_only_uses_persisted_schema_values() -> None:
    assert run_module._run_mode(RunOptions()) == "normal"
    assert run_module._run_mode(RunOptions(force=True)) == "normal"
    assert run_module._run_mode(RunOptions(retry_errors=True)) == "normal"
    assert run_module._run_mode(RunOptions(dry_run=True)) == "dry_run"
