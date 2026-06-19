from __future__ import annotations

from sqlalchemy import and_, func
from sqlmodel import select

from ...db.models import ExtractionResultEntity, ExtractionRunEntity, LapRecordEntity, ImageFileEntity, RunInputEntity
from ...db.repositories import ImageFileRepository
from ...schemas import ImageFile
from .run_reads import _run_option
from .session_provider import GuiReadSessionProvider
from .types import GuiImage, GuiRunOption


class GuiImageReadQueries:
    """Read queries for GUI image inventory."""

    def __init__(self, session_provider: GuiReadSessionProvider):
        self._session_provider = session_provider

    def list_images(
        self,
        *,
        file_status: str | None = None,
        best_lap_status: str | None = None,
        inventory_filter: str | None = None,
        track: str | None = None,
        run_id: str | None = None,
        processing_status: str | None = None,
    ) -> list[GuiImage]:
        if not self._session_provider.can_read():
            return []
        with self._session_provider.session() as session:
            query = self._image_ids_query(
                file_status=file_status,
                best_lap_status=best_lap_status,
                inventory_filter=inventory_filter,
                track=track,
                run_id=run_id,
                processing_status=processing_status,
            )
            rows = session.exec(
                select(ImageFileEntity)
                .where(ImageFileEntity.id.in_(query.scalar_subquery()))
                .order_by(ImageFileEntity.created_at.desc())
            ).all()
            processing_by_image = _latest_processing_statuses(session, [row.id for row in rows])
            repo = ImageFileRepository(session)
            images: list[GuiImage] = []
            for row in rows:
                images.append(
                    _to_gui_image(
                        repo.to_schema(row),
                        processing_by_image.get(row.id, "unprocessed"),
                    )
                )
            if inventory_filter == "duplicate":
                images.sort(key=_duplicate_group_sort_key)
            return images

    def image_filter_values(
        self,
        *,
        file_status: str | None = None,
        best_lap_status: str | None = None,
        inventory_filter: str | None = None,
        track: str | None = None,
        run_id: str | None = None,
        processing_status: str | None = None,
    ) -> tuple[list[str], list[GuiRunOption]]:
        if not self._session_provider.can_read():
            return [], []
        with self._session_provider.session() as session:
            track_image_file_ids = self._image_ids_query(
                file_status=file_status,
                best_lap_status=best_lap_status,
                inventory_filter=inventory_filter,
                run_id=run_id,
                processing_status=processing_status,
            ).scalar_subquery()
            tracks_query = (
                select(LapRecordEntity.track)
                .where(
                    LapRecordEntity.track.is_not(None),
                    LapRecordEntity.track != "",
                    LapRecordEntity.image_file_id.in_(track_image_file_ids),
                )
                .distinct()
                .order_by(LapRecordEntity.track.asc())
            )

            run_image_file_ids = self._image_ids_query(
                file_status=file_status,
                best_lap_status=best_lap_status,
                inventory_filter=inventory_filter,
                track=track,
                processing_status=processing_status,
            ).scalar_subquery()
            runs_query = (
                select(ExtractionRunEntity)
                .join(RunInputEntity, RunInputEntity.run_id == ExtractionRunEntity.id)
                .where(
                    RunInputEntity.image_file_id.is_not(None),
                    RunInputEntity.image_file_id.in_(run_image_file_ids),
                )
                .distinct()
                .order_by(ExtractionRunEntity.started_at.desc(), ExtractionRunEntity.id.desc())
            )
            tracks = [str(value) for value in session.exec(tracks_query).all() if value]
            runs = [_run_option(row) for row in session.exec(runs_query).all()]
            return tracks, runs

    def get_image(self, image_file_id: str) -> ImageFile | None:
        if not self._session_provider.can_read():
            return None
        with self._session_provider.session() as session:
            entity = session.get(ImageFileEntity, image_file_id)
            return ImageFileRepository(session).to_schema(entity) if entity is not None else None


    def _image_ids_query(
        self,
        *,
        file_status: str | None = None,
        best_lap_status: str | None = None,
        inventory_filter: str | None = None,
        track: str | None = None,
        run_id: str | None = None,
        processing_status: str | None = None,
    ):
        query = select(ImageFileEntity.id)
        if file_status is not None:
            query = query.where(ImageFileEntity.file_status == file_status)
        if best_lap_status is not None:
            query = query.where(ImageFileEntity.best_lap_status == best_lap_status)
        if processing_status is not None:
            query = _apply_processing_status_filter(query, processing_status)
        if track is not None:
            lap_subq = select(LapRecordEntity.image_file_id)
            lap_subq = lap_subq.where(LapRecordEntity.track == track)
            query = query.where(ImageFileEntity.id.in_(lap_subq.scalar_subquery()))
        if run_id is not None:
            run_input_subq = (
                select(RunInputEntity.image_file_id)
                .where(
                    RunInputEntity.run_id == run_id,
                    RunInputEntity.image_file_id.is_not(None),
                )
                .scalar_subquery()
            )
            query = query.where(ImageFileEntity.id.in_(run_input_subq))
        if inventory_filter is not None:
            if inventory_filter == "duplicate":
                query = _apply_duplicate_group_filter(query)
            else:
                query = query.where(False)
        return query


def _apply_duplicate_group_filter(query):
    matching_ids = query.subquery()
    duplicate_parent_ids = (
        select(ImageFileEntity.duplicate_of_image_file_id)
        .where(ImageFileEntity.duplicate_of_image_file_id.is_not(None))
        .distinct()
        .subquery()
    )
    canonical_ids = (
        select(func.coalesce(ImageFileEntity.duplicate_of_image_file_id, ImageFileEntity.id).label("canonical_id"))
        .where(ImageFileEntity.id.in_(select(matching_ids.c.id)))
        .where(
            (ImageFileEntity.duplicate_of_image_file_id.is_not(None))
            | (ImageFileEntity.id.in_(select(duplicate_parent_ids.c.duplicate_of_image_file_id)))
        )
        .distinct()
        .subquery()
    )
    return select(ImageFileEntity.id).where(
        (ImageFileEntity.id.in_(select(canonical_ids.c.canonical_id)))
        | (ImageFileEntity.duplicate_of_image_file_id.in_(select(canonical_ids.c.canonical_id)))
    )


def _duplicate_group_sort_key(image: ImageFile) -> tuple[str, str, int, str]:
    group_id = image.duplicate_of_image_file_id or image.id
    role = 0 if image.duplicate_of_image_file_id is None else 1
    return (str(image.file_hash or ""), str(group_id), role, str(image.current_name or "").lower())



def _to_gui_image(image: ImageFile, processing_status: str) -> GuiImage:
    return GuiImage(
        id=image.id,
        file_hash=image.file_hash,
        duplicate_of_image_file_id=image.duplicate_of_image_file_id,
        current_name=image.current_name,
        semantic_name=image.semantic_name,
        current_path=image.current_path,
        file_status=str(image.file_status),
        processing_status=processing_status,
        best_lap_status=str(image.best_lap_status),
        file_size_bytes=image.file_size_bytes,
        image_format=image.image_format,
        mime_type=image.mime_type,
        width_px=image.width_px,
        height_px=image.height_px,
        bit_depth=image.bit_depth,
        color_mode=image.color_mode,
        file_modified_at=image.file_modified_at,
        race_datetime=image.race_datetime,
        race_date=image.race_date,
        race_datetime_source=image.race_datetime_source,
        image_metadata_json=dict(image.image_metadata_json or {}),
    )

def _apply_processing_status_filter(query, processing_status: str):
    processed_subq = select(ExtractionResultEntity.image_file_id).distinct().scalar_subquery()
    latest_input = _latest_run_input_subquery()
    if processing_status == "unprocessed":
        skipped_subq = (
            select(RunInputEntity.image_file_id)
            .join(latest_input, RunInputEntity.id == latest_input.c.latest_input_id)
            .where(
                RunInputEntity.image_file_id.is_not(None),
                RunInputEntity.decision != "process",
            )
            .distinct()
            .scalar_subquery()
        )
        return query.where(
            ~ImageFileEntity.id.in_(processed_subq),
            ~ImageFileEntity.id.in_(skipped_subq),
        )
    if processing_status == "skipped":
        skipped_subq = (
            select(RunInputEntity.image_file_id)
            .join(latest_input, RunInputEntity.id == latest_input.c.latest_input_id)
            .where(
                RunInputEntity.image_file_id.is_not(None),
                RunInputEntity.decision != "process",
                ~RunInputEntity.image_file_id.in_(processed_subq),
            )
            .distinct()
            .scalar_subquery()
        )
        return query.where(ImageFileEntity.id.in_(skipped_subq))
    statuses = _result_statuses_for_processing_status(processing_status)
    if not statuses:
        return query.where(False)
    latest = (
        select(
            ExtractionResultEntity.image_file_id,
            func.max(ExtractionResultEntity.created_at).label("latest_created"),
        )
        .group_by(ExtractionResultEntity.image_file_id)
        .subquery()
    )
    latest_status_subq = (
        select(ExtractionResultEntity.image_file_id)
        .join(
            latest,
            and_(
                ExtractionResultEntity.image_file_id == latest.c.image_file_id,
                ExtractionResultEntity.created_at == latest.c.latest_created,
            ),
        )
        .where(ExtractionResultEntity.status.in_(statuses))
        .distinct()
        .scalar_subquery()
    )
    return query.where(ImageFileEntity.id.in_(latest_status_subq))


def _latest_processing_statuses(session, image_file_ids: list[str]) -> dict[str, str]:
    if not image_file_ids:
        return {}
    latest_result = (
        select(
            ExtractionResultEntity.image_file_id.label("image_file_id"),
            ExtractionResultEntity.status.label("status"),
            func.row_number().over(
                partition_by=ExtractionResultEntity.image_file_id,
                order_by=(
                    ExtractionResultEntity.created_at.desc(),
                    ExtractionResultEntity.id.desc(),
                ),
            ).label("result_rank"),
        )
        .where(ExtractionResultEntity.image_file_id.in_(image_file_ids))
        .subquery()
    )
    rows = session.exec(
        select(latest_result.c.image_file_id, latest_result.c.status).where(
            latest_result.c.result_rank == 1
        )
    ).all()
    statuses: dict[str, str] = {
        str(image_id): _processing_status_for_result(str(result_status))
        for image_id, result_status in rows
        if image_id
    }
    missing_result_ids = [image_id for image_id in image_file_ids if image_id not in statuses]
    if missing_result_ids:
        latest_input = _latest_run_input_subquery()
        input_rows = session.exec(
            select(RunInputEntity)
            .join(latest_input, RunInputEntity.id == latest_input.c.latest_input_id)
            .where(RunInputEntity.image_file_id.in_(missing_result_ids))
        ).all()
        for row in input_rows:
            if row.image_file_id and row.decision != "process":
                statuses[row.image_file_id] = "skipped"
    return statuses


def _latest_run_input_subquery():
    return (
        select(
            RunInputEntity.image_file_id,
            func.max(RunInputEntity.id).label("latest_input_id"),
        )
        .where(RunInputEntity.image_file_id.is_not(None))
        .group_by(RunInputEntity.image_file_id)
        .subquery()
    )


def _processing_status_for_result(result_status: str) -> str:
    if result_status in {"pending", "running"}:
        return "processing"
    if result_status == "ok":
        return "processed_ok"
    if result_status == "error":
        return "processed_error"
    if result_status == "cancelled":
        return "cancelled"
    return "processed_error"


def _result_statuses_for_processing_status(processing_status: str) -> set[str]:
    return {
        "processing": {"pending", "running"},
        "processed_ok": {"ok"},
        "processed_error": {"error"},
        "cancelled": {"cancelled"},
    }.get(processing_status, set())

