from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class AssignmentCreate(APIModel):
    course_id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    instructions: str | None = Field(default=None, max_length=5000)
    due_date: datetime | None = None
    max_marks: float = Field(..., ge=0)
    assignment_type: str = Field(pattern="^(homework|project|quiz|exam)$")
    is_published: bool = True


class AssignmentUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    instructions: str | None = Field(default=None, max_length=5000)
    due_date: datetime | None = None
    max_marks: float | None = Field(default=None, ge=0)
    is_published: bool | None = None


class AssignmentPublic(APIModel):
    id: str
    course_id: str
    title: str
    description: str
    instructions: str | None
    due_date: datetime | None
    max_marks: float
    assignment_type: str
    is_published: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class AssignmentSubmissionCreate(APIModel):
    assignment_id: str
    submission_text: str | None = Field(default=None, max_length=10000)
    file_urls: list[str] = Field(default_factory=list)


class AssignmentSubmissionUpdate(APIModel):
    submission_text: str | None = Field(default=None, max_length=10000)
    file_urls: list[str] | None = None


class AssignmentSubmissionPublic(APIModel):
    id: str
    assignment_id: str
    student_id: str
    course_id: str
    enrollment_id: str
    submission_text: str | None
    file_urls: list[str]
    submitted_at: datetime
    status: str
    marks_obtained: float | None
    feedback: str | None
    graded_by: str | None
    graded_at: datetime | None
    created_at: datetime
    updated_at: datetime
