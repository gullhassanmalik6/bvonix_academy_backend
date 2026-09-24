from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class CourseCreate(APIModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    instructor_id: str
    duration_hours: int = Field(ge=1, le=1000)
    price: float = Field(ge=0.0)
    is_published: bool = False


class CourseUpdate(APIModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=5000)
    instructor_id: str | None = None
    duration_hours: int | None = Field(default=None, ge=1, le=1000)
    price: float | None = Field(default=None, ge=0.0)
    is_published: bool | None = None


class CoursePublic(APIModel):
    id: str
    title: str
    description: str
    instructor_id: str
    duration_hours: int
    price: float
    is_published: bool
    created_at: datetime
    updated_at: datetime
