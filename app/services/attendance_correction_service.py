from __future__ import annotations

from dataclasses import replace

from pymongo.errors import DuplicateKeyError

from app.core.attendance_correction import (
    APPROVED,
    ATTENDANCE_STATUSES,
    REJECTED,
    REQUESTED,
    UNDER_REVIEW,
    assert_correction_transition,
)
from app.core.permissions import is_management
from app.models.attendance_correction import AttendanceCorrection
from app.repositories.archival import record_is_active
from app.repositories.attendance_correction_repository import AttendanceCorrectionRepository
from app.services.attendance_service import AttendanceService
from app.services.audit_service import AuditService
from app.utils.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError


class AttendanceCorrectionService:
    def __init__(
        self,
        corrections: AttendanceCorrectionRepository,
        attendance: AttendanceService,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._corrections = corrections
        self._attendance = attendance
        self._audit = audit

    async def request_correction(
        self,
        *,
        attendance_id: str,
        student_id: str,
        requester_id: str,
        reason: str,
        requested_status: str,
    ) -> AttendanceCorrection:
        """A student asks for their own mark to be changed."""
        cleaned_reason = reason.strip()
        if len(cleaned_reason) < 10:
            raise ConflictError("A correction reason must be at least 10 characters")
        if requested_status not in ATTENDANCE_STATUSES:
            raise ConflictError("Requested attendance status is not valid")

        attendance = await self._attendance.get_attendance(attendance_id)
        if not record_is_active(attendance) or attendance.student_id != student_id:
            raise NotFoundError("Attendance not found")
        if requested_status == attendance.status:
            raise ConflictError("Requested status matches the current attendance mark")

        existing = await self._corrections.find_open_for_attendance(attendance_id)
        if existing is not None:
            raise ConflictError("This attendance mark already has an open correction request")

        now = AttendanceCorrection.now_utc()
        draft = AttendanceCorrection(
            id="",
            attendance_id=attendance.id,
            student_id=attendance.student_id,
            course_id=attendance.course_id,
            enrollment_id=attendance.enrollment_id,
            requester_id=requester_id,
            reviewer_id=None,
            reason=cleaned_reason,
            previous_status=attendance.status,
            previous_is_excused=attendance.is_excused,
            requested_status=requested_status,
            status=REQUESTED,
            decision=None,
            requested_at=now,
            review_started_at=None,
            reviewed_at=None,
            review_note=None,
            created_at=now,
            updated_at=now,
        )
        try:
            return await self._corrections.create_request(draft)
        except DuplicateKeyError as exc:
            raise ConflictError("This attendance mark already has an open correction request") from exc

    async def list_corrections(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        open_only: bool = False,
        student_id: str | None = None,
        course_id: str | None = None,
    ) -> tuple[list[AttendanceCorrection], int]:
        return await self._corrections.list_page(
            skip=skip,
            limit=limit,
            status=status,
            open_only=open_only,
            student_id=student_id,
            course_id=course_id,
        )

    async def start_review(
        self,
        correction_id: str,
        *,
        actor_id: str,
        actor_role: str,
    ) -> AttendanceCorrection:
        self._require_reviewer(actor_role)
        correction = await self._get(correction_id)
        assert_correction_transition(correction.status, UNDER_REVIEW)
        now = AttendanceCorrection.now_utc()
        updated = replace(
            correction,
            status=UNDER_REVIEW,
            reviewer_id=actor_id,
            review_started_at=now,
            updated_at=now,
        )
        return await self._save(updated)

    async def approve(
        self,
        correction_id: str,
        *,
        actor_id: str,
        actor_role: str,
        review_note: str | None = None,
    ) -> AttendanceCorrection:
        self._require_reviewer(actor_role)
        correction = await self._get(correction_id)
        assert_correction_transition(correction.status, APPROVED)
        await self._attendance.apply_corrected_status(correction.attendance_id, correction.requested_status)
        now = AttendanceCorrection.now_utc()
        updated = replace(
            correction,
            status=APPROVED,
            decision=APPROVED,
            reviewer_id=actor_id,
            reviewed_at=now,
            review_note=_clean_note(review_note),
            updated_at=now,
        )
        saved = await self._save(updated)
        await self._audit_decision(
            action="attendance_correction.approve",
            previous=correction,
            current=saved,
            actor_id=actor_id,
            actor_role=actor_role,
        )
        return saved

    async def reject(
        self,
        correction_id: str,
        *,
        actor_id: str,
        actor_role: str,
        review_note: str | None = None,
    ) -> AttendanceCorrection:
        self._require_reviewer(actor_role)
        correction = await self._get(correction_id)
        assert_correction_transition(correction.status, REJECTED)
        now = AttendanceCorrection.now_utc()
        updated = replace(
            correction,
            status=REJECTED,
            decision=REJECTED,
            reviewer_id=actor_id,
            reviewed_at=now,
            review_note=_clean_note(review_note),
            updated_at=now,
        )
        saved = await self._save(updated)
        await self._audit_decision(
            action="attendance_correction.reject",
            previous=correction,
            current=saved,
            actor_id=actor_id,
            actor_role=actor_role,
        )
        return saved

    def _require_reviewer(self, actor_role: str) -> None:
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")

    async def _get(self, correction_id: str) -> AttendanceCorrection:
        correction = await self._corrections.get_by_id(correction_id)
        if correction is None:
            raise NotFoundError("Attendance correction not found")
        return correction

    async def _save(self, correction: AttendanceCorrection) -> AttendanceCorrection:
        saved = await self._corrections.save(correction)
        if saved is None:
            raise NotFoundError("Attendance correction not found")
        return saved

    async def _audit_decision(
        self,
        *,
        action: str,
        previous: AttendanceCorrection,
        current: AttendanceCorrection,
        actor_id: str,
        actor_role: str,
    ) -> None:
        if self._audit is None:
            raise AppError("Audit log is unavailable")
        logged = await self._audit.record(
            action=action,
            entity_type="attendance_correction",
            entity_id=current.id,
            previous=previous,
            current=current,
            actor_id=actor_id,
            actor_role=actor_role,
            context={
                "decision": current.decision,
                "previous_attendance_status": current.previous_status,
                "new_attendance_status": current.requested_status,
                "requester_id": current.requester_id,
                "reviewer_id": current.reviewer_id,
            },
        )
        if logged is None:
            raise AppError("Audit log could not be written")


def _clean_note(review_note: str | None) -> str | None:
    if review_note is None:
        return None
    cleaned = review_note.strip()
    return cleaned or None
