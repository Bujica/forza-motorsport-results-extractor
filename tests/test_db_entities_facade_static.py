from __future__ import annotations

from pathlib import Path

from forza.db import entities, models

ROOT = Path(__file__).resolve().parents[1]


def test_db_entities_facade_reexports_current_model_entities() -> None:
    model_entity_names = sorted(
        name
        for name in vars(models)
        if name.endswith("Entity")
    )

    assert model_entity_names
    assert sorted(name for name in entities.__all__ if name.endswith("Entity")) == model_entity_names
    assert "utc_now" in entities.__all__

    for name in model_entity_names:
        assert getattr(entities, name) is getattr(models, name)
    assert entities.utc_now is models.utc_now


def test_db_entities_facade_does_not_advertise_sqlmodel_in_star_exports() -> None:
    assert "SQLModel" not in entities.__all__
    assert "Field" not in entities.__all__
    assert not hasattr(entities, "SQLModel")


def test_prompt_snapshot_entity_lives_in_base_module() -> None:
    model_source = (ROOT / "forza" / "db" / "models.py").read_text(encoding="utf-8")
    base_source = (ROOT / "forza" / "db" / "entities" / "base.py").read_text(encoding="utf-8")

    assert "class PromptSnapshotEntity" not in model_source
    assert "def utc_now()" not in model_source
    assert "from .entities.base import PromptSnapshotEntity, utc_now" in model_source
    assert "class PromptSnapshotEntity" in base_source
    assert "def utc_now()" in base_source


def test_prompt_snapshot_entity_identity_is_preserved_through_models_facade() -> None:
    from forza.db.entities.base import PromptSnapshotEntity, utc_now

    assert models.PromptSnapshotEntity is PromptSnapshotEntity
    assert models.utc_now is utc_now
    assert entities.PromptSnapshotEntity is PromptSnapshotEntity
    assert entities.utc_now is utc_now


def test_run_entities_live_in_run_module() -> None:
    model_source = (ROOT / "forza" / "db" / "models.py").read_text(encoding="utf-8")
    run_source = (ROOT / "forza" / "db" / "entities" / "run.py").read_text(encoding="utf-8")

    assert "class ExtractionRunEntity" not in model_source
    assert "class RunInputEntity" not in model_source
    assert "class ModelRuntimeSnapshotEntity" not in model_source
    assert "from .entities.run import ExtractionRunEntity, ModelRuntimeSnapshotEntity, RunInputEntity" in model_source
    assert "class ExtractionRunEntity" in run_source
    assert "class RunInputEntity" in run_source
    assert "class ModelRuntimeSnapshotEntity" in run_source


def test_run_entity_identity_is_preserved_through_models_facade() -> None:
    from forza.db.entities.run import ExtractionRunEntity, ModelRuntimeSnapshotEntity, RunInputEntity

    assert models.ExtractionRunEntity is ExtractionRunEntity
    assert models.RunInputEntity is RunInputEntity
    assert models.ModelRuntimeSnapshotEntity is ModelRuntimeSnapshotEntity
    assert entities.ExtractionRunEntity is ExtractionRunEntity
    assert entities.RunInputEntity is RunInputEntity
    assert entities.ModelRuntimeSnapshotEntity is ModelRuntimeSnapshotEntity


def test_image_file_entity_lives_in_image_module() -> None:
    model_source = (ROOT / "forza" / "db" / "models.py").read_text(encoding="utf-8")
    image_source = (ROOT / "forza" / "db" / "entities" / "image.py").read_text(encoding="utf-8")

    assert "class ImageFileEntity" not in model_source
    assert "from .entities.image import ImageFileEntity" in model_source
    assert "class ImageFileEntity" in image_source
    assert "__tablename__ = \"image_files\"" in image_source
    assert "idx_image_files_status" in image_source


def test_image_file_entity_identity_is_preserved_through_models_facade() -> None:
    from forza.db.entities.image import ImageFileEntity

    assert models.ImageFileEntity is ImageFileEntity
    assert entities.ImageFileEntity is ImageFileEntity


def test_extraction_result_entities_live_in_result_module() -> None:
    model_source = (ROOT / "forza" / "db" / "models.py").read_text(encoding="utf-8")
    result_source = (ROOT / "forza" / "db" / "entities" / "result.py").read_text(encoding="utf-8")

    assert "class ExtractionResultEntity" not in model_source
    assert "class ExtractionAttemptEntity" not in model_source
    assert "class ModelArtifactEntity" not in model_source
    assert "from .entities.result import ExtractionAttemptEntity, ExtractionResultEntity, ModelArtifactEntity" in model_source
    assert "class ExtractionResultEntity" in result_source
    assert "class ExtractionAttemptEntity" in result_source
    assert "class ModelArtifactEntity" in result_source


def test_extraction_result_entity_identity_is_preserved_through_models_facade() -> None:
    from forza.db.entities.result import ExtractionAttemptEntity, ExtractionResultEntity, ModelArtifactEntity

    assert models.ExtractionResultEntity is ExtractionResultEntity
    assert models.ExtractionAttemptEntity is ExtractionAttemptEntity
    assert models.ModelArtifactEntity is ModelArtifactEntity
    assert entities.ExtractionResultEntity is ExtractionResultEntity
    assert entities.ExtractionAttemptEntity is ExtractionAttemptEntity
    assert entities.ModelArtifactEntity is ModelArtifactEntity


def test_lap_record_entity_lives_in_lap_module() -> None:
    model_source = (ROOT / "forza" / "db" / "models.py").read_text(encoding="utf-8")
    lap_source = (ROOT / "forza" / "db" / "entities" / "lap.py").read_text(encoding="utf-8")

    assert "class LapRecordEntity" not in model_source
    assert "from .entities.lap import LapRecordEntity" in model_source
    assert "class LapRecordEntity" in lap_source
    assert "idx_lap_records_best_track_class_driver" in lap_source
    assert "idx_lap_records_best_gui_order" in lap_source
    assert "best_lap_ms" in lap_source


def test_lap_record_entity_identity_is_preserved_through_models_facade() -> None:
    from forza.db.entities.lap import LapRecordEntity

    assert models.LapRecordEntity is LapRecordEntity
    assert entities.LapRecordEntity is LapRecordEntity


def test_review_entities_live_in_review_module() -> None:
    model_source = (ROOT / "forza" / "db" / "models.py").read_text(encoding="utf-8")
    review_source = (ROOT / "forza" / "db" / "entities" / "review.py").read_text(encoding="utf-8")

    assert "class ReviewCaseEntity" not in model_source
    assert "class ReviewCorrectionEntity" not in model_source
    assert "class ImageFlagEntity" not in model_source
    assert "from .entities.review import ImageFlagEntity, ReviewCaseEntity, ReviewCorrectionEntity" in model_source
    assert "class ReviewCaseEntity" in review_source
    assert "class ReviewCorrectionEntity" in review_source
    assert "class ImageFlagEntity" in review_source


def test_review_entity_identity_is_preserved_through_models_facade() -> None:
    from forza.db.entities.review import ImageFlagEntity, ReviewCaseEntity, ReviewCorrectionEntity

    assert models.ReviewCaseEntity is ReviewCaseEntity
    assert models.ReviewCorrectionEntity is ReviewCorrectionEntity
    assert models.ImageFlagEntity is ImageFlagEntity
    assert entities.ReviewCaseEntity is ReviewCaseEntity
    assert entities.ReviewCorrectionEntity is ReviewCorrectionEntity
    assert entities.ImageFlagEntity is ImageFlagEntity


def test_remaining_entities_live_in_domain_modules() -> None:
    model_source = (ROOT / "forza" / "db" / "models.py").read_text(encoding="utf-8")
    modules = {
        "export": ["ExportArtifactEntity"],
        "reference": ["ReferenceTrackEntity", "ReferenceCarEntity"],
        "external": ["ExternalRecordImportEntity", "ExternalLapRecordEntity"],
    }

    for module_name, names in modules.items():
        module_source = (ROOT / "forza" / "db" / "entities" / f"{module_name}.py").read_text(encoding="utf-8")
        for name in names:
            assert f"class {name}" not in model_source
            assert f"class {name}" in module_source

    assert "from .entities.export import ExportArtifactEntity" in model_source
    assert "from .entities.reference import ReferenceCarEntity, ReferenceTrackEntity" in model_source
    assert "from .entities.external import ExternalLapRecordEntity, ExternalRecordImportEntity" in model_source
    assert "idx_external_lap_records_active_order" in (
        ROOT / "forza" / "db" / "entities" / "external.py"
    ).read_text(encoding="utf-8")
    assert "entities.lab" not in model_source


def test_remaining_entity_identities_are_preserved_through_models_facade() -> None:
    from forza.db.entities.export import ExportArtifactEntity
    from forza.db.entities.external import ExternalLapRecordEntity, ExternalRecordImportEntity
    from forza.db.entities.reference import ReferenceCarEntity, ReferenceTrackEntity

    expected = {
        "ExportArtifactEntity": ExportArtifactEntity,
        "ReferenceTrackEntity": ReferenceTrackEntity,
        "ReferenceCarEntity": ReferenceCarEntity,
        "ExternalRecordImportEntity": ExternalRecordImportEntity,
        "ExternalLapRecordEntity": ExternalLapRecordEntity,
    }

    for name, value in expected.items():
        assert getattr(models, name) is value
        assert getattr(entities, name) is value

    for removed in (
        "Lab" + "RunEntity",
        "Lab" + "RunCaseEntity",
        "Lab" + "ArtifactEntity",
        "Lab" + "SampleEntity",
        "Lab" + "SampleImageEntity",
    ):
        assert not hasattr(models, removed)
        assert not hasattr(entities, removed)
