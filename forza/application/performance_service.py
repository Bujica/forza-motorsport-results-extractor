from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


class PerformanceLapLike(Protocol):
    id: str
    image_file_id: str
    track: str
    race_class: str
    weather: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int
    dirty: bool
    is_best_lap: bool
    source_file: str
    race_date: object | None


class ExternalLapRecordLike(Protocol):
    track: str
    race_class: str
    weather: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int


@dataclass(frozen=True)
class PerformanceCard:
    title: str
    value: str
    detail: str


@dataclass(frozen=True)
class PerformanceRow:
    primary: str
    secondary: str
    value: str
    detail: str = ""


@dataclass(frozen=True)
class ProgressPoint:
    race_date: date | None
    lap_ms: int
    lap_display: str
    car: str
    session_source: str


@dataclass(frozen=True)
class CarPerformance:
    track: str
    race_class: str
    weather: str
    car: str
    usage_count: int
    player_usage_count: int
    session_wins: int
    best_ms: int | None
    best_display: str | None
    best_driver: str | None
    gap_to_combo_best_ms: int | None
    dominance_score: float


@dataclass(frozen=True)
class TrackRecord:
    track: str
    race_class: str
    weather: str
    my_best_ms: int | None
    my_best_display: str | None
    my_best_car: str | None
    my_best_date: date | None
    rival_best_ms: int | None
    rival_best_display: str | None
    rival_best_driver: str | None
    rival_best_car: str | None
    community_ms: int | None
    community_display: str | None
    community_driver: str | None
    community_car: str | None
    gap_to_rival_ms: int | None
    gap_to_rival_pct: float | None
    gap_to_community_ms: int | None
    gap_to_community_pct: float | None
    i_hold_combo_record: bool
    sessions_raced: int
    last_raced: date | None
    progress: list[ProgressPoint] = field(default_factory=list)
    car_performance: list[CarPerformance] = field(default_factory=list)
    most_used_car: str | None = None
    dominant_car: str | None = None


@dataclass(frozen=True)
class RivalRecord:
    driver: str
    sessions_shared: int
    their_best_ms: int | None
    my_best_in_common_ms: int | None
    tracks_shared: list[str]
    usually_faster: bool


@dataclass(frozen=True)
class PerformanceSummary:
    gamertag: str
    total_sessions: int
    tracks_raced: int
    records_held: int
    closest_to_community_ms: int | None
    closest_to_community_pct: float | None
    community_records_loaded: int
    community_records_comparable: int
    community_records_matched: int
    most_improved_track: str | None
    most_improved_delta_ms: int | None
    track_records: list[TrackRecord]
    rivals: list[RivalRecord]
    available_tracks: list[str]
    available_classes: list[str]


@dataclass(frozen=True)
class PerformanceDashboard:
    cards: list[PerformanceCard]
    records: list[PerformanceRow]
    strengths: list[PerformanceRow]
    improvement_targets: list[PerformanceRow]
    car_usage: list[PerformanceRow]
    car_strength: list[PerformanceRow]
    recent_best: list[PerformanceRow]
    car_performance: list[CarPerformance]
    summary: PerformanceSummary | None = None


def compute_performance_summary(
    laps: list[PerformanceLapLike],
    external_records: list[ExternalLapRecordLike],
    *,
    gamertag: str,
) -> PerformanceSummary:
    """Compute player-centric performance analytics from already-loaded rows.

    The service is pure application logic: no Qt imports, no database access, and
    no filesystem access. Community records imported from the spreadsheet are
    treated as dry-only and are not applied to TCR.
    """
    player = _normalise_driver(gamertag)
    clean_laps = [lap for lap in laps if not lap.dirty]
    player_laps = [lap for lap in clean_laps if player and _normalise_driver(lap.driver) == player]
    player_session_ids = {_session_key(lap) for lap in player_laps}
    player_session_laps = [
        lap for lap in clean_laps if _session_key(lap) in player_session_ids
    ] if player_session_ids else []
    player_laps_by_combo: dict[tuple[str, str, str], list[PerformanceLapLike]] = defaultdict(list)
    session_laps_by_combo: dict[tuple[str, str, str], list[PerformanceLapLike]] = defaultdict(list)
    for lap in player_laps:
        player_laps_by_combo[_combo_key(lap)].append(lap)
    for lap in player_session_laps:
        session_laps_by_combo[_combo_key(lap)].append(lap)

    external_by_key = _external_record_lookup(external_records)
    track_records: list[TrackRecord] = []
    for key, my_group in player_laps_by_combo.items():
        track, race_class, weather = key
        combo_group = session_laps_by_combo.get(key, [])
        my_best = min(my_group, key=lambda lap: (lap.best_lap_ms, _race_date_sort_key(_lap_date(lap)), lap.car.lower()))
        rival_group = [lap for lap in combo_group if _normalise_driver(lap.driver) != player]
        rival_best = min(rival_group, key=lambda lap: (lap.best_lap_ms, lap.driver.lower(), lap.car.lower())) if rival_group else None
        community = _community_record_for_combo(external_by_key, track=track, race_class=race_class, weather=weather)
        progress = _progress_points(my_group)
        car_rows = build_car_performance(combo_group, gamertag=gamertag)
        most_used = min(car_rows, key=_most_used_car_sort_key) if car_rows else None
        dominant = min(car_rows, key=_dominant_car_sort_key) if car_rows else None
        gap_to_rival = (my_best.best_lap_ms - rival_best.best_lap_ms) if rival_best is not None else None
        gap_to_rival_pct = _gap_pct(gap_to_rival, rival_best.best_lap_ms if rival_best is not None else None)
        gap_to_community = (my_best.best_lap_ms - community.best_lap_ms) if community is not None else None
        gap_to_community_pct = _gap_pct(gap_to_community, community.best_lap_ms if community is not None else None)
        sessions = {_session_key(lap) for lap in my_group}
        dates = [_lap_date(lap) for lap in my_group if _lap_date(lap) is not None]
        track_records.append(
            TrackRecord(
                track=track,
                race_class=race_class,
                weather=weather,
                my_best_ms=my_best.best_lap_ms,
                my_best_display=my_best.best_lap,
                my_best_car=my_best.car,
                my_best_date=_lap_date(my_best),
                rival_best_ms=rival_best.best_lap_ms if rival_best is not None else None,
                rival_best_display=rival_best.best_lap if rival_best is not None else None,
                rival_best_driver=rival_best.driver if rival_best is not None else None,
                rival_best_car=rival_best.car if rival_best is not None else None,
                community_ms=community.best_lap_ms if community is not None else None,
                community_display=community.best_lap if community is not None else None,
                community_driver=community.driver if community is not None else None,
                community_car=community.car if community is not None else None,
                gap_to_rival_ms=gap_to_rival,
                gap_to_rival_pct=gap_to_rival_pct,
                gap_to_community_ms=gap_to_community,
                gap_to_community_pct=gap_to_community_pct,
                i_hold_combo_record=rival_best is None or my_best.best_lap_ms <= rival_best.best_lap_ms,
                sessions_raced=len(sessions),
                last_raced=max(dates) if dates else None,
                progress=progress,
                car_performance=car_rows,
                most_used_car=most_used.car if most_used is not None else None,
                dominant_car=dominant.car if dominant is not None else None,
            )
        )

    track_records.sort(key=_track_record_sort_key)
    rivals = _rival_records(player_session_laps, player_laps, gamertag=gamertag)
    most_improved_track, most_improved_delta = _most_improved(track_records)
    community_gap_records = [
        record
        for record in track_records
        if record.gap_to_community_ms is not None and record.gap_to_community_pct is not None
    ]
    closest_community_record = (
        min(
            community_gap_records,
            key=lambda record: (
                abs(record.gap_to_community_pct or 0.0),
                abs(record.gap_to_community_ms or 0),
                record.gap_to_community_ms or 0,
            ),
        )
        if community_gap_records
        else None
    )
    community_records_comparable = sum(
        1
        for track, race_class, weather in external_by_key
        if weather == "dry" and race_class.upper() != "TCR"
    )
    community_records_matched = sum(1 for record in track_records if record.community_ms is not None)
    return PerformanceSummary(
        gamertag=gamertag,
        total_sessions=len(player_session_ids),
        tracks_raced=len({(record.track, record.race_class, record.weather) for record in track_records}),
        records_held=sum(1 for record in track_records if record.i_hold_combo_record),
        closest_to_community_ms=closest_community_record.gap_to_community_ms if closest_community_record is not None else None,
        closest_to_community_pct=closest_community_record.gap_to_community_pct if closest_community_record is not None else None,
        community_records_loaded=len(external_records),
        community_records_comparable=community_records_comparable,
        community_records_matched=community_records_matched,
        most_improved_track=most_improved_track,
        most_improved_delta_ms=most_improved_delta,
        track_records=track_records,
        rivals=rivals,
        available_tracks=sorted({record.track for record in track_records}),
        available_classes=sorted({record.race_class for record in track_records}),
    )


def build_dashboard(
    laps: list[PerformanceLapLike],
    *,
    gamertag: str = "",
    external_records: list[ExternalLapRecordLike] | None = None,
) -> PerformanceDashboard:
    """Build the current Records screen dashboard from the new summary model."""
    external_records = external_records or []
    clean = [lap for lap in laps if not lap.dirty]
    competitive = clean or laps
    best_laps = [lap for lap in competitive if lap.is_best_lap]
    summary = compute_performance_summary(laps, external_records, gamertag=gamertag)
    all_car_performance = [
        car
        for record in summary.track_records
        for car in record.car_performance
    ]
    cards = [
        PerformanceCard("Sessions", str(summary.total_sessions), f"{summary.tracks_raced} track/class/weather combo(s)"),
        PerformanceCard("Records held", str(summary.records_held), "fastest in shared sessions"),
        PerformanceCard("Closest community gap", _gap_value(summary.closest_to_community_ms, summary.closest_to_community_pct), _community_coverage_detail(summary)),
        PerformanceCard(
            "Most improved",
            _gap_value(-summary.most_improved_delta_ms if summary.most_improved_delta_ms is not None else None),
            summary.most_improved_track or "No progression data",
        ),
        PerformanceCard(
            "Top rival",
            summary.rivals[0].driver if summary.rivals else "—",
            f"{summary.rivals[0].sessions_shared} shared session(s)" if summary.rivals else "No shared rivals",
        ),
    ]
    return PerformanceDashboard(
        cards=cards,
        records=_track_record_rows(summary.track_records)[:12],
        strengths=_record_held_rows(summary.track_records)[:8] or _strongest_tracks(best_laps or competitive)[:8],
        improvement_targets=_improvement_rows(summary.track_records)[:8],
        car_usage=_car_usage(all_car_performance)[:10],
        car_strength=_strongest_cars(all_car_performance)[:10],
        recent_best=_recent_progress_rows(summary.track_records)[:8],
        car_performance=all_car_performance,
        summary=summary,
    )


def build_car_performance(laps: list[PerformanceLapLike], *, gamertag: str = "") -> list[CarPerformance]:
    player = _normalise_driver(gamertag)
    grouped: dict[tuple[str, str, str], list[PerformanceLapLike]] = defaultdict(list)
    for lap in laps:
        if lap.dirty:
            continue
        grouped[_combo_key(lap)].append(lap)

    rows: list[CarPerformance] = []
    for (track, race_class, weather), group in grouped.items():
        if not group:
            continue
        combo_best_ms = min(lap.best_lap_ms for lap in group)
        laps_by_car: dict[str, list[PerformanceLapLike]] = defaultdict(list)
        session_laps: dict[str, list[PerformanceLapLike]] = defaultdict(list)
        for lap in group:
            laps_by_car[lap.car].append(lap)
            session_laps[_session_key(lap)].append(lap)

        session_wins: Counter[str] = Counter()
        for session_group in session_laps.values():
            winner = min(session_group, key=lambda lap: (lap.best_lap_ms, lap.car.lower(), lap.driver.lower()))
            session_wins[winner.car] += 1

        for car, car_laps in laps_by_car.items():
            best = min(car_laps, key=lambda lap: (lap.best_lap_ms, lap.driver.lower()))
            gap = best.best_lap_ms - combo_best_ms
            usage_count = len(car_laps)
            player_usage_count = sum(1 for lap in car_laps if player and _normalise_driver(lap.driver) == player)
            wins = session_wins.get(car, 0)
            rows.append(
                CarPerformance(
                    track=track,
                    race_class=race_class,
                    weather=weather,
                    car=car,
                    usage_count=usage_count,
                    player_usage_count=player_usage_count,
                    session_wins=wins,
                    best_ms=best.best_lap_ms,
                    best_display=best.best_lap,
                    best_driver=best.driver,
                    gap_to_combo_best_ms=gap,
                    dominance_score=_dominance_score(wins=wins, gap_ms=gap, usage_count=usage_count),
                )
            )
    return sorted(rows, key=lambda row: (_combo_label(row).lower(), _dominant_car_sort_key(row)))


def _community_coverage_detail(summary: PerformanceSummary) -> str:
    if summary.community_records_comparable <= 0:
        return "no Best Laps community records loaded"
    return (
        f"{summary.community_records_matched}/{summary.community_records_comparable} "
        "Best Laps community record(s) matched"
    )


def _track_record_rows(records: list[TrackRecord]) -> list[PerformanceRow]:
    rows: list[PerformanceRow] = []
    for record in records:
        rows.append(
            PerformanceRow(
                primary=f"{record.track} · {record.race_class}",
                secondary=f"{record.weather} · {record.sessions_raced} session(s)",
                value=record.my_best_display or "—",
                detail=(
                    f"rival {_gap_value(record.gap_to_rival_ms, record.gap_to_rival_pct)} · "
                    f"community {_community_detail(record)} · "
                    f"dominant {record.dominant_car or '—'}"
                ),
            )
        )
    return rows


def _record_held_rows(records: list[TrackRecord]) -> list[PerformanceRow]:
    return [
        PerformanceRow(
            primary=f"{record.track} · {record.race_class}",
            secondary=record.weather,
            value=record.my_best_display or "—",
            detail=f"{record.my_best_car or '—'} · {record.sessions_raced} session(s)",
        )
        for record in records
        if record.i_hold_combo_record
    ]


def _improvement_rows(records: list[TrackRecord]) -> list[PerformanceRow]:
    rows_with_sort: list[tuple[tuple[float, int], PerformanceRow]] = []
    for record in records:
        if record.gap_to_community_ms is not None:
            target_gap = record.gap_to_community_ms
            target_pct = record.gap_to_community_pct
        else:
            target_gap = record.gap_to_rival_ms
            target_pct = record.gap_to_rival_pct
        if target_gap is None:
            continue
        rows_with_sort.append(
            (
                _opportunity_sort_key(target_gap, target_pct),
                PerformanceRow(
                    primary=f"{record.track} · {record.race_class}",
                    secondary=record.weather,
                    value=_gap_value(target_gap, target_pct),
                    detail=f"mine {record.my_best_display or '—'} · community {_community_detail(record)}",
                ),
            )
        )
    return [row for _key, row in sorted(rows_with_sort, key=lambda item: item[0])]


def _recent_progress_rows(records: list[TrackRecord]) -> list[PerformanceRow]:
    rows: list[PerformanceRow] = []
    for record in records:
        if not record.progress:
            continue
        latest = max(record.progress, key=lambda point: (_race_date_sort_key(point.race_date), -point.lap_ms))
        best_ms = record.my_best_ms
        delta = latest.lap_ms - best_ms if best_ms is not None else None
        rows.append(
            PerformanceRow(
                primary=f"{record.track} · {record.race_class}",
                secondary=f"{record.weather} · {latest.race_date or 'no date'}",
                value=latest.lap_display,
                detail=f"{latest.car} · {_gap_value(delta)} vs best",
            )
        )
    return sorted(rows, key=lambda row: row.secondary, reverse=True)


def _strongest_tracks(laps: list[PerformanceLapLike]) -> list[PerformanceRow]:
    counts = Counter(lap.track for lap in laps if lap.is_best_lap)
    return [
        PerformanceRow(track, "best-lap groups", f"{count} record(s)")
        for track, count in counts.most_common()
    ]


def _car_usage(car_performance: list[CarPerformance]) -> list[PerformanceRow]:
    best_by_combo: dict[tuple[str, str, str], CarPerformance] = {}
    for row in car_performance:
        key = (row.track, row.race_class, row.weather)
        current = best_by_combo.get(key)
        if current is None or _most_used_car_sort_key(row) < _most_used_car_sort_key(current):
            best_by_combo[key] = row
    return [
        PerformanceRow(
            primary=f"{row.track} · {row.race_class}",
            secondary=f"{row.weather} · most used",
            value=f"{row.car} ({row.usage_count})",
            detail=f"player {row.player_usage_count} · best {row.best_display or '—'}",
        )
        for row in sorted(best_by_combo.values(), key=lambda item: (_combo_label(item).lower(), item.car.lower()))
    ]


def _strongest_cars(car_performance: list[CarPerformance]) -> list[PerformanceRow]:
    best_by_combo: dict[tuple[str, str, str], CarPerformance] = {}
    for row in car_performance:
        key = (row.track, row.race_class, row.weather)
        current = best_by_combo.get(key)
        if current is None or _dominant_car_sort_key(row) < _dominant_car_sort_key(current):
            best_by_combo[key] = row
    return [
        PerformanceRow(
            primary=f"{row.track} · {row.race_class}",
            secondary=f"{row.weather} · {row.car}",
            value=f"{row.session_wins} session win(s)",
            detail=f"best {row.best_display or '—'} · {row.best_driver or '—'} · {row.usage_count} lap(s)",
        )
        for row in sorted(best_by_combo.values(), key=lambda item: (_combo_label(item).lower(), _dominant_car_sort_key(item)))
    ]


def _external_record_lookup(external_records: list[ExternalLapRecordLike]) -> dict[tuple[str, str, str], ExternalLapRecordLike]:
    lookup: dict[tuple[str, str, str], ExternalLapRecordLike] = {}
    for record in external_records:
        weather = _normalise_weather(getattr(record, "weather", None) or "dry")
        key = (record.track, record.race_class, weather)
        current = lookup.get(key)
        if current is None or record.best_lap_ms < current.best_lap_ms:
            lookup[key] = record
    return lookup


def _community_record_for_combo(
    external_by_key: dict[tuple[str, str, str], ExternalLapRecordLike],
    *,
    track: str,
    race_class: str,
    weather: str,
) -> ExternalLapRecordLike | None:
    if weather != "dry" or race_class.upper() == "TCR":
        return None
    return external_by_key.get((track, race_class, "dry"))


def _rival_records(
    player_session_laps: list[PerformanceLapLike],
    player_laps: list[PerformanceLapLike],
    *,
    gamertag: str,
) -> list[RivalRecord]:
    player = _normalise_driver(gamertag)
    if not player:
        return []
    player_by_session_combo: dict[tuple[str, tuple[str, str, str]], list[PerformanceLapLike]] = defaultdict(list)
    for lap in player_laps:
        player_by_session_combo[(_session_key(lap), _combo_key(lap))].append(lap)

    rival_sessions: dict[str, set[str]] = defaultdict(set)
    rival_tracks: dict[str, set[str]] = defaultdict(set)
    rival_laps: dict[str, list[PerformanceLapLike]] = defaultdict(list)
    comparison_counts: Counter[str] = Counter()
    faster_counts: Counter[str] = Counter()
    my_common_best: dict[str, int] = {}

    for lap in player_session_laps:
        driver_key = _normalise_driver(lap.driver)
        if not driver_key or driver_key == player:
            continue
        session_key = _session_key(lap)
        combo_key = _combo_key(lap)
        player_context = player_by_session_combo.get((session_key, combo_key), [])
        if not player_context:
            continue
        my_best = min(player_context, key=lambda item: item.best_lap_ms)
        rival_sessions[lap.driver].add(session_key)
        rival_tracks[lap.driver].add(lap.track)
        rival_laps[lap.driver].append(lap)
        comparison_counts[lap.driver] += 1
        if lap.best_lap_ms < my_best.best_lap_ms:
            faster_counts[lap.driver] += 1
        current_my_best = my_common_best.get(lap.driver)
        if current_my_best is None or my_best.best_lap_ms < current_my_best:
            my_common_best[lap.driver] = my_best.best_lap_ms

    rows: list[RivalRecord] = []
    for driver, laps in rival_laps.items():
        their_best = min(laps, key=lambda lap: lap.best_lap_ms)
        comparisons = comparison_counts[driver]
        rows.append(
            RivalRecord(
                driver=driver,
                sessions_shared=len(rival_sessions[driver]),
                their_best_ms=their_best.best_lap_ms,
                my_best_in_common_ms=my_common_best.get(driver),
                tracks_shared=sorted(rival_tracks[driver]),
                usually_faster=bool(comparisons and faster_counts[driver] > comparisons / 2),
            )
        )
    return sorted(rows, key=lambda row: (-row.sessions_shared, row.driver.lower()))


def _progress_points(laps: list[PerformanceLapLike]) -> list[ProgressPoint]:
    points = [
        ProgressPoint(
            race_date=_lap_date(lap),
            lap_ms=lap.best_lap_ms,
            lap_display=lap.best_lap,
            car=lap.car,
            session_source=getattr(lap, "source_file", "") or getattr(lap, "image_file_id", ""),
        )
        for lap in laps
    ]
    return sorted(points, key=lambda point: (_race_date_sort_key(point.race_date), point.lap_ms, point.car.lower()))


def _most_improved(records: list[TrackRecord]) -> tuple[str | None, int | None]:
    best_label: str | None = None
    best_delta: int | None = None
    for record in records:
        dated = [point for point in record.progress if point.race_date is not None]
        points = dated or record.progress
        if len(points) < 2:
            continue
        ordered = sorted(points, key=lambda point: (_race_date_sort_key(point.race_date), point.lap_ms))
        first = ordered[0]
        best = min(ordered, key=lambda point: point.lap_ms)
        delta = first.lap_ms - best.lap_ms
        if delta <= 0:
            continue
        if best_delta is None or delta > best_delta:
            best_delta = delta
            best_label = f"{record.track} · {record.race_class} · {record.weather}"
    return best_label, best_delta


def _track_record_sort_key(record: TrackRecord) -> tuple[int, float, int, str, str, str]:
    community_missing = 1 if record.gap_to_community_pct is None else 0
    community_gap_pct = abs(record.gap_to_community_pct) if record.gap_to_community_pct is not None else 10**12
    community_gap_ms = abs(record.gap_to_community_ms) if record.gap_to_community_ms is not None else 10**12
    return (community_missing, community_gap_pct, community_gap_ms, record.track.lower(), record.race_class.lower(), record.weather.lower())


def _combo_key(lap: PerformanceLapLike) -> tuple[str, str, str]:
    return (lap.track, lap.race_class, _normalise_weather(lap.weather))


def _combo_label(row: CarPerformance) -> str:
    return f"{row.track} · {row.race_class} · {row.weather}"


def _session_key(lap: PerformanceLapLike) -> str:
    image_file_id = getattr(lap, "image_file_id", None)
    if image_file_id:
        return str(image_file_id)
    lap_id = getattr(lap, "id", None)
    return f"lap:{lap_id or id(lap)}"


def _lap_date(lap: PerformanceLapLike) -> date | None:
    value = getattr(lap, "race_date", None)
    return value if isinstance(value, date) else None


def _race_date_sort_key(value: date | None) -> date:
    return value or date.min


def _normalise_driver(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalise_weather(value: str | None) -> str:
    return str(value or "unknown").strip().lower() or "unknown"


def _community_detail(record: TrackRecord) -> str:
    if record.race_class.upper() == "TCR":
        return "no TCR community record"
    if record.weather != "dry":
        return "not comparable"
    return record.community_display or "no data"


def _gap_value(value_ms: int | None, value_pct: float | None = None) -> str:
    if value_ms is None:
        return "—"
    seconds = value_ms / 1000
    if value_pct is None:
        return f"{seconds:+.3f}s"
    return f"{seconds:+.3f}s ({value_pct:+.2f}%)"


def _gap_pct(value_ms: int | None, reference_ms: int | None) -> float | None:
    if value_ms is None or reference_ms is None or reference_ms <= 0:
        return None
    return (value_ms / reference_ms) * 100.0


def _opportunity_sort_key(value_ms: int, value_pct: float | None) -> tuple[float, int]:
    pct = value_pct if value_pct is not None else 0.0
    positive_pct = pct if pct > 0 else -10**12
    positive_ms = value_ms if value_ms > 0 else -10**12
    return (-positive_pct, -positive_ms)


def _dominance_score(*, wins: int, gap_ms: int, usage_count: int) -> float:
    return (wins * 1000.0) - (gap_ms / 1000.0) + min(usage_count, 10) / 100.0


def _dominant_car_sort_key(row: CarPerformance) -> tuple[int, int, int, str]:
    best_ms = row.best_ms if row.best_ms is not None else 10**12
    return (-row.session_wins, best_ms, -row.usage_count, row.car.lower())


def _most_used_car_sort_key(row: CarPerformance) -> tuple[int, int, int, str]:
    best_ms = row.best_ms if row.best_ms is not None else 10**12
    return (-row.usage_count, -row.player_usage_count, best_ms, row.car.lower())
