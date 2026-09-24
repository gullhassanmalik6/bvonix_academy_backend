from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Certificate:
    """
    Domain model for course completion certificates.
    
    Stores certificate information for students who complete courses.
    """

    id: str
    student_id: str  # Reference to Student
    course_id: str  # Reference to Course
    enrollment_id: str  # Reference to Enrollment
    certificate_number: str  # Unique certificate number
    issue_date: datetime
    completion_date: datetime
    grade: str | None  # Final grade if applicable
    issued_by: str  # Admin/Instructor user_id
    certificate_url: str | None  # URL to certificate file/PDF
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
