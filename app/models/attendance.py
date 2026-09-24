from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Attendance:
    """
    Domain model for student attendance.
    
    Tracks daily attendance for students in courses.
    """

    id: str
    student_id: str  # Reference to Student
    course_id: str  # Reference to Course
    enrollment_id: str  # Reference to Enrollment
    date: datetime  # Date of attendance
    status: str  # "present", "absent", "late", "excused"
    marked_by: str  # Instructor/Admin user_id
    notes: str | None
    absence_reason: str | None  # Reason submitted by student for absence
    absence_reason_submitted_at: datetime | None  # When student submitted reason
    is_excused: bool  # Whether absence is excused (approved by admin/instructor)
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
