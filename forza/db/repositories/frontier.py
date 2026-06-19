from __future__ import annotations

from collections import OrderedDict
from typing import Protocol

from ...config import CLASS_ORDER


class FrontierLap(Protocol):
    id: str
    image_file_id: str
    track: str
    race_class: str
    weather: str | None
    temp_f: float | None
    driver: str
    car: str
    best_lap_ms: int
    dirty: bool


class FrontierCalculator:
    """Calculate clean best-lap rows without depending on a database session."""

    def simple_best_rows(self, rows: list[FrontierLap]) -> list[FrontierLap]:
        clean = [row for row in rows if not row.dirty]
        clean.sort(key=lambda row: row.best_lap_ms)
        best: OrderedDict[tuple[str, str, str, str], FrontierLap] = OrderedDict()
        for row in clean:
            key = (row.track, row.race_class, row.driver, row.car)
            best.setdefault(key, row)
        return list(best.values())

    def clean_frontier_rows(
        self,
        rows: list[FrontierLap],
        gamertag: str,
    ) -> list[FrontierLap]:
        if not rows:
            return []

        name_lower = gamertag.lower()
        player_by_car: dict[tuple, list[tuple[int, float | None, FrontierLap]]] = {}
        player_overall: dict[tuple, list[tuple[int, float | None, FrontierLap]]] = {}

        for row in rows:
            if row.driver.lower() != name_lower:
                continue
            condition = self._condition_key(row)
            temp = self._temp_key(row)
            player_by_car.setdefault(
                (row.track, row.race_class, row.car, condition),
                [],
            ).append((row.best_lap_ms, temp, row))
            player_overall.setdefault(
                (row.track, row.race_class, condition),
                [],
            ).append((row.best_lap_ms, temp, row))

        kept: list[FrontierLap] = []
        for row in rows:
            condition = self._condition_key(row)
            temp = self._temp_key(row)
            overall_candidates = player_overall.get((row.track, row.race_class, condition), [])
            limit = self._best_player_time(overall_candidates)
            if limit is None:
                continue

            if row.driver.lower() == name_lower:
                candidates = player_by_car.get((row.track, row.race_class, row.car, condition), [])
                if self._is_frontier_record(candidates, row, row.best_lap_ms, temp):
                    kept.append(row)
            elif row.best_lap_ms < limit:
                kept.append(row)

        opponent_best: dict[tuple, int] = {}
        for row in kept:
            if row.driver.lower() == name_lower:
                continue
            key = (row.driver, row.car, row.track, row.race_class, self._condition_key(row))
            previous = opponent_best.get(key)
            if previous is None or row.best_lap_ms < previous:
                opponent_best[key] = row.best_lap_ms

        claimed: set[tuple] = set()
        final_rows: list[FrontierLap] = []
        for row in kept:
            if row.driver.lower() == name_lower:
                final_rows.append(row)
                continue
            key = (row.driver, row.car, row.track, row.race_class, self._condition_key(row))
            best = opponent_best.get(key)
            if best is not None and row.best_lap_ms == best and key not in claimed:
                final_rows.append(row)
                claimed.add(key)

        final_rows.sort(
            key=lambda row: (
                (row.track or "").lower(),
                CLASS_ORDER.get(row.race_class, 99),
                row.weather or "unknown",
                row.temp_f if row.temp_f is not None else -1,
                row.best_lap_ms,
            )
        )
        return final_rows

    def _condition_key(self, row: FrontierLap) -> tuple:
        return (row.weather or "unknown",)

    def _temp_key(self, row: FrontierLap) -> float | None:
        if row.temp_f is None:
            return None
        return round(float(row.temp_f), 1)

    def _dominates_time(
        self,
        challenger_time: int,
        challenger_temp: float | None,
        current_time: int,
        current_temp: float | None,
    ) -> bool:
        if challenger_time == current_time and challenger_temp == current_temp:
            return False
        if challenger_time > current_time:
            return False
        if challenger_temp is None or current_temp is None:
            return challenger_temp == current_temp
        return challenger_temp <= current_temp

    def _is_frontier_record(
        self,
        candidates: list[tuple[int, float | None, FrontierLap]],
        current: FrontierLap,
        current_time: int,
        current_temp: float | None,
    ) -> bool:
        for other_time, other_temp, other in candidates:
            if other.image_file_id == current.image_file_id:
                continue
            if self._dominates_time(other_time, other_temp, current_time, current_temp):
                return False
        return True

    def _best_player_time(
        self,
        candidates: list[tuple[int, float | None, FrontierLap]],
    ) -> int | None:
        if not candidates:
            return None
        return min(time for time, _, _ in candidates)
