from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Result:
    """
    Domain model for student results/grades.
    
    Stores grades, marks, and feedback for students in courses.
    """

    id: str
    student_id: str  # Reference to Student
    course_id: str  # Reference to Course
    enrollment_id: str  # Reference to Enrollment
    assessment_type: str  # "assignment", "quiz", "midterm", "final", "project"
    assessment_name: str
    marks_obtained: float
    total_marks: float
    percentage: float
    grade: str  # "A+", "A", "B+", "B", "C+", "C", "D", "F"
    feedback: str | None
    issued_by: str  # Instructor/Admin user_id
    issued_date: datetime
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
