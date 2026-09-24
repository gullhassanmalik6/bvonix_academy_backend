from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class CourseMaterialCreate(APIModel):
    course_id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    material_type: str = Field(pattern="^(video|document|link|assignment_instruction)$")
    content_url: str | None = None
    file_path: str | None = None
    file_size: int | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    order: int = Field(default=0, ge=0)
    is_published: bool = True
    is_required: bool = False


class CourseMaterialUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    content_url: str | None = None
    order: int | None = Field(default=None, ge=0)
    is_published: bool | None = None
    is_required: bool | None = None


class CourseMaterialPublic(APIModel):
    id: str
    course_id: str
    title: str
    description: str | None
    material_type: str
    content_url: str | None
    file_path: str | None
    file_size: int | None
    duration_minutes: int | None
    order: int
    is_published: bool
    is_required: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
