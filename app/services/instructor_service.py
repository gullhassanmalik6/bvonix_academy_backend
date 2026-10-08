"""
Instructor service - business logic for instructor management.

Why: Service layer encapsulates business logic and orchestrates
repository operations, keeping routes clean and testable.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.core.permissions import is_admin
from app.models.instructor import Instructor
from app.repositories.instructor_repository import InstructorRepository
from app.schemas.instructor import InstructorCreate, InstructorUpdate
from app.services.archive_actions import archive_record, purge_record
from app.services.audit_service import AuditService
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError


class InstructorService:
    def __init__(
        self,
        instructor_repo: InstructorRepository,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._instructors = instructor_repo
        self._audit = audit

    async def get_instructor(self, instructor_id: str) -> Instructor:
        """Get an instructor by ID."""
        instructor = await self._instructors.get_by_id(instructor_id)
        if instructor is None:
            raise NotFoundError("Instructor not found")
        return instructor

    async def get_instructor_by_user_id(self, user_id: str) -> Instructor:
        """Get an instructor by user_id."""
        instructor = await self._instructors.get_by_user_id(user_id)
        if instructor is None:
            raise NotFoundError("Instructor not found")
        return instructor

    async def list_instructors(self, skip: int = 0, limit: int = 100) -> tuple[list[Instructor], int]:
        """List all instructors with pagination."""
        instructors = await self._instructors.list(skip=skip, limit=limit)
        total = await self._instructors.count()
        return instructors, total

    async def create_instructor(self, payload: InstructorCreate) -> Instructor:
        """Create a new instructor."""
        try:
            return await self._instructors.create_instructor(
                user_id=payload.user_id,
                bio=payload.bio,
                specialization=payload.specialization,
                years_of_experience=payload.years_of_experience,
            )
        except ValueError as e:
            raise NotFoundError(str(e)) from e
        except DuplicateKeyError as e:
            raise ConflictError("Instructor already exists for this user") from e

    async def update_instructor(self, instructor_id: str, payload: InstructorUpdate) -> Instructor:
        """Update an instructor."""
        instructor = await self.get_instructor(instructor_id)
        
        update_data: dict[str, any] = {}
        if payload.bio is not None:
            update_data["bio"] = payload.bio
        if payload.specialization is not None:
            update_data["specialization"] = payload.specialization
        if payload.years_of_experience is not None:
            update_data["years_of_experience"] = payload.years_of_experience
        if payload.is_active is not None:
            update_data["is_active"] = payload.is_active
        
        if not update_data:
            return instructor
        
        from datetime import datetime, timezone
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated_instructor = await self._instructors.update(instructor_id, update_data)
        if updated_instructor is None:
            raise NotFoundError("Instructor not found")
        return updated_instructor

    async def delete_instructor(
        self,
        instructor_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive an instructor profile. The row stays for audit."""
        if not is_admin(actor_role):
            raise ForbiddenError("Admin access required")
        instructor = await self.get_instructor(instructor_id)
        await archive_record(
            self._instructors,
            instructor,
            archived_by=archived_by,
            deactivate=True,
            audit=self._audit,
            action="instructor.delete",
            entity_type="instructor",
            not_found="Instructor not found",
        )

    async def purge_instructor(self, instructor_id: str, *, actor_role: str, actor_id: str) -> None:
        """Permanently remove an instructor profile. Super admin only."""
        instructor = await self.get_instructor(instructor_id)
        await purge_record(
            self._instructors,
            instructor,
            actor_role=actor_role,
            actor_id=actor_id,
            audit=self._audit,
            entity_type="instructor",
            not_found="Instructor not found",
        )
