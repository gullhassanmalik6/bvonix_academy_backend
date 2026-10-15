from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Assignment:
    """
    Domain model for course assignments.
    
    Defines assignments that students need to complete.
    """

    id: str
    course_id: str  # Reference to Course
    title: str
    description: str
    instructions: str | None
    due_date: datetime | None
    max_marks: float
    assignment_type: str  # "homework", "project", "quiz", "exam"
    is_published: bool
    created_by: str  # Instructor/Admin user_id
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)


@dataclass(slots=True)
class AssignmentSubmission:
    """
    Domain model for student assignment submissions.
    
    Tracks student submissions for assignments.
    """

    id: str
    assignment_id: str  # Reference to Assignment
    student_id: str  # Reference to Student
    course_id: str  # Reference to Course
    enrollment_id: str  # Reference to Enrollment
    submission_text: str | None  # Text submission
    file_urls: list[str]  # URLs to submitted files
    submitted_at: datetime
    status: str  # "pending", "submitted", "graded", "late", "resubmitted"
    marks_obtained: float | None
    feedback: str | None
    graded_by: str | None  # Instructor/Admin user_id
    graded_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
