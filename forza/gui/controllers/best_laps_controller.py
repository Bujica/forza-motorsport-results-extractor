from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from ...application import DatabaseService, ExternalImportResult, ExternalRecordService
from ...config import AppConfig
from ...domain import LapRowLike, ordered_lap_key
from ...events import EventType, PipelineEvent
from ...output.pdf import generate_pdf
from ...schemas import ExportLap
from ..config_state import ConfigChangeSet
from ...application.gui_read_service import GuiReadService
from ...application.gui_read_service_best_laps import list_external_records


class _GuiBestLapSourceLike(LapRowLike, Protocol):
    id: str
    image_file_id: str | None
    run_id: str | None
    temp_f: float | None
    best_lap: str
    dirty: bool
    source_file: str


class _ExternalBestLapRecordLike(Protocol):
    track: str
    race_class: str
    driver: str
    car: str
    best_lap: str
    best_lap_ms: int
    source: str


@dataclass(frozen=True)
class BestLapRow:
    lap_id: str | None
    image_file_id: str | None
    run_id: str | None
    track: str
    race_class: str
    weather: str
    temp_f: float | None
    driver: str
    car: str
    car_class: str
    best_lap: str
    best_lap_ms: int
    dirty: bool
    source_file: str
    source_type: str = "internal"
    source_label: str = ""
    is_external: bool = False


@dataclass(frozen=True)
class BestLapFilterOptions:
    tracks: list[str]
    race_classes: list[str]
    weather: list[str]
    drivers: list[str]
    cars: list[str]
    dirty_states: list[str]
    source_states: list[str]


class BestLapsController(QObject):
    rows_changed = Signal(object)
    filter_options_changed = Signal(object)
    external_records_imported = Signal()
    action_completed = Signal(str)
    action_failed = Signal(str)

    def __init__(self, *, cfg: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._gamertag = str(getattr(cfg, "gamertag", "") or "").strip().lower()
        self._reader = _reader_for(cfg)
        self._external_records_service = _external_records_service_for(cfg)
        self._all_rows: list[BestLapRow] = []
        self._rows: list[BestLapRow] = []
        self._track: str | None = None
        self._race_class: str | None = None
        self._weather: str | None = None
        self._driver: str | None = None
        self._car: str | None = None
        self._dirty: str | None = "all"
        self._source: str | None = "all"
        self._only_mine = False
        self._loaded = False

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if changes.affects("user.gamertag"):
            self._gamertag = str(getattr(cfg, "gamertag", "") or "").strip().lower()
            if self._loaded:
                self._apply_current_filters()
        if not changes.affects("paths.database_file"):
            return
        self._reader.close()
        self._reader = _reader_for(cfg)
        self._all_rows = []
        self._rows = []
        self._loaded = False
        self.rows_changed.emit(self._rows)
        self.filter_options_changed.emit(BestLapFilterOptions([], [], [], [], [], [], []))

    def close(self) -> None:
        self._reader.close()

    def refresh(
        self,
        track: str | None = "all",
        race_class: str | None = "all",
        weather: str | None = "all",
        driver: str | None = "all",
        car: str | None = "all",
        dirty: str | None = "all",
        source: str | None = "all",
        only_mine: bool = False,
    ) -> None:
        """Apply current filters, loading from DB only when the cache is empty."""
        self._set_filters(track, race_class, weather, driver, car, dirty, source, only_mine)
        if not self._loaded:
            self.reload()
            return
        self._apply_current_filters()

    def reload(self) -> None:
        rows = [_row_from_lap(row) for row in self._reader.list_laps(best_only=True)]
        rows.extend(_row_from_external(row) for row in list_external_records(self._reader))
        self._all_rows = sorted(rows, key=lambda row: ordered_lap_key(row, {}))
        self._loaded = True
        self._apply_current_filters()

    def apply_filters(
        self,
        track: str | None = "all",
        race_class: str | None = "all",
        weather: str | None = "all",
        driver: str | None = "all",
        car: str | None = "all",
        dirty: str | None = "all",
        source: str | None = "all",
        only_mine: bool = False,
    ) -> None:
        self.refresh(track, race_class, weather, driver, car, dirty, source, only_mine)

    def import_external_records(self, path: Path) -> None:
        try:
            with DatabaseService(self._cfg.database_file) as database:
                result = self._external_records_service.import_to_db(database, path)
        except Exception as exc:
            self.action_failed.emit(f"External records import failed: {exc}")
            return
        self.reload()
        self.external_records_imported.emit()
        self.action_completed.emit(_external_import_message(result))

    def generate_pdf(self) -> None:
        if not self._rows:
            self.action_failed.emit("No filtered best laps to generate PDF.")
            return
        pdf_path = Path(self._cfg.pdf_file)
        internal_rows = [_export_lap(row) for row in self._rows if not row.is_external]
        external_rows = [_external_pdf_row(row) for row in self._rows if row.is_external]
        try:
            generate_pdf(
                internal_rows,
                pdf_path,
                self._cfg,
                [],
                external_records=external_rows,
            )
        except Exception as exc:
            self.action_failed.emit(f"Filtered PDF generation failed: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf_path.resolve())))
        self.action_completed.emit(f"Filtered PDF generated: {len(self._rows)} row(s) · {pdf_path}")

    def export_csv(self, destination: Path) -> None:
        if not self._rows:
            self.action_failed.emit("No best laps to export.")
            return
        path = Path(destination)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(_csv_row(self._rows[0]).keys()))
            writer.writeheader()
            for row in self._rows:
                writer.writerow(_csv_row(row))
        self.action_completed.emit(f"Best laps exported: {len(self._rows)} row(s) · {path}")

    def handle_event(self, event: PipelineEvent) -> None:
        if event.type in {EventType.IMAGE_FINISHED, EventType.RUN_FINISHED, EventType.LAP_RECORD_CORRECTED, EventType.REVIEW_CASES_CREATED}:
            self.reload()

    def _set_filters(
        self,
        track: str | None,
        race_class: str | None,
        weather: str | None,
        driver: str | None,
        car: str | None,
        dirty: str | None,
        source: str | None,
        only_mine: bool,
    ) -> None:
        self._track = _none_for_all(track)
        self._race_class = _none_for_all(race_class)
        self._weather = _none_for_all(weather)
        self._driver = _none_for_all(driver)
        self._car = _none_for_all(car)
        self._dirty = dirty or "all"
        self._source = source or "all"
        self._only_mine = bool(only_mine)

    def _apply_current_filters(self) -> None:
        rows = self._apply_filters(self._all_rows)
        self._rows = rows
        self.rows_changed.emit(self._rows)
        self.filter_options_changed.emit(self._filter_options(self._all_rows))

    def _apply_filters(self, rows: list[BestLapRow], *, exclude: str | None = None) -> list[BestLapRow]:
        def keep(row: BestLapRow) -> bool:
            if exclude != "track" and self._track and row.track != self._track:
                return False
            if exclude != "race_class" and self._race_class and row.race_class != self._race_class:
                return False
            if exclude != "weather" and self._weather and row.weather != self._weather:
                return False
            if exclude != "driver" and self._driver and row.driver != self._driver:
                return False
            if exclude != "car" and self._car and row.car != self._car:
                return False
            if exclude != "dirty" and self._dirty == "clean" and row.dirty:
                return False
            if exclude != "dirty" and self._dirty == "dirty" and not row.dirty:
                return False
            if exclude != "source" and self._source == "screenshots" and row.is_external:
                return False
            if exclude != "source" and self._source == "external" and not row.is_external:
                return False
            if self._only_mine and not self._is_mine(row):
                return False
            return True
        return [row for row in rows if keep(row)]

    def _filter_options(self, rows: list[BestLapRow]) -> BestLapFilterOptions:
        return BestLapFilterOptions(
            tracks=_unique(row.track for row in self._apply_filters(rows, exclude="track")),
            race_classes=_unique(row.race_class for row in self._apply_filters(rows, exclude="race_class")),
            weather=_unique(row.weather for row in self._apply_filters(rows, exclude="weather")),
            drivers=_unique(row.driver for row in self._apply_filters(rows, exclude="driver")),
            cars=_unique(row.car for row in self._apply_filters(rows, exclude="car")),
            dirty_states=_dirty_options(self._apply_filters(rows, exclude="dirty")),
            source_states=_source_options(self._apply_filters(rows, exclude="source")),
        )

    def _is_mine(self, row: BestLapRow) -> bool:
        return bool(self._gamertag and row.driver.strip().lower() == self._gamertag)


def _reader_for(cfg: Any) -> GuiReadService:
    return GuiReadService(cfg.database_file)


def _external_records_service_for(cfg: Any) -> ExternalRecordService:
    return ExternalRecordService()


def _row_from_lap(lap: _GuiBestLapSourceLike) -> BestLapRow:
    return BestLapRow(
        lap_id=lap.id,
        image_file_id=lap.image_file_id,
        run_id=lap.run_id,
        track=lap.track,
        race_class=lap.race_class,
        weather=lap.weather,
        temp_f=lap.temp_f,
        driver=lap.driver,
        car=lap.car,
        car_class=lap.race_class,
        best_lap=lap.best_lap,
        best_lap_ms=lap.best_lap_ms,
        dirty=lap.dirty,
        source_file=lap.source_file,
        source_type="internal",
        source_label=lap.source_file,
        is_external=False,
    )


def _row_from_external(record: _ExternalBestLapRecordLike) -> BestLapRow:
    return BestLapRow(
        lap_id=None,
        image_file_id=None,
        run_id=None,
        track=record.track,
        race_class=record.race_class,
        weather="dry",
        temp_f=None,
        driver=record.driver,
        car=record.car,
        car_class=record.race_class,
        best_lap=record.best_lap,
        best_lap_ms=record.best_lap_ms,
        dirty=False,
        source_file=record.source,
        source_type="external",
        source_label=record.source,
        is_external=True,
    )


def _unique(values) -> list[str]:
    return sorted({str(value) for value in values if value})


def _dirty_options(rows: list[BestLapRow]) -> list[str]:
    states = {"dirty" if row.dirty else "clean" for row in rows}
    return [state for state in ("clean", "dirty") if state in states]


def _source_options(rows: list[BestLapRow]) -> list[str]:
    states = {"external" if row.is_external else "screenshots" for row in rows}
    return [state for state in ("screenshots", "external") if state in states]


def _csv_row(row: BestLapRow) -> dict[str, object]:
    return {
        "track": row.track,
        "race_class": row.race_class,
        "weather": row.weather,
        "temp_f": row.temp_f if row.temp_f is not None else "",
        "driver": row.driver,
        "car": row.car,
        "car_class": row.car_class,
        "best_lap": row.best_lap,
        "best_lap_ms": row.best_lap_ms,
        "dirty": row.dirty,
        "source": row.source_label or row.source_file,
        "source_type": row.source_type,
        "source_file": row.source_file,
        "image_file_id": _identity_field(row.image_file_id),
        "lap_id": _identity_field(row.lap_id),
        "run_id": _identity_field(row.run_id),
    }


def _export_lap(row: BestLapRow) -> ExportLap:
    return ExportLap(
        image_file_id=_identity_field(row.image_file_id),
        source_file=row.source_label or row.source_file,
        file_hash=None,
        lap_index=0,
        semantic_name=None,
        race_datetime=None,
        race_date=None,
        image_format=None,
        width_px=None,
        height_px=None,
        track=row.track,
        race_class=row.race_class,
        weather=row.weather,
        temp_f=row.temp_f,
        temp_c=_temp_c(row.temp_f),
        driver=row.driver,
        car=row.car,
        car_class=row.car_class,
        best_lap=row.best_lap,
        best_lap_ms=row.best_lap_ms,
        dirty=row.dirty,
        is_best_lap=True,
    )


def _external_pdf_row(row: BestLapRow) -> dict[str, object]:
    return {
        "track": row.track,
        "race_class": row.race_class,
        "driver": row.driver,
        "car": row.car,
        "best_lap": row.best_lap,
        "best_lap_ms": row.best_lap_ms,
        "source": row.source_label or row.source_file,
    }


def _identity_field(value: str | None) -> str:
    return value or ""


def _temp_c(temp_f: float | None) -> float | None:
    if temp_f is None:
        return None
    return round((float(temp_f) - 32.0) * 5.0 / 9.0, 1)


def _external_import_message(result: ExternalImportResult) -> str:
    parts = [
        f"External records imported: {len(result.records)} record(s) from {result.total_rows} row(s).",
        f"Canonicalized cars: {result.canonicalized_cars}.",
        f"New cars added: {result.new_cars}.",
        f"Unmapped tracks: {result.unmapped_tracks}.",
        f"Invalid laps: {result.invalid_laps}.",
    ]
    if result.new_car_names:
        preview = ", ".join(result.new_car_names[:8])
        suffix = "" if len(result.new_car_names) <= 8 else f", +{len(result.new_car_names) - 8} more"
        parts.append(f"New car list: {preview}{suffix}.")
    if result.ambiguous_cars:
        parts.append(f"Ambiguous cars not added: {result.ambiguous_cars}.")
    return " ".join(parts)


def _none_for_all(value: str | None) -> str | None:
    if value in (None, "", "all"):
        return None
    return value
