import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import ExtractionAttemptEntity, ExtractionResultEntity, ModelArtifactEntity, ImageFileEntity, RunInputEntity
from forza.db.repositories import ImageFlagRepository, LapRepository, RunRepository, ImageFileRepository
from forza.db.repositories.model_results import ExtractionResultRepository
from forza.schemas import ExtractionResult, LapRecord, ModelExtractionAttempt, RaceSession
from forza.application import GuiReadService
from forza.application import ImageRenameService


LAB_FLAG = "track"


def _make_result(source_file="raw.png", file_hash="hash", *, track="Mugello Circuit Full Circuit") -> ExtractionResult:
    session = RaceSession(
        track=track,
        temp_f=77.0,
        temp_c=25.0,
        entries=[
            LapRecord("Bujica89", "Honda Civic", "TCR", "01:58.123", 118123, False),
            LapRecord("Driver2", "Honda Civic", "TCR", "01:40.000", 100000, True),
        ],
        race_class="TCR",
        weather="dry",
    )
    return ExtractionResult(
        source_file=source_file,
        file_hash=file_hash,
        image_file_id="img-1",
        semantic_name=f"{track} - TCR #1.png",
        session=session,
        status="ok",
        current_path=source_file,
        model_attempts=[
            ModelExtractionAttempt(
                attempt_number=1,
                status="ok",
                accepted=True,
                raw_response='{"ok":true}',
            )
        ],
    )


def _seed_database(db_path: Path, image_path: Path, *, raw_response_artifact_path: Path | None = None):
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            runs = RunRepository(session)
            images = ImageFileRepository(session)
            results = ExtractionResultRepository(session)
            laps = LapRepository(session)
            flags = ImageFlagRepository(session)
            runs.create(run_id="run-1", backend="lmstudio", model="test-model", prompt_name="p1")
            result = _make_result(source_file=image_path.name)
            result.current_path = str(image_path)
            image = images.upsert(
                image_id="img-1",
                file_hash=result.file_hash,
                file_name=image_path.name,
                current_name=image_path.name,
                current_path=image_path,
                semantic_name=result.semantic_name,
            )
            extraction = results.add_result(
                result,
                run_id="run-1",
                image_file_id=image.id,
            )
            laps.add_result(
                result,
                run_id="run-1",
                image_file_id=image.id,
                extraction_result_id=extraction.id,
            )
            laps.mark_best_laps(run_id="run-1")
            flags.add_flag(image_file_id=image.id, run_id="run-1", flag=LAB_FLAG)
            if raw_response_artifact_path is not None:
                raw_bytes = raw_response_artifact_path.read_bytes()
                session.add(ModelArtifactEntity(
                    id="raw-artifact-1",
                    run_id="run-1",
                    image_file_id=image.id,
                    extraction_result_id=extraction.id,
                    attempt_id=extraction.accepted_attempt_id,
                    artifact_type="raw_response",
                    file_path=str(raw_response_artifact_path),
                    sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    size_bytes=len(raw_bytes),
                    is_canonical=True,
                ))
            session.commit()
    finally:
        engine.dispose()



def _clear_sql_raw_response(db_path: Path) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            attempt = session.exec(select(ExtractionAttemptEntity)).first()
            assert attempt is not None
            attempt.raw_response = None
            session.add(attempt)
            session.commit()
    finally:
        engine.dispose()

def _seed_filter_fixture(db_path: Path) -> None:
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            runs = RunRepository(session)
            images = ImageFileRepository(session)
            results = ExtractionResultRepository(session)
            laps = LapRepository(session)
            flags = ImageFlagRepository(session)
            for run_id in ("run-a", "run-b"):
                runs.create(run_id=run_id, backend="lmstudio", model="test-model", prompt_name="p1")

            rows = [
                ("img-a1", "run-a", "Track A", True),
                ("img-a2", "run-a", "Track B", True),
                ("img-b1", "run-b", "Track A", True),
                ("img-b2", "run-b", "Track C", False),
            ]
            for image_id, run_id, track, flagged in rows:
                source_file = f"{image_id}.png"
                result = _make_result(source_file=source_file, file_hash=f"hash-{image_id}", track=track)
                image = images.upsert(
                    image_id=image_id,
                    file_hash=result.file_hash,
                    file_name=source_file,
                    current_name=source_file,
                    current_path=source_file,
                    semantic_name=result.semantic_name,
                )
                extraction = results.add_result(
                    result,
                    run_id=run_id,
                    image_file_id=image.id,
                )
                laps.add_result(
                    result,
                    run_id=run_id,
                    image_file_id=image.id,
                    extraction_result_id=extraction.id,
                )
                if flagged:
                    flags.add_flag(image_file_id=image.id, run_id=run_id, flag=LAB_FLAG)
                session.add(RunInputEntity(run_id=run_id, image_file_id=image.id, input_order=0, input_path=source_file, file_name=source_file, file_hash=image.file_hash, decision="process"))
            session.commit()
    finally:
        engine.dispose()


def test_gui_read_service_lists_images_laps_runs_results_and_summary(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    db_path = tmp_path / "forza.sqlite3"
    _seed_database(db_path, image_path)

    gui = GuiReadService(db_path)

    assert gui.get_image("img-1").semantic_name == "Mugello Circuit Full Circuit - TCR #1.png"
    assert gui.list_images(inventory_filter=LAB_FLAG) == []
    assert not hasattr(gui, "list_image_flags")
    assert len(gui.list_images(track="Mugello Circuit Full Circuit")) == 1
    assert gui.list_runs()[0].id == "run-1"
    assert [lap.driver for lap in gui.list_laps(image_file_id="img-1")] == ["Bujica89", "Driver2"]
    assert len(gui.list_laps(best_only=True)) == 1
    assert gui.list_extraction_results(model="test-model")[0].has_raw_response is True

    summary = gui.dashboard_summary()
    assert summary.images == 1
    assert summary.extraction_results == 1
    assert summary.lap_records == 2
    assert summary.best_lap_images == 1


def test_gui_lap_reads_display_current_name_when_physical_file_was_renamed(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    db_path = tmp_path / "forza.sqlite3"
    _seed_database(db_path, image_path)

    renamed = tmp_path / "renamed-by-user.png"
    image_path.rename(renamed)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            image = session.get(ImageFileEntity, "img-1")
            image.current_name = renamed.name
            image.current_path = str(renamed)
            image.semantic_name = None
            session.add(image)
            session.commit()
    finally:
        engine.dispose()

    gui = GuiReadService(db_path)

    assert gui.list_laps(best_only=True)[0].source_file == "renamed-by-user.png"


def test_image_filter_values_preserve_combined_facet_semantics(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    _seed_filter_fixture(db_path)

    gui = GuiReadService(db_path)

    tracks, runs = gui.image_filter_values(
        track="Track A",
        run_id="run-a",
    )

    # Track options ignore the current track but keep the run filter.
    assert tracks == ["Track A", "Track B"]
    # Run options ignore the current run but keep the track filter.
    assert [run.id for run in runs] == ["run-b", "run-a"]
    assert all("processed" in run.label for run in runs)
    assert all("T" not in run.label for run in runs)


def test_image_filter_values_use_distinct_sql_not_full_lap_materialization() -> None:
    source = Path("forza/application/gui_read/image_reads.py").read_text(encoding="utf-8")
    body = source.split("def image_filter_values", 1)[1].split("def get_image", 1)[0]

    assert ".distinct()" in body
    assert "list_laps" not in body
    assert "list_images" not in body


def test_dashboard_summary_no_longer_exposes_lab_sample_candidates() -> None:
    source = Path("forza/application/gui_read/dashboard_reads.py").read_text(encoding="utf-8")

    assert "LAB_SELECTION_FLAGS" not in source
    assert "lab_sample_candidates" not in source

def test_gui_read_schema_check_is_cached_until_invalidated(tmp_path, monkeypatch):
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    db_path = tmp_path / "forza.sqlite3"
    _seed_database(db_path, image_path)

    from forza.application.gui_read import session_provider as gui_read_session_provider

    calls = {"count": 0}

    def fake_is_up_to_date(path):
        calls["count"] += 1
        return True

    monkeypatch.setattr(gui_read_session_provider, "is_up_to_date", fake_is_up_to_date)

    gui = GuiReadService(db_path)
    assert gui.dashboard_summary().images == 1
    assert gui.list_runs()[0].id == "run-1"
    assert calls["count"] == 1

    gui.invalidate_schema_cache()
    assert gui.list_images()[0].id == "img-1"
    assert calls["count"] == 2


def test_image_debug_detail_only_reads_raw_response_inside_allowed_roots(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    allowed = tmp_path / "output" / "model_artifacts" / "registered"
    allowed.mkdir(parents=True)
    allowed_raw = allowed / "ok.json"
    allowed_raw.write_text("allowed raw", encoding="utf-8")
    blocked_raw = tmp_path / "outside.json"
    blocked_raw.write_text("blocked raw", encoding="utf-8")

    db_path = tmp_path / "forza.sqlite3"
    _seed_database(db_path, image_path, raw_response_artifact_path=allowed_raw)
    _clear_sql_raw_response(db_path)

    gui = GuiReadService(db_path, raw_response_roots=[allowed])
    debug_id = gui.list_image_debug_cases()[0].latest_result_id
    assert gui.get_image_debug_case_by_result(debug_id).raw_response == "allowed raw"

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            row = session.exec(select(ModelArtifactEntity)).first()
            row.file_path = str(blocked_raw)
            session.add(row)
            session.commit()
    finally:
        engine.dispose()

    gui.invalidate_schema_cache()
    assert gui.get_image_debug_case_by_result(debug_id).raw_response is None


def test_image_debug_raw_evidence_prefers_sql_and_requires_explicit_artifact_read(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    allowed = tmp_path / "output" / "model_artifacts" / "registered"
    allowed.mkdir(parents=True)
    allowed_raw = allowed / "ok.json"
    allowed_raw.write_text("allowed raw", encoding="utf-8")

    db_path = tmp_path / "forza.sqlite3"
    _seed_database(db_path, image_path, raw_response_artifact_path=allowed_raw)

    gui = GuiReadService(db_path)
    debug_id = gui.list_image_debug_cases()[0].latest_result_id
    detail = gui.get_image_debug_case_by_result(debug_id)

    assert detail.raw_response == '{"ok":true}'
    assert detail.raw_response_payload == {"ok": True}
    assert any(artifact.file_path == str(allowed_raw) for artifact in detail.artifacts)
    assert gui.read_registered_artifact_text(debug_id, allowed_roots=[]) is None
    assert gui.read_registered_artifact_text(debug_id, allowed_roots=[allowed]) == "allowed raw"


def test_image_debug_cases_use_image_centric_read_model() -> None:
    source = Path("forza/application/gui_read/image_debug_reads.py").read_text(encoding="utf-8")
    list_cases_body = source.split("def list_image_debug_cases", 1)[1].split("def get_image_debug_case", 1)[0]

    assert "ImageFileEntity" in list_cases_body
    assert "_cases_for_images" in source
    assert "image_metadata_json" in source


def test_image_rename_service_plans_renames_and_exports_semantic_names(tmp_path):
    source = tmp_path / "raw.png"
    source.write_text("image", encoding="utf-8")
    db_path = tmp_path / "forza.sqlite3"
    _seed_database(db_path, source)

    service = ImageRenameService(db_path)
    plan = service.plan_rename("img-1")
    assert plan is not None
    assert plan.source_path == source
    assert plan.target_path.name == "Mugello Circuit Full Circuit - TCR #1.png"

    dry = service.rename_file("img-1", dry_run=True)
    assert dry.renamed is False
    assert source.exists()

    result = service.rename_file("img-1", dry_run=False)
    assert result.renamed is True
    assert result.plan.target_path.exists()
    assert not source.exists()

    export_dir = tmp_path / "export"
    exported = service.export_images(["img-1"], export_dir, naming="semantic")
    assert exported.copied == 1
    assert exported.files[0].name == "Mugello Circuit Full Circuit - TCR #1.png"


def test_image_rename_service_sanitizes_windows_reserved_names(tmp_path):
    source = tmp_path / "raw.png"
    source.write_text("image", encoding="utf-8")
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            ImageFileRepository(session).upsert(
                image_id="img-1",
                file_hash="hash",
                file_name="raw.png",
                current_name="raw.png",
                current_path=source,
                semantic_name='CON.png',
            )
            session.commit()
    finally:
        engine.dispose()

    plan = ImageRenameService(db_path).plan_rename("img-1")
    assert plan is not None
    assert plan.target_path.name == "CON_.png"


def test_image_rename_service_batch_continues_numbering_without_double_suffix(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    semantic = "Maple Valley Full Circuit - TCR.png"
    paths = [
        tmp_path / "Maple Valley Full Circuit - TCR - Race 001.png",
        tmp_path / "Maple Valley Full Circuit - TCR - Race 002.png",
        tmp_path / "Screenshot_1.png",
        tmp_path / "Screenshot_2.png",
    ]
    for index, path in enumerate(paths):
        path.write_text(f"image-{index}", encoding="utf-8")

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            for index, path in enumerate(paths):
                ImageFileRepository(session).upsert(
                    image_id=f"img-{index}",
                    file_hash=f"hash-{index}",
                    file_name=path.name,
                    current_name=path.name,
                    current_path=path,
                    semantic_name=semantic,
                )
            session.commit()
    finally:
        engine.dispose()

    service = ImageRenameService(db_path)
    plans = service.plan_rename_many(["img-2", "img-3"])
    assert [plan.target_path.name for plan in plans] == [
        "Maple Valley Full Circuit - TCR - Race 003.png",
        "Maple Valley Full Circuit - TCR - Race 004.png",
    ]
    assert all(plan.target_path.name.count(" - Race ") == 1 for plan in plans)

    results = service.rename_files(["img-2", "img-3"], dry_run=False)
    assert all(result.renamed for result in results)
    repeated = service.plan_rename_many(["img-2", "img-3"])
    assert all(not plan.would_change for plan in repeated)
    assert [plan.target_path.name for plan in repeated] == [
        "Maple Valley Full Circuit - TCR - Race 003.png",
        "Maple Valley Full Circuit - TCR - Race 004.png",
    ]


def test_image_rename_service_single_file_continues_existing_numbering(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    semantic = "Kyalami Grand Prix Circuit - TCR.png"
    existing = tmp_path / "Kyalami Grand Prix Circuit - TCR - Race 005.png"
    source = tmp_path / "Screenshot.png"
    existing.write_text("existing", encoding="utf-8")
    source.write_text("source", encoding="utf-8")

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            ImageFileRepository(session).upsert(
                image_id="existing",
                file_hash="hash-existing",
                file_name=existing.name,
                current_name=existing.name,
                current_path=existing,
                semantic_name=semantic,
            )
            ImageFileRepository(session).upsert(
                image_id="source",
                file_hash="hash-source",
                file_name=source.name,
                current_name=source.name,
                current_path=source,
                semantic_name=semantic,
            )
            session.commit()
    finally:
        engine.dispose()

    plan = ImageRenameService(db_path).plan_rename("source")
    assert plan is not None
    assert plan.target_path.name == "Kyalami Grand Prix Circuit - TCR - Race 006.png"


def test_image_rename_service_continues_after_unindexed_base_name(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    semantic = "Indianapolis Motor Speedway Grand Prix Circuit - TCR.png"
    existing = tmp_path / semantic
    source = tmp_path / "Screenshot.png"
    existing.write_text("existing", encoding="utf-8")
    source.write_text("source", encoding="utf-8")

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            for image_id, path in [("existing", existing), ("source", source)]:
                ImageFileRepository(session).upsert(
                    image_id=image_id,
                    file_hash=f"hash-{image_id}",
                    file_name=path.name,
                    current_name=path.name,
                    current_path=path,
                    semantic_name=semantic,
                )
            session.commit()
    finally:
        engine.dispose()

    plan = ImageRenameService(db_path).plan_rename("source")
    assert plan is not None
    assert plan.target_path.name == "Indianapolis Motor Speedway Grand Prix Circuit - TCR - Race 001.png"


def test_image_rename_service_repairs_double_race_suffixes(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    semantic = "Maple Valley Full Circuit - TCR.png"
    paths = [
        tmp_path / "Maple Valley Full Circuit - TCR - Race 001.png",
        tmp_path / "Maple Valley Full Circuit - TCR - Race 002.png",
        tmp_path / "Maple Valley Full Circuit - TCR - Race 001 - Race 002.png",
        tmp_path / "Maple Valley Full Circuit - TCR - Race 002 - Race 002.png",
    ]
    for index, path in enumerate(paths):
        path.write_text(f"image-{index}", encoding="utf-8")

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            for index, path in enumerate(paths):
                ImageFileRepository(session).upsert(
                    image_id=f"img-{index}",
                    file_hash=f"hash-{index}",
                    file_name=path.name,
                    current_name=path.name,
                    current_path=path,
                    semantic_name=semantic,
                )
            session.commit()
    finally:
        engine.dispose()

    service = ImageRenameService(db_path)
    plans = service.plan_rename_many(["img-2", "img-3"])
    assert [plan.target_path.name for plan in plans] == [
        "Maple Valley Full Circuit - TCR - Race 003.png",
        "Maple Valley Full Circuit - TCR - Race 004.png",
    ]

    results = service.rename_files(["img-2", "img-3"], dry_run=False)
    assert all(result.renamed for result in results)
    assert all(plan.target_path.name.count(" - Race ") == 1 for plan in plans)
    assert all(not plan.would_change for plan in service.plan_rename_many(["img-2", "img-3"]))


def test_image_rename_service_orders_complete_series_by_race_datetime_and_preserves_mtime(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    semantic = "Maple Valley Full Circuit - TCR.png"
    rows = [
        ("newest", tmp_path / "Maple Valley Full Circuit - TCR - Race 001.png", datetime(2026, 6, 3, tzinfo=timezone.utc)),
        ("oldest", tmp_path / "Maple Valley Full Circuit - TCR - Race 002.png", datetime(2026, 6, 1, tzinfo=timezone.utc)),
        ("middle", tmp_path / "Screenshot.png", datetime(2026, 6, 2, tzinfo=timezone.utc)),
    ]
    original_mtimes: dict[str, float] = {}
    for image_id, path, race_datetime in rows:
        path.write_text(image_id, encoding="utf-8")
        os.utime(path, (race_datetime.timestamp(), race_datetime.timestamp()))
        original_mtimes[image_id] = path.stat().st_mtime

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            for image_id, path, race_datetime in rows:
                image = ImageFileRepository(session).upsert(
                    image_id=image_id,
                    file_hash=f"hash-{image_id}",
                    file_name=path.name,
                    current_name=path.name,
                    current_path=path,
                    semantic_name=semantic,
                )
                image.race_datetime = race_datetime
                image.race_date = race_datetime.date()
                session.add(image)
            session.commit()
    finally:
        engine.dispose()

    service = ImageRenameService(db_path)
    image_ids = ["newest", "oldest", "middle"]
    plans = service.plan_rename_many(image_ids)
    assert [(plan.image_file_id, plan.target_path.name) for plan in plans] == [
        ("oldest", "Maple Valley Full Circuit - TCR - Race 001.png"),
        ("middle", "Maple Valley Full Circuit - TCR - Race 002.png"),
        ("newest", "Maple Valley Full Circuit - TCR - Race 003.png"),
    ]

    results = service.rename_files(image_ids, dry_run=False)
    assert all(result.renamed for result in results)
    assert [(tmp_path / f"Maple Valley Full Circuit - TCR - Race {index:03d}.png").read_text(encoding="utf-8") for index in range(1, 4)] == [
        "oldest",
        "middle",
        "newest",
    ]

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            for image_id, _path, _race_datetime in rows:
                image = session.get(ImageFileEntity, image_id)
                current_path = Path(image.current_path)
                assert current_path.stat().st_mtime == original_mtimes[image_id]
                assert image.current_name == current_path.name
    finally:
        engine.dispose()

    repeated = service.plan_rename_many(image_ids)
    assert all(not plan.would_change for plan in repeated)


def test_image_rename_service_does_not_reorder_partial_series(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    semantic = "Maple Valley Full Circuit - TCR.png"
    newest = tmp_path / "Maple Valley Full Circuit - TCR - Race 001.png"
    oldest = tmp_path / "Maple Valley Full Circuit - TCR - Race 002.png"
    newest.write_text("newest", encoding="utf-8")
    oldest.write_text("oldest", encoding="utf-8")

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            for image_id, path, race_datetime in [
                ("newest", newest, datetime(2026, 6, 2, tzinfo=timezone.utc)),
                ("oldest", oldest, datetime(2026, 6, 1, tzinfo=timezone.utc)),
            ]:
                image = ImageFileRepository(session).upsert(
                    image_id=image_id,
                    file_hash=f"hash-{image_id}",
                    file_name=path.name,
                    current_name=path.name,
                    current_path=path,
                    semantic_name=semantic,
                )
                image.race_datetime = race_datetime
                session.add(image)
            session.commit()
    finally:
        engine.dispose()

    plan = ImageRenameService(db_path).plan_rename("newest")
    assert plan is not None
    assert plan.target_path == newest
    assert plan.would_change is False

