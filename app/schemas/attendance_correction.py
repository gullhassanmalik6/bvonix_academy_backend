from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.attendance_correction import AttendanceCorrection
from app.schemas.common import APIModel


class AttendanceCorrectionCreate(APIModel):
    reason: str = Field(min_length=10, max_length=1000)
    requested_status: str = Field(pattern="^(present|absent|late|excused)$")


class AttendanceCorrectionDecision(APIModel):
    review_note: str | None = Field(default=None, max_length=1000)


class AttendanceCorrectionPublic(APIModel):
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


def correction_to_public(correction: AttendanceCorrection) -> AttendanceCorrectionPublic:
    return AttendanceCorrectionPublic(
        id=correction.id,
        attendance_id=correction.attendance_id,
        student_id=correction.student_id,
        course_id=correction.course_id,
        enrollment_id=correction.enrollment_id,
        requester_id=correction.requester_id,
        reviewer_id=correction.reviewer_id,
        reason=correction.reason,
        previous_status=correction.previous_status,
        previous_is_excused=correction.previous_is_excused,
        requested_status=correction.requested_status,
        status=correction.status,
        decision=correction.decision,
        requested_at=correction.requested_at,
        review_started_at=correction.review_started_at,
        reviewed_at=correction.reviewed_at,
        review_note=correction.review_note,
        created_at=correction.created_at,
        updated_at=correction.updated_at,
    )
