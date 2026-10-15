from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.models.announcement import Announcement
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class AnnouncementRepository(BaseRepository[Announcement]):
    collection_name = "announcements"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING), ("archived_at", ASCENDING)])
        await self.collection.create_index([("is_published", ASCENDING)])
        await self.collection.create_index([("published_at", ASCENDING)])
        await self.collection.create_index([("priority", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Announcement:
        return Announcement(
            id=oid_str(doc["_id"]),
            course_id=oid_str(doc["course_id"]) if doc.get("course_id") else None,
            title=doc.get("title", ""),
            content=doc.get("content", ""),
            priority=doc.get("priority", "normal"),
            is_published=doc.get("is_published", True),
            published_at=doc.get("published_at"),
            expires_at=doc.get("expires_at"),
            created_by=oid_str(doc["created_by"]),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
        )

    async def get_by_id(self, announcement_id: str) -> Announcement | None:
        doc = await self.find_document_by_id(announcement_id)
        return self._to_model(doc) if doc else None

    async def list_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        course_id: str | None = None,
    ) -> tuple[list[Announcement], int]:
        """Page announcements. Omitting course_id keeps the system-wide list."""
        query: dict[str, Any] = {}
        if course_id:
            try:
                query["course_id"] = ObjectId(course_id)
            except Exception:
                return [], 0
        else:
            query["course_id"] = None
        return await self.find_page(
            query,
            skip=skip,
            limit=limit,
            sort=[("published_at", DESCENDING)],
        )

    async def get_by_course(
        self,
        course_id: str | None,
        published_only: bool = True,
    ) -> list[Announcement]:
        """Get announcements for a course or system-wide."""
        filter_dict: dict[str, Any] = with_active()
        
        if course_id:
            try:
                filter_dict["course_id"] = ObjectId(course_id)
            except Exception:
                return []
        else:
            filter_dict["course_id"] = None  # System-wide
        
        if published_only:
            filter_dict["is_published"] = True
            now = datetime.now(timezone.utc)
            filter_dict["$or"] = [
                {"expires_at": None},
                {"expires_at": {"$gte": now}},
            ]
        
        return await self.collect(filter_dict, sort=[("priority", -1), ("published_at", -1)])

    async def page_published(
        self,
        course_id: str | None,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Announcement], int]:
        """Page the same published, unexpired rows that get_by_course returns in full."""
        query: dict[str, Any] = {}
        if course_id:
            try:
                query["course_id"] = ObjectId(course_id)
            except Exception:
                return [], 0
        else:
            query["course_id"] = None
        query["is_published"] = True
        now = datetime.now(timezone.utc)
        query["$or"] = [{"expires_at": None}, {"expires_at": {"$gte": now}}]
        return await self.find_page(
            query,
            skip=skip,
            limit=limit,
            sort=[("priority", -1), ("published_at", -1)],
        )

    async def create_announcement(
        self,
        *,
        course_id: str | None,
        title: str,
        content: str,
        priority: str,
        is_published: bool,
        published_at: datetime | None,
        expires_at: datetime | None,
        created_by: str,
    ) -> Announcement:
        now = datetime.now(timezone.utc)
        try:
            course_oid = ObjectId(course_id) if course_id else None
            created_by_oid = ObjectId(created_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        payload = {
            "course_id": course_oid,
            "title": title,
            "content": content,
            "priority": priority,
            "is_published": is_published,
            "published_at": published_at or (now if is_published else None),
            "expires_at": expires_at,
            "created_by": created_by_oid,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
