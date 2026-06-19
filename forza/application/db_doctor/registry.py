from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlmodel import Session

from .contracts import DbDoctorCheck


DbDoctorCheckFn = Callable[[Session], Iterable[DbDoctorCheck]]


@dataclass(frozen=True)
class RegisteredDbDoctorCheck:
    key: str
    check: DbDoctorCheckFn


class DbDoctorCheckRegistry:
    def __init__(self) -> None:
        self._checks: list[RegisteredDbDoctorCheck] = []

    def register(self, key: str, check: DbDoctorCheckFn) -> None:
        if any(registered.key == key for registered in self._checks):
            raise ValueError(f"Duplicate DB Doctor check key: {key}")
        self._checks.append(RegisteredDbDoctorCheck(key=key, check=check))

    def checks(self) -> tuple[RegisteredDbDoctorCheck, ...]:
        return tuple(self._checks)
