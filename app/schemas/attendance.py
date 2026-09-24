from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class AttendanceCreate(APIModel):
    student_id: str
    course_id: str
    enrollment_id: str
    date: datetime
    status: str = Field(pattern="^(present|absent|late|excused)$")
    marked_by: str
    notes: str | None = Field(default=None, max_length=500)
    absence_reason: str | None = Field(default=None, max_length=1000)
    is_excused: bool = False


class AttendanceUpdate(APIModel):
    status: str | None = Field(default=None, pattern="^(present|absent|late|excused)$")
    notes: str | None = Field(default=None, max_length=500)
    absence_reason: str | None = Field(default=None, max_length=1000)
    is_excused: bool | None = None


class AttendancePublic(APIModel):
    id: str
    student_id: str
    course_id: str
    enrollment_id: str
    date: datetime
    status: str
    marked_by: str
    notes: str | None
    absence_reason: str | None
    absence_reason_submitted_at: datetime | None
    is_excused: bool
    created_at: datetime
    updated_at: datetime


class AbsenceReasonSubmit(APIModel):
    """Schema for students to submit absence reasons."""
    absence_reason: str = Field(..., min_length=10, max_length=1000, description="Reason for absence")
