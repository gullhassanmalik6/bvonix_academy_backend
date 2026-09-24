from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class CertificateCreate(APIModel):
    student_id: str
    course_id: str
    enrollment_id: str
    completion_date: datetime
    grade: str | None = Field(default=None, max_length=10)
    issued_by: str
    certificate_url: str | None = Field(default=None, max_length=500)


class CertificateUpdate(APIModel):
    certificate_url: str | None = Field(default=None, max_length=500)
    is_verified: bool | None = None


class CertificatePublic(APIModel):
    id: str
    student_id: str
    course_id: str
    enrollment_id: str
    certificate_number: str
    issue_date: datetime
    completion_date: datetime
    grade: str | None
    issued_by: str
    certificate_url: str | None
    is_verified: bool
    created_at: datetime
    updated_at: datetime
