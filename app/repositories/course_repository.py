from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.course import Course
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class CourseRepository(BaseRepository[Course]):
    collection_name = "courses"

    async def ensure_indexes(self) -> None:
        # Index on instructor_id for faster lookups
        await self.collection.create_index([("instructor_id", ASCENDING)])
        await self.collection.create_index([
            ("instructor_id", ASCENDING),
            ("archived_at", ASCENDING),
            ("created_at", ASCENDING),
        ])
        # Index on is_published for filtering
        await self.collection.create_index([("is_published", ASCENDING)])
        await self.collection.create_index([("is_published", ASCENDING), ("archived_at", ASCENDING)])
        await self.collection.create_index([("title", ASCENDING)])
        await self.collection.create_index([("created_at", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Course:
        return Course(
            id=oid_str(doc["_id"]),
            title=doc["title"],
            description=doc["description"],
            instructor_id=oid_str(doc["instructor_id"]),
            duration_hours=doc["duration_hours"],
            price=doc["price"],
            is_published=doc.get("is_published", False),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
        )

    async def get_by_id(self, course_id: str) -> Course | None:
        doc = await self.find_document_by_id(course_id)
        return self._to_model(doc) if doc else None

    async def get_by_instructor(self, instructor_id: str) -> list[Course]:
        """Get active courses by an instructor."""
        try:
            oid = ObjectId(instructor_id)
        except Exception:
            return []
        return await self.collect(
            {"instructor_id": oid},
            sort=[("created_at", ASCENDING)],
        )

    async def page_by_instructor(
        self,
        instructor_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        published_only: bool = False,
    ) -> tuple[list[Course], int]:
        try:
            oid = ObjectId(instructor_id)
        except Exception:
            return [], 0
        query: dict[str, Any] = {"instructor_id": oid}
        if published_only:
            query["is_published"] = True
        return await self.find_page(
            query,
            skip=skip,
            limit=limit,
            sort=[("created_at", ASCENDING)],
        )

    async def get_published(self, skip: int = 0, limit: int = 100) -> list[Course]:
        """Get one page of published courses. The page size cannot exceed the list maximum."""
        page, _total = await self.find_page(
            {"is_published": True},
            skip=skip,
            limit=limit,
            sort=[("created_at", ASCENDING)],
        )
        return page

    async def create_course(
        self,
        *,
        title: str,
        description: str,
        instructor_id: str,
        duration_hours: int,
        price: float,
        is_published: bool = False,
    ) -> Course:
        now = datetime.now(timezone.utc)
        try:
            instructor_oid = ObjectId(instructor_id)
        except Exception:
            raise ValueError("Invalid instructor_id")
        
        payload = {
            "title": title,
            "description": description,
            "instructor_id": instructor_oid,
            "duration_hours": duration_hours,
            "price": price,
            "is_published": is_published,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
