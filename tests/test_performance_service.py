from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from forza.application.performance_service import (
    build_dashboard,
    build_car_performance,
    compute_performance_summary,
)


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
    is_best_lap: bool = False
    source_file: str = ""
    race_date: date | None = None


@dataclass(frozen=True)
class External:
    track: str
    race_class: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int
    weather: str = "dry"


def _laps() -> list[Lap]:
    return [
        Lap("p1", "s1", "Mugello", "A", "dry", "Bujica89", "Ferrari 488", "1:33.000", 93000, source_file="s1.png", race_date=date(2026, 5, 1)),
        Lap("r1", "s1", "Mugello", "A", "dry", "FastOne", "Lambo", "1:32.000", 92000, source_file="s1.png", race_date=date(2026, 5, 1)),
        Lap("p2", "s2", "Mugello", "A", "dry", "Bujica89", "Ferrari 488", "1:31.000", 91000, is_best_lap=True, source_file="s2.png", race_date=date(2026, 5, 10)),
        Lap("r2", "s2", "Mugello", "A", "dry", "FastOne", "Porsche", "1:31.500", 91500, source_file="s2.png", race_date=date(2026, 5, 10)),
        Lap("p3", "s3", "Mugello", "A", "rain", "Bujica89", "Ferrari 488", "1:40.000", 100000, source_file="s3.png", race_date=date(2026, 5, 12)),
        Lap("r3", "s3", "Mugello", "A", "rain", "RainAce", "Subaru", "1:39.000", 99000, source_file="s3.png", race_date=date(2026, 5, 12)),
        Lap("p4", "s4", "Road America", "TCR", "dry", "Bujica89", "Audi TCR", "2:11.000", 131000, source_file="s4.png", race_date=date(2026, 5, 14)),
        Lap("r4", "s4", "Road America", "TCR", "dry", "TouringAce", "Honda TCR", "2:10.000", 130000, source_file="s4.png", race_date=date(2026, 5, 14)),
        Lap("d1", "s5", "Mugello", "A", "dry", "Bujica89", "Ferrari 488", "1:20.000", 80000, dirty=True, source_file="dirty.png", race_date=date(2026, 5, 16)),
    ]


def test_compute_performance_summary_uses_player_sessions_and_dry_only_community_records() -> None:
    summary = compute_performance_summary(
        _laps(),
        [External("Mugello", "A", "Community", "Meta Car", "1:30.000", 90000), External("Road America", "TCR", "Community", "TCR Car", "2:00.000", 120000)],
        gamertag="Bujica89",
    )

    assert summary.total_sessions == 4
    assert summary.tracks_raced == 3
    assert summary.records_held == 1
    assert summary.closest_to_community_ms == 1000
    assert summary.most_improved_track == "Mugello · A · dry"
    assert summary.most_improved_delta_ms == 2000

    mugello_dry = next(row for row in summary.track_records if row.track == "Mugello" and row.weather == "dry")
    assert mugello_dry.my_best_display == "1:31.000"
    assert mugello_dry.rival_best_driver == "FastOne"
    assert mugello_dry.gap_to_rival_ms == -500
    assert mugello_dry.community_display == "1:30.000"
    assert mugello_dry.gap_to_community_ms == 1000
    assert mugello_dry.i_hold_combo_record is True
    assert [point.lap_display for point in mugello_dry.progress] == ["1:33.000", "1:31.000"]

    mugello_rain = next(row for row in summary.track_records if row.track == "Mugello" and row.weather == "rain")
    assert mugello_rain.community_ms is None
    assert mugello_rain.gap_to_community_ms is None
    assert mugello_rain.i_hold_combo_record is False

    tcr = next(row for row in summary.track_records if row.race_class == "TCR")
    assert tcr.community_ms is None
    assert tcr.gap_to_community_ms is None


def test_car_performance_tracks_usage_player_usage_and_dominance_by_combo() -> None:
    rows = build_car_performance(_laps(), gamertag="Bujica89")
    ferrari = next(row for row in rows if row.track == "Mugello" and row.weather == "dry" and row.car == "Ferrari 488")
    lambo = next(row for row in rows if row.car == "Lambo")

    assert ferrari.usage_count == 2
    assert ferrari.player_usage_count == 2
    assert ferrari.session_wins == 1
    assert ferrari.best_display == "1:31.000"
    assert ferrari.gap_to_combo_best_ms == 0
    assert lambo.session_wins == 1
    assert lambo.gap_to_combo_best_ms == 1000

    summary = compute_performance_summary(_laps(), [], gamertag="Bujica89")
    mugello_dry = next(row for row in summary.track_records if row.track == "Mugello" and row.weather == "dry")
    assert mugello_dry.most_used_car == "Ferrari 488"
    assert mugello_dry.dominant_car == "Ferrari 488"


def test_rivals_are_computed_from_shared_image_sessions() -> None:
    summary = compute_performance_summary(_laps(), [], gamertag="Bujica89")

    fast_one = next(row for row in summary.rivals if row.driver == "FastOne")
    assert fast_one.sessions_shared == 2
    assert fast_one.their_best_ms == 91500
    assert fast_one.my_best_in_common_ms == 91000
    assert fast_one.tracks_shared == ["Mugello"]
    assert fast_one.usually_faster is False

    rain_ace = next(row for row in summary.rivals if row.driver == "RainAce")
    assert rain_ace.sessions_shared == 1
    assert rain_ace.usually_faster is True


def test_build_dashboard_preserves_current_records_view_payload() -> None:
    dashboard = build_dashboard(
        _laps(),
        gamertag="Bujica89",
        external_records=[External("Mugello", "A", "Community", "Meta Car", "1:30.000", 90000)],
    )

    assert dashboard.summary is not None
    assert dashboard.cards
    assert dashboard.records
    assert dashboard.car_usage
    assert dashboard.car_strength
    assert dashboard.recent_best
    assert any("Ferrari 488" in row.value for row in dashboard.car_usage)
