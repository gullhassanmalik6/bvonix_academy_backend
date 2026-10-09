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
        await self.collection.create_index([("course_id", ASCENDING), ("archived_at", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING), ("order", ASCENDING)])
        await self.collection.create_index([
            ("course_id", ASCENDING),
            ("is_published", ASCENDING),
            ("archived_at", ASCENDING),
            ("order", ASCENDING),
            ("created_at", ASCENDING),
        ])
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
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
        )

    async def get_by_id(self, material_id: str) -> CourseMaterial | None:
        doc = await self.find_document_by_id(material_id)
        return self._to_model(doc) if doc else None

    async def list_page(
        self,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        published_only: bool = False,
    ) -> tuple[list[CourseMaterial], int]:
        try:
            query: dict[str, Any] = {"course_id": ObjectId(course_id)}
        except Exception:
            return [], 0
        if published_only:
            query["is_published"] = True
        return await self.find_page(query, skip=skip, limit=limit, sort=[("order", ASCENDING), ("created_at", ASCENDING)])

    async def get_by_course(self, course_id: str, published_only: bool = True) -> list[CourseMaterial]:
        """Get all materials for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        query: dict[str, Any] = {"course_id": course_oid}
        if published_only:
            query["is_published"] = True
        return await self.collect(query, sort=[("order", ASCENDING), ("created_at", ASCENDING)])

    async def count_for_course(self, course_id: str, *, published_only: bool = True) -> int:
        """Count materials with the same filter as list_page. Archived rows stay out."""
        try:
            query: dict[str, Any] = {"course_id": ObjectId(course_id)}
        except Exception:
            return 0
        if published_only:
            query["is_published"] = True
        return await self.count(query)

    async def find_published_for_courses(self, course_ids: list[str]) -> dict[str, list[CourseMaterial]]:
        """Load published materials for many courses without one query per course."""
        from app.repositories.listing import MAX_PAGE_SIZE

        oids = []
        for raw in course_ids:
            try:
                oids.append(ObjectId(raw))
            except Exception:
                continue
        grouped: dict[str, list[CourseMaterial]] = {}
        step = MAX_PAGE_SIZE
        for start in range(0, len(oids), step):
            chunk = oids[start:start + step]
            skip = 0
            while True:
                page, total = await self.find_page(
                    {"course_id": {"$in": chunk}, "is_published": True},
                    skip=skip,
                    limit=MAX_PAGE_SIZE,
                    sort=[("order", ASCENDING), ("created_at", ASCENDING)],
                )
                for item in page:
                    grouped.setdefault(item.course_id, []).append(item)
                skip += len(page)
                if not page or skip >= total:
                    break
        return grouped

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
