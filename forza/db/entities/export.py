from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, String
from sqlmodel import Field, SQLModel

from .base import utc_now


class ExportArtifactEntity(SQLModel, table=True):
    __tablename__ = "export_artifacts"
    __table_args__ = (
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_export_artifacts_size_nonnegative"),
    )

    id: str = Field(primary_key=True)
    run_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("extraction_runs.id", ondelete="SET NULL"), nullable=True))
    artifact_type: str
    file_path: str
    relative_path: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
