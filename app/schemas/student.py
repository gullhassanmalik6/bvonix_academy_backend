from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class StudentCreate(APIModel):
    user_id: str
    enrollment_date: datetime | None = None


class StudentUpdate(APIModel):
    enrolled_courses: list[str] | None = None
    is_active: bool | None = None


class StudentPublic(APIModel):
    id: str
    user_id: str
    enrollment_date: datetime
    enrolled_courses: list[str]
    is_active: bool = True  # Default to True if missing
    created_at: datetime
    updated_at: datetime
