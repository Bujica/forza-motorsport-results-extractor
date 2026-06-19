from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from .base import utc_now


class ReferenceTrackEntity(SQLModel, table=True):
    __tablename__ = "reference_tracks"

    id: str = Field(primary_key=True)
    name: str = Field(unique=True)
    normalized_name: str | None = None
    aliases_json: list = Field(default_factory=list, sa_column=Column(JSON))
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReferenceCarEntity(SQLModel, table=True):
    __tablename__ = "reference_cars"

    id: str = Field(primary_key=True)
    name: str = Field(unique=True)
    normalized_name: str | None = None
    race_class: str | None = None
    aliases_json: list = Field(default_factory=list, sa_column=Column(JSON))
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
