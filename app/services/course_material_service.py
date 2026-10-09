from __future__ import annotations

from app.core.permissions import is_management
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.schemas.course_material import CourseMaterialCreate, CourseMaterialUpdate
from app.models.course_material import CourseMaterial
from app.services.archive_actions import archive_record
from app.services.audit_service import AuditService
from app.services.course_service import course_is_operational, require_active_course
from app.utils.exceptions import ForbiddenError, NotFoundError


class CourseMaterialService:
    def __init__(
        self,
        material_repo: CourseMaterialRepository,
        *,
        courses: CourseRepository | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._materials = material_repo
        self._courses = courses
        self._audit = audit

    async def create_material(self, payload: CourseMaterialCreate, created_by: str) -> CourseMaterial:
        """Create a new course material."""
        await require_active_course(self._courses, payload.course_id)
        return await self._materials.create_material(
            course_id=payload.course_id,
            title=payload.title,
            description=payload.description,
            material_type=payload.material_type,
            content_url=payload.content_url,
            file_path=payload.file_path,
            file_size=payload.file_size,
            duration_minutes=payload.duration_minutes,
            order=payload.order,
            is_published=payload.is_published,
            is_required=payload.is_required,
            created_by=created_by,
        )

    async def get_material(self, material_id: str) -> CourseMaterial:
        """Get material by ID."""
        material = await self._materials.get_by_id(material_id)
        if not material:
            raise NotFoundError("Course material not found")
        return material

    async def list_course_materials(
        self,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        published_only: bool = False,
    ) -> tuple[list[CourseMaterial], int]:
        """Page materials for one course without loading the whole set into Python."""
        if not await course_is_operational(self._courses, course_id):
            return [], 0
        return await self._materials.list_page(
            course_id, skip=skip, limit=limit, published_only=published_only
        )

    async def get_course_materials(
        self,
        course_id: str,
        published_only: bool = True,
    ) -> list[CourseMaterial]:
        """Get all materials for a course."""
        if not await course_is_operational(self._courses, course_id):
            return []
        return await self._materials.get_by_course(course_id, published_only)

    async def count_published(self, course_id: str) -> int:
        """Published material count for an operational course. Does not load the rows."""
        if not await course_is_operational(self._courses, course_id):
            return 0
        return await self._materials.count_for_course(course_id, published_only=True)

    async def published_for_courses(self, course_ids: list[str]) -> dict[str, list[CourseMaterial]]:
        """Published materials for the supplied active courses, loaded in batches."""
        return await self._materials.find_published_for_courses(course_ids)

    async def update_material(
        self,
        material_id: str,
        payload: CourseMaterialUpdate,
    ) -> CourseMaterial:
        """Update a course material."""
        material = await self.get_material(material_id)
        await require_active_course(self._courses, material.course_id)
        
        update_data: dict[str, any] = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.description is not None:
            update_data["description"] = payload.description
        if payload.content_url is not None:
            update_data["content_url"] = payload.content_url
        if payload.order is not None:
            update_data["order"] = payload.order
        if payload.is_published is not None:
            update_data["is_published"] = payload.is_published
        if payload.is_required is not None:
            update_data["is_required"] = payload.is_required
        
        from datetime import datetime, timezone
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._materials.update(material_id, update_data)
        if not updated:
            raise NotFoundError("Course material not found")
        return updated

    async def delete_material(
        self,
        material_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive a course material. Submissions and history are left in place."""
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        material = await self.get_material(material_id)
        await archive_record(
            self._materials,
            material,
            archived_by=archived_by,
            deactivate=False,
            audit=self._audit,
            action="material.delete",
            entity_type="material",
            not_found="Course material not found",
        )
