from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlmodel import Session

from ...db import create_sqlite_engine
from ...db.migrate import is_up_to_date


class GuiReadSessionProvider:
    """Owns GUI read database engine lifecycle and schema-readiness cache."""

    def __init__(self, database_file: Path):
        self.database_file = Path(database_file)
        self._engine = None
        self._schema_ready: bool | None = None

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def invalidate_schema_cache(self) -> None:
        self._schema_ready = None

    def can_read(self) -> bool:
        if not self.database_file.exists():
            self._schema_ready = None
            return False
        if self._schema_ready is True:
            return True
        self._schema_ready = is_up_to_date(self.database_file)
        return self._schema_ready

    def get_engine(self):
        if self._engine is None:
            self._engine = create_sqlite_engine(self.database_file)
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.get_engine()) as session:
            yield session
