from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.scholarship_repository import ScholarshipRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.course_repository import CourseRepository
from app.services.notification_service import NotificationService
from app.schemas.scholarship import ScholarshipCreate, ScholarshipUpdate
from app.models.scholarship import Scholarship
from app.services.audit_service import AuditService, write_audit
from app.utils.exceptions import NotFoundError


class ScholarshipService:
    def __init__(
        self,
        scholarship_repo: ScholarshipRepository,
        notification_service: NotificationService | None = None,
        student_repo: StudentRepository | None = None,
        course_repo: CourseRepository | None = None,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._scholarships = scholarship_repo
        self._notifications = notification_service
        self._students = student_repo
        self._courses = course_repo
        self._audit = audit

    async def create_scholarship(self, payload: ScholarshipCreate) -> Scholarship:
        """Create a new scholarship."""
        scholarship = await self._scholarships.create_scholarship(
            student_id=payload.student_id,
            course_id=payload.course_id,
            enrollment_id=payload.enrollment_id,
            scholarship_type=payload.scholarship_type,
            amount=payload.amount,
            start_date=payload.start_date,
            end_date=payload.end_date,
            max_absences_per_month=payload.max_absences_per_month,
            notes=payload.notes,
        )
        await write_audit(
            self._audit,
            action="scholarship.create",
            entity_type="scholarship",
            entity_id=scholarship.id,
            current=scholarship,
        )
        return scholarship

    async def get_scholarship(self, scholarship_id: str) -> Scholarship:
        """Get a scholarship by ID."""
        scholarship = await self._scholarships.get_by_id(scholarship_id)
        if not scholarship:
            raise NotFoundError("Scholarship not found")
        return scholarship

    async def list_scholarships(
        self,
        skip: int = 0,
        limit: int = 100,
        student_id: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Scholarship], int]:
        """List scholarships with optional filters."""
        if student_id:
            scholarships = await self._scholarships.get_by_student(student_id, status)
        else:
            # Get all scholarships (for admin)
            all_scholarships = await self._scholarships.list(skip=0, limit=10000)
            scholarships = all_scholarships
        
        # Filter by status if provided
        if status:
            scholarships = [s for s in scholarships if s.status == status]
        
        total = len(scholarships)
        paginated = scholarships[skip:skip + limit]
        return paginated, total

    async def get_student_scholarships(self, student_id: str) -> list[Scholarship]:
        """Get all scholarships for a student."""
        return await self._scholarships.get_by_student(student_id)

    async def get_active_student_scholarships(self, student_id: str) -> list[Scholarship]:
        """Get active scholarships for a student."""
        return await self._scholarships.get_active_by_student(student_id)

    async def get_student_course_scholarships(self, student_id: str, course_id: str) -> list[Scholarship]:
        """Get scholarships for a student in a specific course."""
        return await self._scholarships.get_by_student_and_course(student_id, course_id)

    async def update_scholarship(self, scholarship_id: str, payload: ScholarshipUpdate) -> Scholarship:
        """Update a scholarship."""
        scholarship = await self.get_scholarship(scholarship_id)
        
        update_data: dict[str, any] = {}
        if payload.status is not None:
            update_data["status"] = payload.status
        if payload.amount is not None:
            update_data["amount"] = payload.amount
        if payload.end_date is not None:
            update_data["end_date"] = payload.end_date
        if payload.max_absences_per_month is not None:
            update_data["max_absences_per_month"] = payload.max_absences_per_month
        if payload.notes is not None:
            update_data["notes"] = payload.notes
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._scholarships.update(scholarship_id, update_data)
        if not updated:
            raise NotFoundError("Scholarship not found")
        await write_audit(
            self._audit,
            action="scholarship.update",
            entity_type="scholarship",
            entity_id=updated.id,
            previous=scholarship,
            current=updated,
        )
        return updated

    async def terminate_scholarship(self, scholarship_id: str, reason: str, terminated_by: str | None = None) -> Scholarship:
        """Terminate a scholarship and notify the student."""
        scholarship = await self.get_scholarship(scholarship_id)
        if scholarship.status == "terminated":
            return scholarship

        terminated = await self._scholarships.terminate_scholarship(scholarship_id, reason, terminated_by)
        if not terminated:
            raise NotFoundError("Scholarship not found")

        if self._notifications and self._students:
            student = await self._students.get_by_id(terminated.student_id)
            if student:
                course_title = None
                if terminated.course_id and self._courses:
                    course = await self._courses.get_by_id(terminated.course_id)
                    course_title = course.title if course else None
                await self._notifications.create_scholarship_terminated_notification(
                    user_id=student.user_id,
                    scholarship_id=terminated.id,
                    course_title=course_title,
                    reason=terminated.termination_reason,
                )

        await write_audit(
            self._audit,
            action="scholarship.terminate",
            entity_type="scholarship",
            entity_id=terminated.id,
            previous=scholarship,
            current=terminated,
        )
        return terminated

    async def delete_scholarship(self, scholarship_id: str) -> None:
        """Delete a scholarship."""
        scholarship = await self.get_scholarship(scholarship_id)
        deleted = await self._scholarships.delete(scholarship_id)
        if not deleted:
            raise NotFoundError("Scholarship not found")
        await write_audit(
            self._audit,
            action="scholarship.delete",
            entity_type="scholarship",
            entity_id=scholarship.id,
            previous=scholarship,
        )

    async def check_and_update_attendance(
        self,
        student_id: str,
        course_id: str,
        status: str,
    ) -> None:
        """
        Check attendance and update scholarship absence counts.
        Called when attendance is marked.
        """
        if status in ["present", "excused"]:
            return  # Don't count present or excused as absence
        
        # Get active scholarships for this student and course
        scholarships = await self._scholarships.get_by_student_and_course(student_id, course_id)
        active_scholarships = [s for s in scholarships if s.status == "active"]
        
        # Increment absence for each active scholarship and check for notifications
        for scholarship in active_scholarships:
            updated = await self._scholarships.increment_absence(scholarship.id)
            
            if updated and self._notifications and self._students:
                # Get student to get user_id
                student = await self._students.get_by_id(student_id)
                if student:
                    # Check if at risk (one absence away from termination)
                    if (
                        updated.status == "active" and
                        updated.current_month_absences == updated.max_absences_per_month - 1
                    ):
                        # Get course title for notification
                        course_title = None
                        if updated.course_id and self._courses:
                            course = await self._courses.get_by_id(updated.course_id)
                            course_title = course.title if course else None
                        
                        # Create at-risk notification
                        await self._notifications.create_scholarship_at_risk_notification(
                            user_id=student.user_id,
                            scholarship_id=updated.id,
                            course_title=course_title,
                            absences=updated.current_month_absences,
                            max_absences=updated.max_absences_per_month,
                        )
                    
                    # Check if terminated
                    if updated.status == "terminated":
                        # Get course title for notification
                        course_title = None
                        if updated.course_id and self._courses:
                            course = await self._courses.get_by_id(updated.course_id)
                            course_title = course.title if course else None
                        
                        # Create termination notification
                        await self._notifications.create_scholarship_terminated_notification(
                            user_id=student.user_id,
                            scholarship_id=updated.id,
                            course_title=course_title,
                            reason=updated.termination_reason,
                        )
