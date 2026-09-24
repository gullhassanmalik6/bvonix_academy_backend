from __future__ import annotations

from typing import List

from pydantic import Field

from app.schemas.common import APIModel


class StudentCardDataInput(APIModel):
    """Dynamic card payload for PDF generation."""

    academy_name: str | None = None
    student_name: str
    student_id: str
    father_name: str | None = None
    course: str
    batch: str | None = None
    enrollment_date: str | None = None
    valid_until: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    phone: str | None = None
    email: str | None = None
    campus: str | None = None
    address: str | None = None
    profile_image_url: str | None = None
    verify_url: str | None = None
    website: str | None = None
    support_email: str | None = None
    support_phone: str | None = None


class StudentCardGenerateRequest(APIModel):
    data: StudentCardDataInput


class StudentCardBulkItem(APIModel):
    filename: str | None = None
    data: StudentCardDataInput


class StudentCardBulkGenerateRequest(APIModel):
    students: List[StudentCardBulkItem] = Field(..., min_length=1, max_length=100)


class StudentCardVerifyResponse(APIModel):
    valid: bool
    card_number: str
    student_name: str | None = None
    course_name: str | None = None
    batch: str | None = None
    enrollment_date: str | None = None
    verified_by_admin: bool = False
    message: str
