from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.assignment_repository import AssignmentRepository, AssignmentSubmissionRepository
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentSubmissionCreate,
    AssignmentSubmissionUpdate,
    AssignmentUpdate,
)
from app.models.assignment import Assignment, AssignmentSubmission
from app.services.audit_service import AuditService, write_audit
from app.utils.exceptions import NotFoundError


class AssignmentService:
    def __init__(
        self,
        assignment_repo: AssignmentRepository,
        submission_repo: AssignmentSubmissionRepository,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._assignments = assignment_repo
        self._submissions = submission_repo
        self._audit = audit

    async def create_assignment(self, payload: AssignmentCreate, created_by: str) -> Assignment:
        """Create a new assignment."""
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

    async def get_course_assignments(
        self,
        course_id: str,
        published_only: bool = True,
    ) -> list[Assignment]:
        """Get all assignments for a course."""
        return await self._assignments.get_by_course(course_id, published_only)

    async def update_assignment(
        self,
        assignment_id: str,
        payload: AssignmentUpdate,
    ) -> Assignment:
        """Update an assignment."""
        assignment = await self.get_assignment(assignment_id)
        
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

    async def delete_assignment(self, assignment_id: str) -> None:
        """Delete an assignment."""
        assignment = await self.get_assignment(assignment_id)
        deleted = await self._assignments.delete(assignment_id)
        if not deleted:
            raise NotFoundError("Assignment not found")

    async def submit_assignment(
        self,
        payload: AssignmentSubmissionCreate,
        student_id: str,
        course_id: str,
        enrollment_id: str,
    ) -> AssignmentSubmission:
        """Submit an assignment."""
        # Check if assignment exists
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
