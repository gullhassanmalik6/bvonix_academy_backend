from __future__ import annotations

from app.repositories.course_material_repository import CourseMaterialRepository
from app.schemas.course_material import CourseMaterialCreate, CourseMaterialUpdate
from app.models.course_material import CourseMaterial
from app.utils.exceptions import NotFoundError


class CourseMaterialService:
    def __init__(self, material_repo: CourseMaterialRepository) -> None:
        self._materials = material_repo

    async def create_material(self, payload: CourseMaterialCreate, created_by: str) -> CourseMaterial:
        """Create a new course material."""
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

    async def get_course_materials(
        self,
        course_id: str,
        published_only: bool = True,
    ) -> list[CourseMaterial]:
        """Get all materials for a course."""
        return await self._materials.get_by_course(course_id, published_only)

    async def update_material(
        self,
        material_id: str,
        payload: CourseMaterialUpdate,
    ) -> CourseMaterial:
        """Update a course material."""
        material = await self.get_material(material_id)
        
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

    async def delete_material(self, material_id: str) -> None:
        """Delete a course material."""
        material = await self.get_material(material_id)
        deleted = await self._materials.delete(material_id)
        if not deleted:
            raise NotFoundError("Course material not found")
