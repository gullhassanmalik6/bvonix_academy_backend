from __future__ import annotations

from datetime import datetime

from app.core.permissions import is_admin
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.scholarship_repository import ScholarshipRepository
from app.services.scholarship_service import ScholarshipService
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate
from app.models.attendance import Attendance
from app.services.archive_actions import archive_record, load_for_maintenance, purge_record
from app.services.audit_service import AuditService, write_audit
from app.utils.exceptions import ForbiddenError, NotFoundError


class AttendanceService:
    def __init__(
        self,
        attendance_repo: AttendanceRepository,
        scholarship_repo: ScholarshipRepository | None = None,
        scholarship_service: ScholarshipService | None = None,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._attendances = attendance_repo
        self._scholarships = scholarship_repo
        self._scholarship_service = scholarship_service
        self._audit = audit

    async def create_attendance(self, payload: AttendanceCreate) -> Attendance:
        """Create attendance and check scholarships."""
        attendance = await self._attendances.create_attendance(
            student_id=payload.student_id,
            course_id=payload.course_id,
            enrollment_id=payload.enrollment_id,
            date=payload.date,
            status=payload.status,
            marked_by=payload.marked_by,
            notes=payload.notes,
            absence_reason=payload.absence_reason,
            is_excused=payload.is_excused,
        )
        
        # Check and update scholarships if status is absent/late and not excused
        if payload.status in ["absent", "late"] and not payload.is_excused:
            if self._scholarship_service:
                try:
                    # Use scholarship service which handles notifications
                    await self._scholarship_service.check_and_update_attendance(
                        payload.student_id,
                        payload.course_id,
                        payload.status,
                    )
                except Exception:
                    # Don't fail attendance creation if scholarship check fails
                    pass
            elif self._scholarships:
                # Fallback to direct repository call if service not available
                try:
                    scholarships = await self._scholarships.get_by_student_and_course(
                        payload.student_id,
                        payload.course_id,
                    )
                    active_scholarships = [s for s in scholarships if s.status == "active"]
                    
                    # Increment absence for each active scholarship
                    for scholarship in active_scholarships:
                        await self._scholarships.increment_absence(scholarship.id)
                except Exception:
                    # Don't fail attendance creation if scholarship check fails
                    pass
        
        await write_audit(
            self._audit,
            action="attendance.create",
            entity_type="attendance",
            entity_id=attendance.id,
            current=attendance,
        )
        return attendance

    async def get_attendance(self, attendance_id: str) -> Attendance:
        """Get attendance by ID."""
        attendance = await self._attendances.get_by_id(attendance_id)
        if not attendance:
            raise NotFoundError("Attendance not found")
        return attendance

    async def update_attendance(self, attendance_id: str, payload: AttendanceUpdate) -> Attendance:
        """Update attendance."""
        attendance = await self.get_attendance(attendance_id)
        
        update_data: dict[str, any] = {}
        if payload.status is not None:
            update_data["status"] = payload.status
        if payload.notes is not None:
            update_data["notes"] = payload.notes
        
        update_data["updated_at"] = datetime.now()
        
        updated = await self._attendances.update(attendance_id, update_data)
        if not updated:
            raise NotFoundError("Attendance not found")
        
        # If status changed to absent/late, check scholarships
        if payload.status and payload.status in ["absent", "late"]:
            if self._scholarship_service:
                try:
                    # Use scholarship service which handles notifications
                    await self._scholarship_service.check_and_update_attendance(
                        attendance.student_id,
                        attendance.course_id,
                        payload.status,
                    )
                except Exception:
                    pass
            elif self._scholarships:
                # Fallback to direct repository call if service not available
                try:
                    scholarships = await self._scholarships.get_by_student_and_course(
                        attendance.student_id,
                        attendance.course_id,
                    )
                    active_scholarships = [s for s in scholarships if s.status == "active"]
                    
                    for scholarship in active_scholarships:
                        await self._scholarships.increment_absence(scholarship.id)
                except Exception:
                    pass
        
        await write_audit(
            self._audit,
            action="attendance.update",
            entity_type="attendance",
            entity_id=updated.id,
            previous=attendance,
            current=updated,
        )
        return updated

    async def apply_corrected_status(self, attendance_id: str, status: str) -> Attendance:
        """Apply an approved correction. The existing update path keeps scholarship checks."""
        updated = await self.update_attendance(attendance_id, AttendanceUpdate(status=status))
        excused = status == "excused"
        if updated.is_excused == excused:
            return updated
        fixed = await self._attendances.update(
            attendance_id,
            {"is_excused": excused, "updated_at": datetime.now()},
        )
        return fixed or updated

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> list[Attendance]:
        """Get all attendance records for a student in a course."""
        return await self._attendances.get_by_student_and_course(student_id, course_id)

    async def get_attendance_stats(self, student_id: str, course_id: str) -> dict[str, int]:
        """Get attendance statistics."""
        return await self._attendances.get_attendance_stats(student_id, course_id)

    async def submit_absence_reason(self, attendance_id: str, reason: str) -> Attendance:
        """Submit absence reason for an attendance record."""
        attendance = await self.get_attendance(attendance_id)
        
        # Only allow submitting reason for absent/late status
        if attendance.status not in ["absent", "late"]:
            raise ValueError("Can only submit reason for absent or late attendance")
        
        updated = await self._attendances.submit_absence_reason(attendance_id, reason)
        if not updated:
            raise NotFoundError("Attendance not found")
        return updated

    async def delete_attendance(
        self,
        attendance_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive an attendance mark. The row stays for audit."""
        if not is_admin(actor_role):
            raise ForbiddenError("Admin access required")
        attendance = await self.get_attendance(attendance_id)
        await archive_record(
            self._attendances,
            attendance,
            archived_by=archived_by,
            deactivate=False,
            audit=self._audit,
            action="attendance.delete",
            entity_type="attendance",
            not_found="Attendance not found",
        )

    async def purge_attendance(self, attendance_id: str, *, actor_role: str, actor_id: str) -> None:
        """Permanently remove an attendance mark. Super admin only."""
        attendance = await load_for_maintenance(self._attendances, attendance_id, not_found="Attendance not found")
        await purge_record(
            self._attendances,
            attendance,
            actor_role=actor_role,
            actor_id=actor_id,
            audit=self._audit,
            entity_type="attendance",
            not_found="Attendance not found",
        )
