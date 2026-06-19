from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from ..models import ExtractionResultEntity, LapRecordEntity, ReferenceCarEntity, ReferenceTrackEntity, ImageFileEntity
from ...domain.lap import strip_dirty_symbol
from ...domain.review_rules import driver_name_review_trigger, track_suggestions
from ...schemas import ExportLap, ExtractionResult, LapRecord, RaceClass, ReviewCase
from ..review_identity import case_business_key
from .frontier import FrontierCalculator
from .run_inputs import ensure_process_run_input


@dataclass(frozen=True)
class _ReviewReferenceContext:
    known_cars: set[str]
    known_tracks: list[str]
    known_track_keys: set[str]
    valid_classes: set[str]


class _ReviewCaseCollector:
    def __init__(self, *, known_tracks: list[str], valid_classes: set[str]):
        self._known_tracks = known_tracks
        self._valid_classes = valid_classes
        self._cases: list[ReviewCase] = []
        self._seen: set[str] = set()

    def append(
        self,
        row: LapRecordEntity,
        reason: str,
        *,
        trigger: str,
        model_value: str | None = None,
        per_image: bool = False,
    ) -> None:
        case = ReviewCase(
            reason=reason,
            source_file=row.source_file,
            track=row.track,
            race_class=_review_case_race_class(row.race_class, self._valid_classes),
            weather=row.weather,
            temp_f=row.temp_f,
            driver=None if per_image else row.driver,
            car=None if per_image else row.car,
            best_lap=None if per_image else row.best_lap,
            image_file_id=row.image_file_id,
            run_id=row.run_id,
            extraction_result_id=row.extraction_result_id,
            lap_record_id=None if per_image else row.id,
            lap_index=None if per_image else row.lap_index,
            trigger=trigger,
            model_value=model_value,
            track_suggestions=track_suggestions(row.track, self._known_tracks)
            if reason == "track"
            else [],
        )
        business_key = case_business_key(case)
        if business_key in self._seen:
            return
        self._seen.add(business_key)
        self._cases.append(case)

    def numbered_cases(self) -> list[ReviewCase]:
        for index, case in enumerate(self._cases, start=1):
            case.case_number = index
        return self._cases


def _review_case_race_class(value: str | None, valid_classes: set[str]) -> str:
    text = str(value or "")
    return text if text in valid_classes else "Unknown"


def _append_row_review_candidates(
    row: LapRecordEntity,
    *,
    context: _ReviewReferenceContext,
    append: Callable[..., None],
) -> None:
    # Dirty-lap review is output-impacting only when the lap is visible
    # in Best Laps. Non-best dirty laps are kept as model facts without
    # creating low-value review queue noise.
    if row.dirty and row.is_best_lap:
        append(row, "dirty_lap", trigger="model_marked_dirty", model_value="true")
    if str(row.weather or "").lower() == "unknown":
        append(row, "weather", trigger="weather_unknown", model_value=row.weather, per_image=True)
    if not row.track or row.track == "Unknown":
        append(row, "track", trigger="track_unknown", model_value=row.track, per_image=True)
    if "ambiguous" in str(row.track or "").lower():
        append(row, "track", trigger="track_unresolved", model_value=row.track, per_image=True)
    if context.known_track_keys and row.track and str(row.track).casefold() not in context.known_track_keys:
        append(row, "track", trigger="track_not_in_reference", model_value=row.track, per_image=True)
    if row.race_class == "Unknown":
        append(row, "race_class", trigger="class_unknown", model_value=row.race_class, per_image=True)
    elif str(row.race_class or "") not in context.valid_classes:
        append(row, "race_class", trigger="class_invalid", model_value=row.race_class, per_image=True)
    driver_trigger = driver_name_review_trigger(row.driver)
    if driver_trigger:
        append(row, "driver_name", trigger=driver_trigger, model_value=row.driver)
    if not str(row.car or "").strip():
        append(row, "car", trigger="car_empty", model_value=row.car)
    elif context.known_cars and row.car.strip().casefold() not in context.known_cars:
        append(row, "car", trigger="car_not_in_reference", model_value=row.car)


def _append_rain_time_review_candidates(
    rows: list[LapRecordEntity],
    *,
    append: Callable[..., None],
) -> None:
    best_rows = [row for row in rows if row.is_best_lap]
    best_by_key: dict[tuple[str, str, str], int] = {}
    for row in best_rows:
        key = (row.track, row.race_class, row.weather)
        current = best_by_key.get(key)
        if current is None or row.best_lap_ms < current:
            best_by_key[key] = row.best_lap_ms
    for row in best_rows:
        if row.weather != "rain":
            continue
        best_rain = best_by_key.get((row.track, row.race_class, "rain"))
        best_dry = best_by_key.get((row.track, row.race_class, "dry"))
        if best_rain is not None and best_dry is not None and best_rain < best_dry:
            append(row, "weather", trigger="rain_time_suspicious", model_value=row.weather, per_image=True)


class LapRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_result(
        self,
        result: ExtractionResult,
        *,
        run_id: str,
        image_file_id: str,
        extraction_result_id: str | None = None,
    ) -> list[LapRecordEntity]:
        if result.session is None:
            return []
        if extraction_result_id is None:
            existing_result = self.session.exec(
                select(ExtractionResultEntity).where(
                    ExtractionResultEntity.run_id == run_id,
                    ExtractionResultEntity.image_file_id == image_file_id,
                )
            ).first()
            if existing_result is None:
                run_input_id = ensure_process_run_input(
                    self.session,
                    result,
                    run_id=run_id,
                    image_file_id=image_file_id,
                )
                existing_result = ExtractionResultEntity(
                    id=uuid4().hex,
                    run_id=run_id,
                    run_input_id=run_input_id,
                    image_file_id=image_file_id,
                    status=str(result.status),
                )
                self.session.add(existing_result)
                self.session.flush()
            extraction_result_id = existing_result.id

        race_session = result.session
        entities: list[LapRecordEntity] = []
        for lap_index, entry in enumerate(race_session.entries):
            existing = self.session.exec(
                select(LapRecordEntity).where(
                    LapRecordEntity.extraction_result_id == extraction_result_id,
                    LapRecordEntity.lap_index == lap_index,
                )
            ).first()
            if existing is not None:
                continue
            entity = LapRecordEntity(
                id=uuid4().hex,
                extraction_result_id=extraction_result_id,
                run_id=run_id,
                image_file_id=image_file_id,
                source_file=result.source_file,
                lap_index=lap_index,
                track=race_session.track,
                race_class=str(race_session.race_class),
                weather=str(race_session.weather),
                temp_f=race_session.temp_f,
                temp_c=race_session.temp_c,
                driver=entry.driver,
                driver_normalized=str(entry.driver or "").casefold(),
                car=entry.car,
                car_normalized=str(entry.car or "").casefold(),
                best_lap=strip_dirty_symbol(entry.best_lap),
                best_lap_ms=int(entry.best_lap_ms or 0),
                dirty=entry.dirty,
                raw_lap_json={
                    "model_best_lap": entry.best_lap,
                },
            )
            entity.track_normalized = str(entity.track or "").casefold()
            self.session.add(entity)
            entities.append(entity)
        return entities

    def list_by_run(self, run_id: str) -> list[LapRecordEntity]:
        return list(
            self.session.exec(
                select(LapRecordEntity)
                .where(LapRecordEntity.run_id == run_id)
                .order_by(LapRecordEntity.image_file_id, LapRecordEntity.lap_index)
            )
        )

    def for_image_file(self, image_file_id: str) -> list[LapRecordEntity]:
        return list(
            self.session.exec(
                select(LapRecordEntity)
                .where(LapRecordEntity.image_file_id == image_file_id)
                .order_by(LapRecordEntity.created_at.desc(), LapRecordEntity.lap_index)
            )
        )

    def list_review_candidates(self) -> list[LapRecordEntity]:
        return list(
            self.session.exec(
                select(LapRecordEntity)
                .where(LapRecordEntity.dirty == True)  # noqa: E712
                .order_by(LapRecordEntity.created_at.asc())
            )
        )

    def list_export_rows(self, *, run_id: str | None = None, best_only: bool = False) -> list[LapRecordEntity]:
        query = select(LapRecordEntity)
        if run_id is not None:
            query = query.where(LapRecordEntity.run_id == run_id)
        if best_only:
            query = query.where(LapRecordEntity.is_best_lap == True)  # noqa: E712
        return list(
            self.session.exec(
                query.order_by(
                    LapRecordEntity.track,
                    LapRecordEntity.race_class,
                    LapRecordEntity.driver,
                    LapRecordEntity.best_lap_ms,
                )
            )
        )

    def query_review_candidates(self, *, run_id: str | None = None) -> list[ReviewCase]:
        """Detect review candidates from persisted lap rows.

        The output is keyed by stable row/image identifiers so the review
        repository can preserve user decisions while refreshing open cases.
        """
        context = self._review_reference_context()
        rows = self._review_candidate_rows(run_id=run_id, context=context)
        collector = _ReviewCaseCollector(
            known_tracks=context.known_tracks,
            valid_classes=context.valid_classes,
        )

        for row in rows:
            _append_row_review_candidates(row, context=context, append=collector.append)
        _append_rain_time_review_candidates(rows, append=collector.append)

        return collector.numbered_cases()

    def _review_candidate_rows(
        self,
        *,
        run_id: str | None = None,
        context: _ReviewReferenceContext,
    ) -> list[LapRecordEntity]:
        candidate_ids = self._review_candidate_row_ids(run_id=run_id, context=context)
        if not candidate_ids:
            return []
        query = select(LapRecordEntity).where(LapRecordEntity.id.in_(candidate_ids))
        if run_id is not None:
            query = query.where(LapRecordEntity.run_id == run_id)
        return list(
            self.session.exec(
                query.order_by(
                    LapRecordEntity.created_at.asc(),
                    LapRecordEntity.image_file_id.asc(),
                    LapRecordEntity.lap_index.asc(),
                    LapRecordEntity.id.asc(),
                )
            )
        )

    def _review_candidate_row_ids(
        self,
        *,
        run_id: str | None = None,
        context: _ReviewReferenceContext,
    ) -> set[str]:
        candidate_ids = self._sql_review_candidate_row_ids(run_id=run_id, context=context)
        candidate_ids.update(self._driver_review_candidate_row_ids(run_id=run_id))
        return candidate_ids

    def _sql_review_candidate_row_ids(
        self,
        *,
        run_id: str | None = None,
        context: _ReviewReferenceContext,
    ) -> set[str]:
        query = select(LapRecordEntity.id).where(
            self._base_review_candidate_condition(context=context)
        )
        if run_id is not None:
            query = query.where(LapRecordEntity.run_id == run_id)
        return {str(row_id) for row_id in self.session.exec(query).all()}

    def _driver_review_candidate_row_ids(self, *, run_id: str | None = None) -> set[str]:
        query = select(LapRecordEntity.id, LapRecordEntity.driver)
        if run_id is not None:
            query = query.where(LapRecordEntity.run_id == run_id)
        return {
            str(row_id)
            for row_id, driver in self.session.exec(query).all()
            if driver_name_review_trigger(driver)
        }

    def _base_review_candidate_condition(self, *, context: _ReviewReferenceContext):
        conditions = [
            and_(LapRecordEntity.dirty == True, LapRecordEntity.is_best_lap == True),  # noqa: E712
            func.lower(LapRecordEntity.weather) == "unknown",
            LapRecordEntity.track.is_(None),
            func.trim(LapRecordEntity.track) == "",
            LapRecordEntity.track == "Unknown",
            func.lower(LapRecordEntity.track).like("%ambiguous%"),
            LapRecordEntity.race_class.is_(None),
            LapRecordEntity.race_class == "Unknown",
            ~LapRecordEntity.race_class.in_(sorted(context.valid_classes)),
            LapRecordEntity.car.is_(None),
            func.trim(LapRecordEntity.car) == "",
            and_(
                LapRecordEntity.is_best_lap == True,  # noqa: E712
                func.lower(LapRecordEntity.weather).in_(["dry", "rain"]),
            ),
        ]
        if context.known_track_keys:
            conditions.append(
                and_(
                    LapRecordEntity.track.is_not(None),
                    func.trim(LapRecordEntity.track) != "",
                    func.lower(LapRecordEntity.track).notin_(sorted(context.known_track_keys)),
                )
            )
        if context.known_cars:
            conditions.append(
                and_(
                    LapRecordEntity.car.is_not(None),
                    func.trim(LapRecordEntity.car) != "",
                    func.lower(func.trim(LapRecordEntity.car)).notin_(sorted(context.known_cars)),
                )
            )
        return or_(*conditions)

    def _review_reference_context(self) -> _ReviewReferenceContext:
        known_cars = {
            row.name.casefold()
            for row in self.session.exec(select(ReferenceCarEntity)).all()
        }
        known_tracks = [
            row.name
            for row in self.session.exec(
                select(ReferenceTrackEntity).order_by(ReferenceTrackEntity.name.collate("NOCASE"))
            ).all()
        ]
        return _ReviewReferenceContext(
            known_cars=known_cars,
            known_tracks=known_tracks,
            known_track_keys={row.casefold() for row in known_tracks},
            valid_classes={str(item) for item in RaceClass},
        )

    def export_flat(self, *, run_id: str | None = None, best_only: bool = False) -> list[ExportLap]:
        rows = self.list_export_rows(run_id=run_id, best_only=best_only)
        image_ids = {row.image_file_id for row in rows}
        images = {
            image.id: image
            for image in self.session.exec(
                select(ImageFileEntity).where(ImageFileEntity.id.in_(image_ids))
            ).all()
        } if image_ids else {}
        flat: list[ExportLap] = []
        for row in rows:
            image = images.get(row.image_file_id)
            source_file = (
                image.semantic_name or image.current_name
                if image is not None
                else row.source_file
            )
            flat.append(
                ExportLap(
                    image_file_id=row.image_file_id,
                    source_file=source_file,
                    file_hash=image.file_hash if image is not None else None,
                    lap_index=row.lap_index,
                    semantic_name=image.semantic_name if image is not None else None,
                    race_datetime=image.race_datetime if image is not None else None,
                    race_date=image.race_date if image is not None else None,
                    image_format=image.image_format if image is not None else None,
                    width_px=image.width_px if image is not None else None,
                    height_px=image.height_px if image is not None else None,
                    track=row.track,
                    race_class=row.race_class,
                    weather=row.weather,
                    temp_f=row.temp_f,
                    temp_c=row.temp_c,
                    driver=row.driver,
                    car=row.car,
                    car_class=row.race_class,
                    best_lap=row.best_lap,
                    best_lap_ms=row.best_lap_ms,
                    dirty=row.dirty,
                    is_best_lap=row.is_best_lap,
                )
            )
        return flat

    def mark_best_laps(
        self,
        *,
        run_id: str | None = None,
        gamertag: str | None = None,
    ) -> list[LapRecordEntity]:
        """Mark the relational clean/best-lap frontier.

        When ``gamertag`` is supplied, this mirrors the legacy clean-cache
        semantics against ``lap_records`` instead of snapshots:

        - keep the player frontier per track/class/car/weather/temperature;
        - keep opponent rows faster than the player's best overall time for
          that track/class/weather;
        - keep only each opponent's best row per track/class/car/weather;
        - update ``ImageFile.best_lap_status`` from the winning rows.

        Without ``gamertag`` this falls back to a simple best clean row per
        track/class/driver/car tuple for low-level repository callers.
        """
        rows = self.list_export_rows(run_id=run_id)
        for row in rows:
            row.is_best_lap = False
            self.session.add(row)

        calculator = FrontierCalculator()
        if gamertag:
            winners = calculator.clean_frontier_rows(rows, gamertag)
        else:
            winners = calculator.simple_best_rows(rows)

        winner_ids = {row.id for row in winners}
        winner_image_ids = {row.image_file_id for row in winners}
        all_image_ids = {row.image_file_id for row in rows}
        for row in rows:
            if row.id in winner_ids:
                row.is_best_lap = True
                self.session.add(row)

        for image_id in all_image_ids:
            image = self.session.get(ImageFileEntity, image_id)
            if image is None:
                continue
            image.best_lap_status = "contributing" if image_id in winner_image_ids else "non_contributing"
            self.session.add(image)
        return winners

    def list_best_laps(
        self,
        *,
        run_id: str | None = None,
    ) -> list[LapRecordEntity]:
        """Return rows already marked as best-lap winners.

        This is a read-only persisted-frontier query. It does not recompute
        winners; callers that need a refresh must call ``mark_best_laps()``
        first with the appropriate gamertag.
        """
        return self.list_export_rows(run_id=run_id, best_only=True)

    def to_schema(self, entity: LapRecordEntity) -> LapRecord:
        return LapRecord(
            driver=entity.driver,
            car=entity.car,
            car_class=entity.race_class,
            best_lap=entity.best_lap,
            best_lap_ms=entity.best_lap_ms,
            dirty=entity.dirty,
        )

