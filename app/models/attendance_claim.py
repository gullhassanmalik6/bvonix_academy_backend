from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class AttendanceClaim:
    """A student check-in that is not official until an administrator approves it."""

    id: str
    student_id: str
    course_id: str
    enrollment_id: str
    session_date: datetime
    status: str  # pending_verification, approved, rejected
    submitted_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_reason: str | None
    attendance_id: str | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
