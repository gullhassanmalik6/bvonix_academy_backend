from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class InstructorCreate(APIModel):
    user_id: str
    bio: str | None = Field(default=None, max_length=2000)
    specialization: str | None = Field(default=None, max_length=200)
    years_of_experience: int | None = Field(default=None, ge=0, le=100)


class InstructorUpdate(APIModel):
    bio: str | None = Field(default=None, max_length=2000)
    specialization: str | None = Field(default=None, max_length=200)
    years_of_experience: int | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None


class InstructorPublic(APIModel):
    id: str
    user_id: str
    bio: str | None
    specialization: str | None
    years_of_experience: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
