from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class AnnouncementCreate(APIModel):
    course_id: str | None = None  # None for system-wide
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    is_published: bool = True
    published_at: datetime | None = None
    expires_at: datetime | None = None


class AnnouncementUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    priority: str | None = Field(default=None, pattern="^(low|normal|high|urgent)$")
    is_published: bool | None = None
    expires_at: datetime | None = None


class AnnouncementPublic(APIModel):
    id: str
    course_id: str | None
    title: str
    content: str
    priority: str
    is_published: bool
    published_at: datetime | None
    expires_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime
