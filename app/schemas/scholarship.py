from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class ScholarshipCreate(APIModel):
    student_id: str
    course_id: str | None = None  # None for all courses
    enrollment_id: str | None = None
    scholarship_type: str = Field(pattern="^(full|partial|entry_test|merit|custom)$")
    amount: float = Field(ge=0, le=100)  # Percentage (0-100) or fixed amount
    start_date: datetime
    end_date: datetime | None = None
    max_absences_per_month: int = Field(default=3, ge=1, le=30)
    notes: str | None = Field(default=None, max_length=1000)


class ScholarshipUpdate(APIModel):
    status: str | None = Field(default=None, pattern="^(active|terminated|expired|pending)$")
    amount: float | None = Field(default=None, ge=0, le=100)
    end_date: datetime | None = None
    max_absences_per_month: int | None = Field(default=None, ge=1, le=30)
    notes: str | None = Field(default=None, max_length=1000)


class ScholarshipPublic(APIModel):
    id: str
    student_id: str
    course_id: str | None
    enrollment_id: str | None
    scholarship_type: str
    amount: float
    status: str
    start_date: datetime
    end_date: datetime | None
    termination_reason: str | None
    terminated_at: datetime | None
    terminated_by: str | None
    max_absences_per_month: int
    current_month_absences: int
    current_month_start: datetime
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ScholarshipStatus(APIModel):
    """Simplified scholarship status for LMS dashboard."""
    id: str
    course_id: str | None
    course_title: str | None
    scholarship_type: str
    amount: float
    status: str
    current_month_absences: int
    max_absences_per_month: int
    days_remaining: int | None  # Days until end_date
    is_at_risk: bool  # True if absences >= max_absences - 1
