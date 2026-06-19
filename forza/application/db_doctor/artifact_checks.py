from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import func, text
from sqlmodel import Session, select

from .contracts import DbDoctorCheck
from .run_checks import result_input_parent_mismatch_check
from ...db.evidence import canonical_request_hash
from ...db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ExportArtifactEntity,
    ModelArtifactEntity,
    ModelRuntimeSnapshotEntity,
    PromptSnapshotEntity,
    ImageFileEntity,
)


def result_artifact_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        DbDoctorCheck(
            "ok_results_without_accepted_attempt",
            "error",
            _count(session, select(ExtractionResultEntity).where(
                ExtractionResultEntity.status == "ok",
                ExtractionResultEntity.accepted_attempt_id.is_(None),
            )),
            "Successful extraction results must point to an accepted attempt.",
        ),
        _check_sql(
            session,
            key="accepted_attempt_pointer_invalid",
            detail="accepted_attempt_id must point to an accepted ok attempt.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_results er
                LEFT JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
                WHERE er.accepted_attempt_id IS NOT NULL
                  AND (a.id IS NULL OR a.accepted <> 1 OR a.status <> 'ok')
            """,
        ),
        _check_sql(
            session,
            key="error_results_with_laps",
            detail="Error extraction results must not have lap_records.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_results er
                JOIN lap_records lr ON lr.extraction_result_id = er.id
                WHERE er.status = 'error'
            """,
        ),
        DbDoctorCheck(
            "accepted_attempts_missing_raw_evidence",
            "error",
            _accepted_attempts_missing_raw_evidence(session),
            "Accepted attempts must have raw_response text or a canonical raw_response artifact.",
        ),
        DbDoctorCheck(
            "canonical_artifacts_invalid",
            "error",
            _invalid_canonical_artifacts(session),
            "File-backed canonical model artifacts must exist and match sha256/size_bytes; SQL-backed raw evidence is validated from extraction_attempts.",
        ),
        DbDoctorCheck(
            "model_artifacts_invalid",
            "error",
            _invalid_model_artifacts(session),
            "Every file-backed model artifact must exist and match sha256/size_bytes; SQL-backed raw evidence is validated from extraction_attempts.",
        ),
        DbDoctorCheck(
            "runs_missing_prompt_snapshot",
            "error",
            _count(session, select(ExtractionRunEntity).where(
                (ExtractionRunEntity.prompt_snapshot_id.is_(None))
                | (~ExtractionRunEntity.prompt_snapshot_id.in_(select(PromptSnapshotEntity.id))),
            )),
            "Run prompt_snapshot_id must point to immutable prompt content.",
        ),
        DbDoctorCheck(
            "prompt_snapshot_integrity_invalid",
            "error",
            _invalid_prompt_snapshots(session),
            "Prompt snapshot id/hash must match its canonical immutable content.",
        ),
        _check_sql(
            session,
            key="run_prompt_snapshot_mismatch",
            detail="Run prompt_name/prompt_hash must match its linked prompt snapshot.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_runs r
                JOIN prompt_snapshots p ON p.id = r.prompt_snapshot_id
                WHERE r.prompt_name <> p.prompt_name
                   OR r.prompt_hash <> p.content_hash
                   OR r.prompt_name IS NULL
                   OR r.prompt_hash IS NULL
            """,
        ),
        result_input_parent_mismatch_check(session),
        DbDoctorCheck(
            "runs_after_preflight_missing_runtime_snapshot",
            "error",
            _runs_after_preflight_missing_snapshot(session),
            "Runs that reached LM Studio preflight must have one preflight runtime snapshot.",
        ),
        DbDoctorCheck(
            "export_artifacts_invalid",
            "error",
            _invalid_export_artifacts(session),
            "Export artifacts must exist and match registered hash/size.",
        ),
        DbDoctorCheck(
            "request_messages_contain_image_payload",
            "error",
            _request_messages_with_image_payload(session),
            "Stored request_messages_json must be redacted and contain no image base64 payload.",
        ),
        DbDoctorCheck(
            "request_hash_invalid",
            "error",
            _invalid_request_hashes(session),
            "request_hash must recompute from persisted redacted request payload.",
        ),
        DbDoctorCheck(
            "attempts_missing_runtime_snapshot",
            "error",
            _count(session, select(ExtractionAttemptEntity).where(
                ExtractionAttemptEntity.runtime_snapshot_id.is_(None),
            )),
            "Every real chat attempt must identify the observed runtime snapshot.",
        ),
        _check_sql(
            session,
            key="attempt_parent_mismatch",
            detail="Attempt run/source links must match their extraction_result.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_attempts a
                JOIN extraction_results er ON er.id = a.extraction_result_id
                WHERE a.run_id <> er.run_id
                   OR a.image_file_id <> er.image_file_id
            """,
        ),
        _check_sql(
            session,
            key="accepted_attempt_parent_mismatch",
            detail="accepted_attempt_id must belong to the same extraction_result.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_results er
                JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
                WHERE a.extraction_result_id <> er.id
            """,
        ),
        _check_sql(
            session,
            key="result_attempt_count_mismatch",
            detail="extraction_results.attempt_count must match persisted attempts.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_results er
                WHERE er.attempt_count <> (
                    SELECT COUNT(*) FROM extraction_attempts a
                    WHERE a.extraction_result_id = er.id
                )
            """,
        ),
        _check_sql(
            session,
            key="result_prompt_mismatch",
            detail="Every result must retain the immutable prompt snapshot of its run.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_results er
                JOIN extraction_runs r ON r.id = er.run_id
                WHERE er.prompt_snapshot_id IS NULL
                   OR er.prompt_snapshot_id <> r.prompt_snapshot_id
            """,
        ),
        _check_sql(
            session,
            key="attempt_runtime_parent_mismatch",
            detail="Attempt runtime snapshots must belong to the same run.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_attempts a
                JOIN model_runtime_snapshots s ON s.id = a.runtime_snapshot_id
                WHERE a.run_id <> s.run_id
            """,
        ),
        _check_sql(
            session,
            key="canonical_artifacts_without_attempt",
            detail="Canonical raw response artifacts must belong to a real attempt.",
            sql="""
                SELECT COUNT(*)
                FROM model_artifacts
                WHERE is_canonical = 1
                  AND artifact_type = 'raw_response'
                  AND attempt_id IS NULL
            """,
        ),
        _check_sql(
            session,
            key="model_artifact_parent_mismatch",
            detail="Model artifact run/source/result/attempt links must describe one evidence chain.",
            sql="""
                SELECT COUNT(*)
                FROM model_artifacts ma
                LEFT JOIN extraction_results er ON er.id = ma.extraction_result_id
                LEFT JOIN extraction_attempts a ON a.id = ma.attempt_id
                WHERE (
                    ma.extraction_result_id IS NOT NULL
                    AND (
                        er.id IS NULL
                        OR ma.run_id IS NOT er.run_id
                        OR ma.image_file_id IS NOT er.image_file_id
                    )
                )
                OR (
                    ma.attempt_id IS NOT NULL
                    AND (
                        a.id IS NULL
                        OR ma.run_id IS NOT a.run_id
                        OR ma.image_file_id IS NOT a.image_file_id
                        OR ma.extraction_result_id IS NOT a.extraction_result_id
                    )
                )
            """,
        ),
        DbDoctorCheck(
            "error_attempts_missing_sql_evidence",
            "error",
            _error_attempts_missing_sql_evidence(session),
            "Failed attempts must retain SQL debug evidence such as raw_response, parse_error, or error_message.",
        ),
    ]


def _count(session: Session, query) -> int:
    return int(session.exec(select(func.count()).select_from(query.subquery())).one())


def _scalar_sql(session: Session, sql: str) -> int:
    row = session.exec(text(sql)).one()
    return int(row[0] if isinstance(row, tuple) or hasattr(row, "__getitem__") else row)


def _check_sql(
    session: Session,
    *,
    key: str,
    detail: str,
    sql: str,
    severity: str = "error",
    count_groups: bool = False,
) -> DbDoctorCheck:
    if count_groups:
        rows = session.exec(text(sql)).all()
        count = len(rows)
    else:
        count = _scalar_sql(session, sql)
    return DbDoctorCheck(key, severity, count, detail)



def _invalid_export_artifacts(session: Session) -> int:
    invalid = 0
    for artifact in session.exec(select(ExportArtifactEntity)).all():
        if not _file_matches_size_and_sha256(
            Path(artifact.file_path),
            expected_size=artifact.size_bytes,
            expected_sha256=artifact.sha256,
        ):
            invalid += 1
    return invalid

def _invalid_prompt_snapshots(session: Session) -> int:
    from ...prompts import prompt_payload_hash

    invalid = 0
    rows = session.exec(select(PromptSnapshotEntity)).all()
    for row in rows:
        expected_hash = prompt_payload_hash(
            system_text=row.system_text,
            user_text_template=row.user_text_template,
            response_schema_json=row.response_schema_json,
        )
        if row.content_hash != expected_hash or row.id != f"{row.prompt_name}:{expected_hash}":
            invalid += 1
    return invalid


def _accepted_attempts_missing_raw_evidence(session: Session) -> int:
    return _scalar_sql(
        session,
        """
        SELECT COUNT(*)
        FROM extraction_attempts a
        WHERE a.accepted = 1
          AND COALESCE(a.raw_response, '') = ''
          AND NOT EXISTS (
              SELECT 1
              FROM model_artifacts ma
              WHERE ma.attempt_id = a.id
                AND ma.artifact_type = 'raw_response'
                AND ma.is_canonical = 1
          )
        """,
    )


def _invalid_canonical_artifacts(session: Session) -> int:
    rows = list(session.exec(
        select(ModelArtifactEntity).where(ModelArtifactEntity.is_canonical == True)  # noqa: E712
    ).all())
    return _invalid_file_artifacts(session, rows)


def _invalid_model_artifacts(session: Session) -> int:
    return _invalid_file_artifacts(session, list(session.exec(select(ModelArtifactEntity)).all()))


def _invalid_file_artifacts(session: Session, rows) -> int:
    artifacts = list(rows)
    sql_evidence_keys = _artifact_sql_evidence_keys(session, artifacts)
    invalid = 0
    for artifact in artifacts:
        if _artifact_has_sql_evidence(artifact, sql_evidence_keys):
            continue
        if not _file_matches_size_and_sha256(
            Path(artifact.file_path),
            expected_size=artifact.size_bytes,
            expected_sha256=artifact.sha256,
        ):
            invalid += 1
    return invalid


def _file_matches_size_and_sha256(
    path: Path,
    *,
    expected_size: int | None,
    expected_sha256: str | None,
) -> bool:
    if expected_size is None or expected_sha256 is None:
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    if not path.is_file():
        return False
    if stat.st_size != expected_size:
        return False
    return _sha256_file(path) == expected_sha256


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _artifact_sql_evidence_keys(
    session: Session,
    artifacts: list[ModelArtifactEntity],
) -> set[tuple[str, str]]:
    attempt_ids = sorted({
        str(artifact.attempt_id)
        for artifact in artifacts
        if artifact.artifact_type in {"raw_response", "failed_attempt"}
        and artifact.attempt_id
    })
    if not attempt_ids:
        return set()

    evidence_keys: set[tuple[str, str]] = set()
    for offset in range(0, len(attempt_ids), 900):
        chunk = attempt_ids[offset:offset + 900]
        attempts = session.exec(
            select(ExtractionAttemptEntity).where(ExtractionAttemptEntity.id.in_(chunk))
        ).all()
        for attempt in attempts:
            if attempt.raw_response:
                evidence_keys.add((str(attempt.id), "raw_response"))
            if attempt.status == "error" and _attempt_has_debug_evidence(attempt):
                evidence_keys.add((str(attempt.id), "failed_attempt"))
    return evidence_keys


def _artifact_has_sql_evidence(
    artifact: ModelArtifactEntity,
    sql_evidence_keys: set[tuple[str, str]],
) -> bool:
    if artifact.artifact_type not in {"raw_response", "failed_attempt"}:
        return False
    if not artifact.attempt_id:
        return False
    return (str(artifact.attempt_id), artifact.artifact_type) in sql_evidence_keys


def _attempt_has_debug_evidence(attempt: ExtractionAttemptEntity) -> bool:
    return bool(
        attempt.raw_response
        or attempt.parse_error
        or attempt.error_code
        or attempt.error_message
        or attempt.rejected_reason
        or attempt.validation_issues_json
    )


def _error_attempts_missing_sql_evidence(session: Session) -> int:
    rows = session.exec(
        select(ExtractionAttemptEntity).where(ExtractionAttemptEntity.status == "error")
    ).all()
    return sum(1 for attempt in rows if not _attempt_has_debug_evidence(attempt))


def _runs_after_preflight_missing_snapshot(session: Session) -> int:
    runs = session.exec(
        select(ExtractionRunEntity).where(
            ExtractionRunEntity.status.in_(["completed", "cancelled"]),
        )
    ).all()
    missing = 0
    for run in runs:
        if not _run_requires_preflight_snapshot(session, run):
            continue
        snapshot = session.exec(
            select(ModelRuntimeSnapshotEntity).where(
                ModelRuntimeSnapshotEntity.run_id == run.id,
                ModelRuntimeSnapshotEntity.snapshot_kind == "preflight",
            )
        ).first()
        if snapshot is None:
            missing += 1
    return missing


def _run_requires_preflight_snapshot(session: Session, run: ExtractionRunEntity) -> bool:
    if _is_dry_run(run):
        return False
    if run.status == "completed" and int(run.to_process or 0) > 0:
        return True
    if int(run.processed or 0) > 0 or int(run.succeeded or 0) > 0 or int(run.failed or 0) > 0:
        return True
    return _run_has_extraction_results(session, run.id)


def _is_dry_run(run: ExtractionRunEntity) -> bool:
    if run.mode == "dry_run":
        return True
    config = _run_config(run)
    return bool(config.get("dry_run"))


def _run_config(run: ExtractionRunEntity) -> dict:
    value = run.config_extra_json
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            config = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return config if isinstance(config, dict) else {}
    return value if isinstance(value, dict) else {}


def _run_has_extraction_results(session: Session, run_id: str) -> bool:
    return session.exec(
        select(ExtractionResultEntity.id).where(ExtractionResultEntity.run_id == run_id)
    ).first() is not None


def _request_messages_with_image_payload(session: Session) -> int:
    bad = 0
    rows = session.exec(select(ExtractionAttemptEntity.request_messages_json)).all()
    for payload in rows:
        if payload is None:
            continue
        text_payload = json.dumps(payload, ensure_ascii=True) if not isinstance(payload, str) else payload
        lowered = text_payload.lower()
        if "data:image" in lowered or "base64" in lowered:
            bad += 1
    return bad


def _invalid_request_hashes(session: Session) -> int:
    invalid = 0
    rows = session.exec(
        select(
            ExtractionAttemptEntity,
            ExtractionResultEntity.prompt_snapshot_id,
            ImageFileEntity.file_hash,
        )
        .join(
            ExtractionResultEntity,
            ExtractionResultEntity.id == ExtractionAttemptEntity.extraction_result_id,
        )
        .join(
            ImageFileEntity,
            ImageFileEntity.id == ExtractionAttemptEntity.image_file_id,
        )
    ).all()
    for attempt, prompt_snapshot_id, source_file_hash in rows:
        if not attempt.request_hash:
            invalid += 1
            continue
        expected = canonical_request_hash(
            request_messages_json=attempt.request_messages_json,
            request_config_json=attempt.request_config_json,
            prompt_snapshot_id=prompt_snapshot_id,
            model=attempt.model,
            source_file_hash=source_file_hash,
            request_image_format=attempt.request_image_format,
            request_image_mime_type=attempt.request_image_mime_type,
            request_image_width=attempt.request_image_width,
            request_image_height=attempt.request_image_height,
            request_image_bytes=attempt.request_image_bytes,
        )
        if expected != attempt.request_hash:
            invalid += 1
    return invalid
