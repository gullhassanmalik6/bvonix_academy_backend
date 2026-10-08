from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class AttendanceCorrection:
    """A request to change one existing attendance mark."""

    id: str
    attendance_id: str
    student_id: str
    course_id: str
    enrollment_id: str
    requester_id: str
    reviewer_id: str | None
    reason: str
    previous_status: str
    previous_is_excused: bool
    requested_status: str
    status: str
    decision: str | None
    requested_at: datetime
    review_started_at: datetime | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
