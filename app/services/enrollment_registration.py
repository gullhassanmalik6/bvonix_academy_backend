"""Recoverable enrollment creation and cancellation.

The enrollment document is the registration record. The unique
(student_id, course_id) index remains the duplicate guard. students.enrolled_courses
is a compatibility list derived from enrollments that are not cancelled.

This process does not open a MongoDB transaction. A standalone server cannot
run multi-document transactions, and this deployment does not require a replica
set. A failed list update is repaired by repeating the same request.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.enrollment_workflow import (
    assert_enrollment_transition,
    enrollment_transition_updates,
    workflow_state,
)
from app.core.permissions import is_management
from app.models.enrollment import Enrollment
from app.models.student import Student
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.enrollment import EnrollmentCreate
from app.services.audit_service import (
    AuditService,
    commit_required_decision,
    recover_pending_decision,
    snapshot,
)
from app.utils.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


class RegistrationReconcileError(AppError):
    """The enrollment write succeeded and the compatibility list still needs a retry."""

    def __init__(self) -> None:
        super().__init__(
            "The enrollment was saved, but the student course list could not be updated. Retry the request.",
            status_code=500,
        )


class EnrollmentRegistration:
    def __init__(
        self,
        enrollments: EnrollmentRepository,
        students: StudentRepository,
        courses: CourseRepository | None = None,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._enrollments = enrollments
        self._students = students
        self._courses = courses
        self._audit = audit

    async def reconcile_enrolled_courses(self, student_id: str) -> Student:
        """Set enrolled_courses from non-cancelled enrollments. Safe to repeat."""
        student = await self._students.get_by_id(student_id)
        if student is None:
            raise NotFoundError("Student not found")
        course_ids = await self._enrollments.registration_course_ids(student_id)
        if set(student.enrolled_courses) == set(course_ids):
            return student
        updated = await self._students.set_enrolled_courses(student_id, course_ids)
        if updated is None:
            raise NotFoundError("Student not found")
        return updated

    async def repair_course_list(self, student_id: str) -> Student:
        """Rewrite the compatibility list from enrollments. A failed write can be retried."""
        return await self._reconcile_or_retry(student_id)

    async def _reconcile_or_retry(self, student_id: str) -> Student:
        try:
            return await self.reconcile_enrolled_courses(student_id)
        except NotFoundError:
            raise
        except Exception as exc:
            logger.warning(
                "Enrollment course-list reconcile failed for student %s (%s)",
                student_id,
                type(exc).__name__,
            )
            raise RegistrationReconcileError() from exc

    async def _student_for_user(self, user_id: str) -> Student:
        existing = await self._students.get_by_user_id(user_id)
        if existing is not None:
            return existing
        try:
            return await self._students.create_student(
                user_id=user_id,
                enrollment_date=datetime.now(timezone.utc),
            )
        except DuplicateKeyError:
            existing = await self._students.get_by_user_id(user_id)
            if existing is None:
                raise ConflictError("Student profile could not be created")
            return existing
        except ValueError as exc:
            raise NotFoundError("Student not found") from exc

    async def _existing_registration(self, student_id: str, course_id: str) -> Enrollment:
        """Repair the compatibility list, then return or reject the stored enrollment."""
        existing = await self._enrollments.get_by_student_and_course(student_id, course_id)
        if existing is None:
            raise ConflictError("Enrollment could not be created")
        student = await self._students.get_by_id(student_id)
        listed = student is not None and course_id in student.enrolled_courses
        await self._reconcile_or_retry(student_id)
        if existing.status == "cancelled":
            raise ConflictError("This course enrollment is cancelled")
        if listed:
            raise ConflictError("Already enrolled in this course")
        return existing

    async def enroll(self, user_id: str, course_id: str, payload: EnrollmentCreate) -> Enrollment:
        """Create one pending enrollment. A retry repairs the compatibility list."""
        if self._courses is None or await self._courses.get_by_id(course_id) is None:
            raise NotFoundError("Course not found")
        student = await self._student_for_user(user_id)
        existing = await self._enrollments.get_by_student_and_course(student.id, course_id)
        if existing is not None:
            return await self._existing_registration(student.id, course_id)
        try:
            created = await self._enrollments.create_enrollment(
                student_id=student.id,
                course_id=course_id,
                payment_status="pending",
                class_type=payload.class_type,
                phone_number=payload.phone_number,
                address=payload.address,
                emergency_contact_name=payload.emergency_contact_name,
                emergency_contact_phone=payload.emergency_contact_phone,
                father_guardian_name=payload.father_guardian_name,
                date_of_birth=payload.date_of_birth,
                gender=payload.gender,
                profile_image_url=payload.profile_image_url,
            )
        except DuplicateKeyError:
            logger.warning(
                "Duplicate enrollment insert for student %s and course %s",
                student.id,
                course_id,
            )
            return await self._existing_registration(student.id, course_id)
        except ValueError as exc:
            raise NotFoundError("Course not found") from exc
        await self._reconcile_or_retry(student.id)
        return created

    async def cancel(self, enrollment_id: str, *, actor_id: str, actor_role: str) -> Enrollment:
        """Cancel the enrollment, then derive the compatibility list again."""
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        enrollment = await self._enrollments.get_by_id(enrollment_id)
        if enrollment is None:
            raise NotFoundError("Enrollment not found")
        pending = enrollment.audit_pending if isinstance(enrollment.audit_pending, dict) else None
        if pending and self._audit is not None:
            async def clear_pending():
                return await self._enrollments.update(enrollment.id, {"audit_pending": None})

            await recover_pending_decision(self._audit, enrollment, clear_pending)
            enrollment = await self._enrollments.get_by_id(enrollment_id) or enrollment
        if enrollment.status != "cancelled":
            assert_enrollment_transition(
                actor_role,
                workflow_state(enrollment),
                "cancelled",
                owns_enrollment=False,
            )
            updates = enrollment_transition_updates(enrollment, "cancelled", actor_id=actor_id)
            if self._audit is not None:
                updated = await commit_required_decision(
                    self._audit,
                    lambda data: self._enrollments.update(enrollment_id, data),
                    action="enrollment.cancel",
                    entity_type="enrollment",
                    entity_id=enrollment.id,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    previous=enrollment,
                    updates=updates,
                )
            else:
                updated = await self._enrollments.update(enrollment_id, updates)
            if updated is None:
                raise NotFoundError("Enrollment not found")
            enrollment = updated
        await self._reconcile_or_retry(enrollment.student_id)
        return enrollment
