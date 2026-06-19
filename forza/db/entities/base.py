from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PromptSnapshotEntity(SQLModel, table=True):
    __tablename__ = "prompt_snapshots"
    __table_args__ = (
        UniqueConstraint("prompt_name", "content_hash", name="uq_prompt_snapshots_name_hash"),
    )

    id: str = Field(primary_key=True)
    prompt_name: str
    version_label: str | None = None
    content_hash: str
    system_text: str
    user_text_template: str | None = None
    response_schema_json: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
