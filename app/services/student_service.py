"""
Student service - business logic for student management.

Why: Service layer encapsulates business logic and orchestrates
repository operations, keeping routes clean and testable.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.core.permissions import is_admin
from app.models.student import Student
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.student import StudentCreate, StudentUpdate
from app.services.enrollment_registration import EnrollmentRegistration
from app.services.archive_actions import archive_record, load_for_maintenance, purge_record
from app.services.audit_service import AuditService
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError


class StudentService:
    def __init__(self, student_repo: StudentRepository, *, audit: AuditService | None = None) -> None:
        self._students = student_repo
        self._audit = audit

    async def get_student(self, student_id: str) -> Student:
        """Get a student by ID."""
        student = await self._students.get_by_id(student_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def get_student_by_user_id(self, user_id: str) -> Student:
        """Get a student by user_id."""
        student = await self._students.get_by_user_id(user_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def list_students(
        self,
        skip: int = 0,
        limit: int = 100,
        q: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Student], int]:
        """List students with search and pagination applied in MongoDB."""
        return await self._students.list_page(skip=skip, limit=limit, q=q, sort=sort)

    async def create_student(self, payload: StudentCreate) -> Student:
        """Create a new student."""
        try:
            return await self._students.create_student(
                user_id=payload.user_id,
                enrollment_date=payload.enrollment_date,
            )
        except ValueError as e:
            raise NotFoundError(str(e)) from e
        except DuplicateKeyError as e:
            raise ConflictError("Student already exists for this user") from e

    async def update_student(
        self,
        student_id: str,
        payload: StudentUpdate,
        *,
        enrollments: EnrollmentRepository | None = None,
    ) -> Student:
        """Update profile flags. A submitted course list is rebuilt from enrollments."""
        student = await self.get_student(student_id)
        align_courses = payload.enrolled_courses is not None

        update_data: dict[str, any] = {}
        if payload.is_active is not None:
            update_data["is_active"] = payload.is_active

        if update_data:
            from datetime import datetime, timezone
            update_data["updated_at"] = datetime.now(timezone.utc)
            student = await self._students.update(student_id, update_data)
            if student is None:
                raise NotFoundError("Student not found")
        if not align_courses:
            return student
        if enrollments is None:
            raise ConflictError("The student course list is derived from enrollments and was not replaced.")
        return await self._repair_course_list(student_id, enrollments)

    async def enroll_in_course(
        self,
        student_id: str,
        course_id: str,
        *,
        enrollments: EnrollmentRepository,
        courses: CourseRepository,
    ) -> Student:
        """Repair the compatibility list. This does not create an enrollment."""
        await self.get_student(student_id)
        if await courses.get_by_id(course_id) is None:
            raise NotFoundError("Course not found")
        return await self._repair_course_list(student_id, enrollments)

    async def unenroll_from_course(
        self,
        student_id: str,
        course_id: str,
        *,
        enrollments: EnrollmentRepository,
    ) -> Student:
        """Repair the compatibility list. This does not cancel an enrollment."""
        from bson import ObjectId

        await self.get_student(student_id)
        try:
            ObjectId(course_id)
        except Exception:
            raise NotFoundError("Course not found")
        return await self._repair_course_list(student_id, enrollments)

    async def _repair_course_list(self, student_id: str, enrollments: EnrollmentRepository) -> Student:
        return await EnrollmentRegistration(enrollments, self._students).repair_course_list(student_id)

    async def delete_student(
        self,
        student_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive a student profile. The row stays for audit."""
        if not is_admin(actor_role):
            raise ForbiddenError("Admin access required")
        student = await self.get_student(student_id)
        await archive_record(
            self._students,
            student,
            archived_by=archived_by,
            deactivate=True,
            audit=self._audit,
            action="student.delete",
            entity_type="student",
            not_found="Student not found",
        )

    async def purge_student(self, student_id: str, *, actor_role: str, actor_id: str) -> None:
        """Permanently remove a student profile. Super admin only."""
        student = await load_for_maintenance(self._students, student_id, not_found="Student not found")
        await purge_record(
            self._students,
            student,
            actor_role=actor_role,
            actor_id=actor_id,
            audit=self._audit,
            entity_type="student",
            not_found="Student not found",
        )
