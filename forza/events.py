from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .schemas.enums import ValueStrEnum

_log = logging.getLogger("forza")


class EventType(ValueStrEnum):
    """Event names emitted by services for GUI integration."""

    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    BATCH_STARTED = "batch_started"
    BATCH_FINISHED = "batch_finished"
    IMAGES_DISCOVERED = "images_discovered"
    IMAGE_STARTED = "image_started"
    IMAGE_FINISHED = "image_finished"
    IMAGE_FAILED = "image_failed"
    EXTRACTION_RESULT_CREATED = "extraction_result_created"
    LAP_RECORDS_UPDATED = "lap_records_updated"
    REVIEW_CASES_CREATED = "review_cases_created"
    REVIEW_CASE_CHANGED = "review_case_changed"
    IMAGE_FLAG_CREATED = "image_flag_created"
    IMAGE_FLAG_CHANGED = "image_flag_changed"
    IMAGE_STATUS_CHANGED = "image_status_changed"
    IMAGE_RENAMED = "image_renamed"
    IMAGE_EXPORTED = "image_exported"
    EXPORT_CREATED = "export_created"
    SNAPSHOT_SAVED = "snapshot_saved"
    LAP_RECORD_CORRECTED = "lap_record_corrected"
    PERSISTENCE_FAILED = "persistence_failed"


@dataclass(frozen=True)
class PipelineEvent:
    type: EventType
    message: str = ""
    run_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


EventSink = Callable[[PipelineEvent], None]


def _coerce_event_type(event_type: EventType | str) -> EventType:
    if isinstance(event_type, EventType):
        return event_type
    return EventType(str(event_type))


def emit_event(
    sink: EventSink | None,
    event_type: EventType | str,
    *,
    message: str = "",
    run_id: str | None = None,
    strict: bool = False,
    **data: Any,
) -> None:
    """Emit a typed pipeline event to the given sink.

    String inputs are accepted only when they are valid ``EventType`` values;
    unknown event names fail immediately instead of creating silent runtime
    contracts.
    """
    if sink is None:
        return
    canonical_type = _coerce_event_type(event_type)
    event = PipelineEvent(type=canonical_type, message=message, run_id=run_id, data=data)
    try:
        sink(event)
    except Exception:
        _log.exception(
            "[events] Event sink raised for event_type=%r run_id=%r",
            canonical_type.value,
            run_id,
        )
        if strict:
            raise
