from __future__ import annotations

from datetime import datetime, timezone

from app.core.permissions import is_management
from app.repositories.assignment_repository import AssignmentRepository, AssignmentSubmissionRepository
from app.repositories.course_repository import CourseRepository
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentSubmissionCreate,
    AssignmentSubmissionUpdate,
    AssignmentUpdate,
)
from app.models.assignment import Assignment, AssignmentSubmission
from app.services.archive_actions import archive_record
from app.services.audit_service import AuditService, write_audit
from app.services.course_service import course_is_operational, require_active_course
from app.utils.exceptions import ForbiddenError, NotFoundError


class AssignmentService:
    def __init__(
        self,
        assignment_repo: AssignmentRepository,
        submission_repo: AssignmentSubmissionRepository,
        *,
        courses: CourseRepository | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._assignments = assignment_repo
        self._submissions = submission_repo
        self._courses = courses
        self._audit = audit

    async def create_assignment(self, payload: AssignmentCreate, created_by: str) -> Assignment:
        """Create a new assignment."""
        await require_active_course(self._courses, payload.course_id)
        return await self._assignments.create_assignment(
            course_id=payload.course_id,
            title=payload.title,
            description=payload.description,
            instructions=payload.instructions,
            due_date=payload.due_date,
            max_marks=payload.max_marks,
            assignment_type=payload.assignment_type,
            is_published=payload.is_published,
            created_by=created_by,
        )

    async def get_assignment(self, assignment_id: str) -> Assignment:
        """Get assignment by ID."""
        assignment = await self._assignments.get_by_id(assignment_id)
        if not assignment:
            raise NotFoundError("Assignment not found")
        return assignment

    async def list_course_assignments(
        self,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        published_only: bool = False,
    ) -> tuple[list[Assignment], int]:
        """Page assignments for one course without loading the whole set into Python."""
        if not await course_is_operational(self._courses, course_id):
            return [], 0
        return await self._assignments.list_page(
            course_id, skip=skip, limit=limit, published_only=published_only
        )

    async def get_course_assignments(
        self,
        course_id: str,
        published_only: bool = True,
    ) -> list[Assignment]:
        """Get all assignments for a course."""
        if not await course_is_operational(self._courses, course_id):
            return []
        return await self._assignments.get_by_course(course_id, published_only)

    async def count_published(self, course_id: str) -> int:
        """Published assignment count for an operational course. Does not load the rows."""
        if not await course_is_operational(self._courses, course_id):
            return 0
        return await self._assignments.count_for_course(course_id, published_only=True)

    async def update_assignment(
        self,
        assignment_id: str,
        payload: AssignmentUpdate,
    ) -> Assignment:
        """Update an assignment."""
        assignment = await self.get_assignment(assignment_id)
        await require_active_course(self._courses, assignment.course_id)
        
        update_data: dict[str, any] = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.description is not None:
            update_data["description"] = payload.description
        if payload.instructions is not None:
            update_data["instructions"] = payload.instructions
        if payload.due_date is not None:
            update_data["due_date"] = payload.due_date
        if payload.max_marks is not None:
            update_data["max_marks"] = payload.max_marks
        if payload.is_published is not None:
            update_data["is_published"] = payload.is_published
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._assignments.update(assignment_id, update_data)
        if not updated:
            raise NotFoundError("Assignment not found")
        return updated

    async def delete_assignment(
        self,
        assignment_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive an assignment. Student submissions stay stored."""
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        assignment = await self.get_assignment(assignment_id)
        await archive_record(
            self._assignments,
            assignment,
            archived_by=archived_by,
            deactivate=False,
            audit=self._audit,
            action="assignment.delete",
            entity_type="assignment",
            not_found="Assignment not found",
        )

    async def submit_assignment(
        self,
        payload: AssignmentSubmissionCreate,
        student_id: str,
        course_id: str,
        enrollment_id: str,
    ) -> AssignmentSubmission:
        """Submit an assignment."""
        await require_active_course(self._courses, course_id)
        await self.get_assignment(payload.assignment_id)
        
        return await self._submissions.create_submission(
            assignment_id=payload.assignment_id,
            student_id=student_id,
            course_id=course_id,
            enrollment_id=enrollment_id,
            submission_text=payload.submission_text,
            file_urls=payload.file_urls,
        )

    async def get_submission(
        self,
        student_id: str,
        assignment_id: str,
    ) -> AssignmentSubmission | None:
        """Get student's submission for an assignment."""
        return await self._submissions.get_by_student_and_assignment(student_id, assignment_id)

    async def get_assignment_submissions(self, assignment_id: str) -> list[AssignmentSubmission]:
        """Get all submissions for an assignment."""
        return await self._submissions.get_by_assignment(assignment_id)

    async def page_assignment_submissions(
        self,
        assignment_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[AssignmentSubmission], int]:
        return await self._submissions.page_by_assignment(assignment_id, skip=skip, limit=limit)

    async def grade_submission(
        self,
        submission_id: str,
        marks_obtained: float,
        feedback: str | None,
        graded_by: str,
    ) -> AssignmentSubmission:
        """Grade an assignment submission."""
        submission = await self._submissions.get_by_id(submission_id)
        if not submission:
            raise NotFoundError("Submission not found")
        
        update_data = {
            "marks_obtained": marks_obtained,
            "feedback": feedback,
            "graded_by": graded_by,
            "graded_at": datetime.now(timezone.utc),
            "status": "graded",
            "updated_at": datetime.now(timezone.utc),
        }
        
        updated = await self._submissions.update(submission_id, update_data)
        if not updated:
            raise NotFoundError("Submission not found")
        await write_audit(
            self._audit,
            action="grade.update",
            entity_type="assignment_submission",
            entity_id=updated.id,
            previous={
                "id": submission.id,
                "status": submission.status,
                "marks_obtained": submission.marks_obtained,
                "feedback": submission.feedback,
                "graded_by": submission.graded_by,
            },
            current={
                "id": updated.id,
                "status": updated.status,
                "marks_obtained": updated.marks_obtained,
                "feedback": updated.feedback,
                "graded_by": updated.graded_by,
            },
        )
        return updated
