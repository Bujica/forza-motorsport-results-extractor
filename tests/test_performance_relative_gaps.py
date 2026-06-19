from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from forza.application.performance_service import compute_performance_summary, build_dashboard


@dataclass(frozen=True)
class Lap:
    id: str
    image_file_id: str
    track: str
    race_class: str
    weather: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int
    dirty: bool = False
    is_best_lap: bool = True
    source_file: str = "source.png"
    race_date: date | None = None


@dataclass(frozen=True)
class ExternalRecord:
    track: str
    race_class: str
    weather: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int


def test_community_gap_closest_uses_relative_gap_not_absolute_only() -> None:
    laps = [
        Lap(
            id="short-player",
            image_file_id="short-session",
            track="Short Circuit",
            race_class="D",
            weather="dry",
            driver="Bujica89",
            car="Car",
            best_lap="0:40.500",
            best_lap_ms=40_500,
        ),
        Lap(
            id="long-player",
            image_file_id="long-session",
            track="Long Circuit",
            race_class="D",
            weather="dry",
            driver="Bujica89",
            car="Car",
            best_lap="9:00.500",
            best_lap_ms=540_500,
        ),
    ]
    external = [
        ExternalRecord("Short Circuit", "D", "dry", "Community", "Car", "0:40.000", 40_000),
        ExternalRecord("Long Circuit", "D", "dry", "Community", "Car", "9:00.000", 540_000),
    ]

    summary = compute_performance_summary(laps, external, gamertag="Bujica89")

    assert summary.closest_to_community_ms == 500
    assert summary.closest_to_community_pct == pytest.approx(0.0925925926)
    assert summary.track_records[0].track == "Long Circuit"
    assert summary.track_records[0].gap_to_community_pct == pytest.approx(0.0925925926)
    assert summary.track_records[1].gap_to_community_pct == pytest.approx(1.25)


def test_dashboard_displays_absolute_and_relative_community_gap() -> None:
    laps = [
        Lap(
            id="short-player",
            image_file_id="short-session",
            track="Short Circuit",
            race_class="D",
            weather="dry",
            driver="Bujica89",
            car="Car",
            best_lap="0:40.500",
            best_lap_ms=40_500,
        )
    ]
    external = [ExternalRecord("Short Circuit", "D", "dry", "Community", "Car", "0:40.000", 40_000)]

    dashboard = build_dashboard(laps, gamertag="Bujica89", external_records=external)

    closest_card = next(card for card in dashboard.cards if card.title == "Closest community gap")
    assert closest_card.value == "+0.500s (+1.25%)"
    assert dashboard.records[0].detail.startswith("rival — · community 0:40.000 ·")
