from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Scholarship:
    """
    Domain model for student scholarships.
    
    Tracks scholarship status, type, amount, and validation rules.
    Scholarships can be terminated if attendance rules are violated.
    """

    id: str
    student_id: str  # Reference to Student
    course_id: str  # Reference to Course (optional, can be for all courses)
    enrollment_id: str | None  # Reference to Enrollment (optional)
    scholarship_type: str  # "full", "partial", "entry_test", "merit", etc.
    amount: float  # Scholarship amount (percentage or fixed)
    status: str  # "active", "terminated", "expired", "pending"
    start_date: datetime
    end_date: datetime | None  # None for indefinite scholarships
    termination_reason: str | None  # Reason if terminated
    terminated_at: datetime | None
    terminated_by: str | None  # Admin/Instructor user_id
    max_absences_per_month: int  # Default: 3
    current_month_absences: int  # Absences in current month
    current_month_start: datetime  # Start of current tracking month
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
