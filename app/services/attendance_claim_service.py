"""Student check-in stays pending until an administrator confirms attendance."""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.permissions import is_management
from app.schemas.attendance import AttendanceCreate
from app.services.audit_service import AuditService, write_audit
from app.services.fee_access import OVERDUE_DETAIL, is_learning_restricted
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError

PENDING = "pending_verification"
APPROVED = "approved"
REJECTED = "rejected"
FINAL_STATUSES = {"present", "absent", "late", "excused"}


def session_day(moment: datetime) -> datetime:
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    current = aware.astimezone(timezone.utc)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


def official_percentage(records: list) -> float:
    """Present divided by finalized marks. Pending and rejected claims are not records."""
    finalized = [item for item in records if getattr(item, "status", None) in FINAL_STATUSES]
    if not finalized:
        return 0.0
    present = sum(1 for item in finalized if item.status == "present")
    return round(present / len(finalized) * 100, 2)


class AttendanceClaimService:
    def __init__(self, claims, attendances, *, audit: AuditService | None = None) -> None:
        self._claims = claims
        self._attendances = attendances
        self._audit = audit

    async def submit_check_in(
        self,
        *,
        student_id: str,
        course_id: str,
        enrollment,
        now: datetime | None = None,
        payments: list | None = None,
        total_fee=0,
    ):
        if enrollment is None or enrollment.student_id != student_id or enrollment.course_id != course_id:
            raise ForbiddenError("You can only check in for your own enrolled course")
        moment = now or datetime.now(timezone.utc)
        # The UTC day comes from the server clock. A client date is not accepted.
        if payments is not None and is_learning_restricted(enrollment, payments, moment, total_fee):
            raise ForbiddenError(OVERDUE_DETAIL)
        day = session_day(moment)
        existing = await self._claims.find_for_session(student_id, course_id, day)
        if existing is not None:
            raise ConflictError("Attendance for this session was already submitted")
        try:
            claim = await self._claims.create_claim(
                student_id=student_id,
                course_id=course_id,
                enrollment_id=enrollment.id,
                session_date=day,
                submitted_at=moment,
            )
        except DuplicateKeyError:
            raise ConflictError("Attendance for this session was already submitted") from None
        await write_audit(
            self._audit,
            action="attendance.check_in",
            entity_type="attendance_claim",
            entity_id=claim.id,
            current=claim,
        )
        return claim

    async def decide(
        self,
        claim_id: str,
        *,
        action: str,
        reason: str | None,
        actor_id: str,
        actor_role: str,
    ):
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        claim = await self._claims.get_by_id(claim_id)
        if claim is None:
            raise NotFoundError("Attendance check-in not found")
        if claim.status != PENDING:
            raise ConflictError("This attendance check-in has already been reviewed")
        if action == "approve":
            return await self._approve(claim, actor_id=actor_id, actor_role=actor_role, reason=reason)
        if action == "reject":
            if not (reason or "").strip():
                raise ConflictError("A reason is required to reject a check-in")
            return await self._close(claim, status=REJECTED, actor_id=actor_id, reason=reason.strip(), attendance_id=None)
        if action == "mark_absent":
            if not (reason or "").strip():
                raise ConflictError("A reason is required to mark a student absent")
            attendance = await self._official(
                claim,
                status="absent",
                actor_id=actor_id,
                notes=reason.strip(),
            )
            return await self._close(
                claim,
                status=REJECTED,
                actor_id=actor_id,
                reason=reason.strip(),
                attendance_id=attendance.id,
            )
        raise ConflictError("Unknown attendance action")

    async def mark_absent_without_claim(
        self,
        *,
        student_id: str,
        course_id: str,
        enrollment_id: str,
        session_date: datetime,
        actor_id: str,
        actor_role: str,
        reason: str,
    ):
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        if not (reason or "").strip():
            raise ConflictError("A reason is required to mark a student absent")
        day = session_day(session_date)
        attendance = await self._attendances.create_attendance(
            AttendanceCreate(
                student_id=student_id,
                course_id=course_id,
                enrollment_id=enrollment_id,
                date=day,
                status="absent",
                marked_by=actor_id,
                notes=reason.strip(),
            )
        )
        await write_audit(
            self._audit,
            action="attendance.mark_absent",
            entity_type="attendance",
            entity_id=attendance.id,
            actor_id=actor_id,
            actor_role=actor_role,
            current=attendance,
        )
        return attendance

    async def _approve(self, claim, *, actor_id: str, actor_role: str, reason: str | None):
        attendance = await self._official(claim, status="present", actor_id=actor_id, notes=reason)
        return await self._close(
            claim,
            status=APPROVED,
            actor_id=actor_id,
            reason=(reason or "").strip() or None,
            attendance_id=attendance.id,
        )

    async def _official(self, claim, *, status: str, actor_id: str, notes: str | None):
        existing = await self._attendances.get_attendance_by_session(
            claim.student_id, claim.course_id, claim.session_date
        ) if hasattr(self._attendances, "get_attendance_by_session") else None
        if existing is not None:
            raise ConflictError("An official attendance record already exists for this session")
        return await self._attendances.create_attendance(
            AttendanceCreate(
                student_id=claim.student_id,
                course_id=claim.course_id,
                enrollment_id=claim.enrollment_id,
                date=claim.session_date,
                status=status,
                marked_by=actor_id,
                notes=notes,
            )
        )

    async def _close(self, claim, *, status: str, actor_id: str, reason: str | None, attendance_id: str | None):
        now = datetime.now(timezone.utc)
        updated = await self._claims.update(
            claim.id,
            {
                "status": status,
                "reviewed_by": actor_id,
                "reviewed_at": now,
                "review_reason": reason,
                "attendance_id": attendance_id,
                "updated_at": now,
            },
        )
        if updated is None:
            raise NotFoundError("Attendance check-in not found")
        action = "attendance.approve" if status == APPROVED else "attendance.reject"
        await write_audit(
            self._audit,
            action=action,
            entity_type="attendance_claim",
            entity_id=claim.id,
            actor_id=actor_id,
            previous=claim,
            current=updated,
            context={"reason": reason} if reason else None,
        )
        return updated
