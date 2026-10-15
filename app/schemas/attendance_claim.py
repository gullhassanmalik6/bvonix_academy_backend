from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.common import APIModel


class AttendanceCheckIn(APIModel):
    """A check-in names the course. The server assigns the UTC day and timestamp."""

    model_config = ConfigDict(extra="forbid")

    course_id: str


class AttendanceClaimDecision(APIModel):
    action: str = Field(pattern="^(approve|reject|mark_absent)$")
    reason: str | None = Field(default=None, max_length=500)


class AttendanceClaimBatch(APIModel):
    course_id: str
    session_date: datetime
    decisions: list[dict]


class AttendanceClaimPublic(APIModel):
    id: str
    student_id: str
    course_id: str
    enrollment_id: str
    session_date: datetime
    status: str
    submitted_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_reason: str | None
    attendance_id: str | None
    official_status: str | None = None


def claim_to_public(claim, official_status: str | None = None) -> AttendanceClaimPublic:
    return AttendanceClaimPublic(
        id=claim.id,
        student_id=claim.student_id,
        course_id=claim.course_id,
        enrollment_id=claim.enrollment_id,
        session_date=claim.session_date,
        status=claim.status,
        submitted_at=claim.submitted_at,
        reviewed_by=claim.reviewed_by,
        reviewed_at=claim.reviewed_at,
        review_reason=claim.review_reason,
        attendance_id=claim.attendance_id,
        official_status=official_status,
    )
