from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.course_material import CourseMaterial
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class CourseMaterialRepository(BaseRepository[CourseMaterial]):
    collection_name = "course_materials"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING), ("order", ASCENDING)])
        await self.collection.create_index([("is_published", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> CourseMaterial:
        return CourseMaterial(
            id=oid_str(doc["_id"]),
            course_id=oid_str(doc["course_id"]),
            title=doc.get("title", ""),
            description=doc.get("description"),
            material_type=doc.get("material_type", "document"),
            content_url=doc.get("content_url"),
            file_path=doc.get("file_path"),
            file_size=doc.get("file_size"),
            duration_minutes=doc.get("duration_minutes"),
            order=doc.get("order", 0),
            is_published=doc.get("is_published", True),
            is_required=doc.get("is_required", False),
            created_by=oid_str(doc["created_by"]),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_course(self, course_id: str, published_only: bool = True) -> list[CourseMaterial]:
        """Get all materials for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        filter_dict: dict[str, Any] = {"course_id": course_oid}
        if published_only:
            filter_dict["is_published"] = True
        
        cursor = self.collection.find(filter_dict).sort("order", ASCENDING)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def create_material(
        self,
        *,
        course_id: str,
        title: str,
        description: str | None,
        material_type: str,
        content_url: str | None,
        file_path: str | None,
        file_size: int | None,
        duration_minutes: int | None,
        order: int,
        is_published: bool,
        is_required: bool,
        created_by: str,
    ) -> CourseMaterial:
        now = datetime.now(timezone.utc)
        try:
            course_oid = ObjectId(course_id)
            created_by_oid = ObjectId(created_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        payload = {
            "course_id": course_oid,
            "title": title,
            "description": description,
            "material_type": material_type,
            "content_url": content_url,
            "file_path": file_path,
            "file_size": file_size,
            "duration_minutes": duration_minutes,
            "order": order,
            "is_published": is_published,
            "is_required": is_required,
            "created_by": created_by_oid,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
