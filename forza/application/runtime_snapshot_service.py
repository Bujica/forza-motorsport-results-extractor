from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session

from ..db.models import ModelRuntimeSnapshotEntity
from .db_session_provider import DbSessionProvider


class RuntimeSnapshotService:
    """Owns model runtime snapshot persistence."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def record_runtime_snapshot(
        self,
        *,
        run_id: str,
        diagnostic,
        snapshot_kind: str = "preflight",
    ) -> str:
        snapshot_id = uuid4().hex
        configured_model = _diagnostic_value(diagnostic, "configured_model")
        model_found = bool(_diagnostic_value(diagnostic, "model_found", True))
        matched_model = (
            _diagnostic_value(diagnostic, "matched_model")
            or (configured_model if model_found else None)
        )
        display_name = _diagnostic_value(diagnostic, "model_label") or matched_model
        effective_config = _diagnostic_value(diagnostic, "effective_config")
        model_matches_config = (
            configured_model is not None
            and matched_model is not None
            and str(configured_model).strip() == str(matched_model).strip()
        )
        with Session(self._session_provider.engine_for_db()) as session:
            row = ModelRuntimeSnapshotEntity(
                id=snapshot_id,
                run_id=run_id,
                snapshot_kind=snapshot_kind,
                endpoint=_diagnostic_value(diagnostic, "endpoint", "") or "",
                configured_model=configured_model,
                matched_model=matched_model,
                loaded_model=_diagnostic_value(diagnostic, "loaded_model") or matched_model,
                instance_id=_diagnostic_value(diagnostic, "instance_id") or None,
                display_name=display_name,
                capabilities_json={
                    "summary": _diagnostic_value(diagnostic, "capabilities_summary", ""),
                    "warnings": list(_diagnostic_value(diagnostic, "warnings", ()) or ()),
                    "errors": list(_diagnostic_value(diagnostic, "errors", ()) or ()),
                },
                desired_load_config_json=_diagnostic_value(diagnostic, "desired_config"),
                effective_load_config_json=effective_config,
                load_time_seconds=(
                    _diagnostic_value(diagnostic, "load_time_seconds")
                    or (
                        effective_config.get("load_time_seconds")
                        if isinstance(effective_config, dict)
                        else None
                    )
                ),
                health_ok=bool(_diagnostic_value(diagnostic, "ok", False)),
                health_message=_diagnostic_value(diagnostic, "message"),
                model_matches_config=model_matches_config,
            )
            session.add(row)
            session.commit()
            return snapshot_id


def _diagnostic_value(diagnostic, name: str, default=None):
    if isinstance(diagnostic, dict):
        return diagnostic.get(name, default)
    return getattr(diagnostic, name, default)


__all__ = ["RuntimeSnapshotService"]
