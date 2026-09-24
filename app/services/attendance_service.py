from __future__ import annotations

from datetime import datetime

from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.scholarship_repository import ScholarshipRepository
from app.services.scholarship_service import ScholarshipService
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate
from app.models.attendance import Attendance
from app.utils.exceptions import NotFoundError


class AttendanceService:
    def __init__(
        self,
        attendance_repo: AttendanceRepository,
        scholarship_repo: ScholarshipRepository | None = None,
        scholarship_service: ScholarshipService | None = None,
    ) -> None:
        self._attendances = attendance_repo
        self._scholarships = scholarship_repo
        self._scholarship_service = scholarship_service

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
        
        return updated

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

    async def delete_attendance(self, attendance_id: str) -> None:
        """Delete attendance."""
        attendance = await self.get_attendance(attendance_id)
        deleted = await self._attendances.delete(attendance_id)
        if not deleted:
            raise NotFoundError("Attendance not found")
