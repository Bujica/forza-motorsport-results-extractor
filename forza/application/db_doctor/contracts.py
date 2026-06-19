from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbDoctorCheck:
    key: str
    severity: str
    count: int
    detail: str

    @property
    def ok(self) -> bool:
        return self.count == 0


@dataclass(frozen=True)
class DbDoctorReport:
    database_file: Path
    schema_state: str
    checks: list[DbDoctorCheck]

    @property
    def ok(self) -> bool:
        return self.schema_state == "current" and all(
            check.ok for check in self.checks if check.severity == "error"
        )
