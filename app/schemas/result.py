from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class ResultCreate(APIModel):
    student_id: str
    course_id: str
    enrollment_id: str
    assessment_type: str = Field(pattern="^(assignment|quiz|midterm|final|project)$")
    assessment_name: str = Field(min_length=1, max_length=200)
    marks_obtained: float = Field(ge=0.0)
    total_marks: float = Field(ge=1.0)
    feedback: str | None = Field(default=None, max_length=1000)
    issued_by: str


class ResultUpdate(APIModel):
    assessment_name: str | None = Field(default=None, min_length=1, max_length=200)
    marks_obtained: float | None = Field(default=None, ge=0.0)
    total_marks: float | None = Field(default=None, ge=1.0)
    feedback: str | None = Field(default=None, max_length=1000)


class ResultPublic(APIModel):
    id: str
    student_id: str
    course_id: str
    enrollment_id: str
    assessment_type: str
    assessment_name: str
    marks_obtained: float
    total_marks: float
    percentage: float
    grade: str
    feedback: str | None
    issued_by: str
    issued_date: datetime
    created_at: datetime
    updated_at: datetime
