from __future__ import annotations

from typing import Protocol

from .race_class import CLASS_ORDER


class LapRowLike(Protocol):
    track: str
    race_class: str
    weather: str
    best_lap_ms: int
    driver: str
    car: str


def track_order_map(track_order: list[str] | tuple[str, ...]) -> dict[str, int]:
    """Return a case-insensitive order map based on the canonical track file."""
    return {track.lower(): index for index, track in enumerate(track_order)}


def track_order_key(track: str, order_map: dict[str, int]) -> tuple[int, str]:
    normalized = str(track or "").strip()
    return (order_map.get(normalized.lower(), len(order_map) + 1), normalized.lower())


def class_order_key(race_class: str) -> tuple[int, str]:
    normalized = str(race_class or "").strip()
    return (CLASS_ORDER.get(normalized, 99), normalized)


def ordered_lap_key(row: LapRowLike, order_map: dict[str, int]) -> tuple:
    """Shared best-lap ordering for PDF, CSV, and GUI views.

    Lap ordering is based on integer milliseconds. Float seconds are not a
    domain contract because they are unsuitable for equality/frontier rules.
    """
    return (
        track_order_key(row.track, order_map),
        class_order_key(row.race_class),
        str(row.weather or "").lower(),
        row.best_lap_ms,
        str(row.driver or "").lower(),
        str(row.car or "").lower(),
    )
