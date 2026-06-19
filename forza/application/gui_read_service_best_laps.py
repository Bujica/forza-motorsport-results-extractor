from __future__ import annotations

from .gui_read_service import GuiReadService
from ..db.repositories import ExternalRecordRepository
from ..schemas import ExternalLapRecord


def list_external_records(reader: GuiReadService) -> list[ExternalLapRecord]:
    """Read active external records through the existing GUI read facade engine.

    This helper deliberately uses ``GuiReadService``'s session context so Best
    Laps does not create a second ``DatabaseService`` engine for GUI reads.
    """
    if not reader._can_read():  # noqa: SLF001 - same GUI read-facade layer
        return []
    with reader._session() as session:  # noqa: SLF001 - same GUI read-facade layer
        return ExternalRecordRepository(session).active_records()
