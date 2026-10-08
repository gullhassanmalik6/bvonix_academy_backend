from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.live_session import LiveSession
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class LiveSessionRepository(BaseRepository[LiveSession]):
    collection_name = "live_sessions"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("start_time", ASCENDING)])
        await self.collection.create_index([("status", ASCENDING)])
        await self.collection.create_index([("instructor_id", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> LiveSession:
        return LiveSession(
            id=oid_str(doc["_id"]),
            course_id=oid_str(doc["course_id"]),
            title=doc.get("title", ""),
            description=doc.get("description"),
            session_type=doc.get("session_type", "online"),
            start_time=doc.get("start_time") or datetime.now(timezone.utc),
            end_time=doc.get("end_time") or datetime.now(timezone.utc),
            meeting_link=doc.get("meeting_link"),
            location=doc.get("location"),
            instructor_id=oid_str(doc["instructor_id"]),
            max_participants=doc.get("max_participants"),
            recording_url=doc.get("recording_url"),
            is_recorded=doc.get("is_recorded", False),
            status=doc.get("status", "scheduled"),
            created_by=oid_str(doc["created_by"]),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def list_page(
        self,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[LiveSession], int]:
        try:
            query: dict[str, Any] = {"course_id": ObjectId(course_id)}
        except Exception:
            return [], 0
        return await self.find_page(query, skip=skip, limit=limit, sort=[("start_time", ASCENDING)])

    async def get_by_course(
        self,
        course_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[LiveSession]:
        """Get all sessions for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        filter_dict: dict[str, Any] = {"course_id": course_oid}
        if start_date or end_date:
            date_filter: dict[str, Any] = {}
            if start_date:
                date_filter["$gte"] = start_date
            if end_date:
                date_filter["$lte"] = end_date
            if date_filter:
                filter_dict["start_time"] = date_filter
        
        cursor = self.collection.find(filter_dict).sort("start_time", ASCENDING)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_upcoming(self, course_id: str | None = None) -> list[LiveSession]:
        """Get upcoming sessions."""
        now = datetime.now(timezone.utc)
        filter_dict: dict[str, Any] = {
            "start_time": {"$gte": now},
            "status": {"$in": ["scheduled", "ongoing"]},
        }
        if course_id:
            try:
                filter_dict["course_id"] = ObjectId(course_id)
            except Exception:
                return []
        
        cursor = self.collection.find(filter_dict).sort("start_time", ASCENDING)
        docs = await cursor.to_list(length=100)
        return [self._to_model(doc) for doc in docs]

    async def create_session(
        self,
        *,
        course_id: str,
        title: str,
        description: str | None,
        session_type: str,
        start_time: datetime,
        end_time: datetime,
        meeting_link: str | None,
        location: str | None,
        instructor_id: str,
        max_participants: int | None,
        created_by: str,
    ) -> LiveSession:
        now = datetime.now(timezone.utc)
        try:
            course_oid = ObjectId(course_id)
            instructor_oid = ObjectId(instructor_id)
            created_by_oid = ObjectId(created_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        payload = {
            "course_id": course_oid,
            "title": title,
            "description": description,
            "session_type": session_type,
            "start_time": start_time,
            "end_time": end_time,
            "meeting_link": meeting_link,
            "location": location,
            "instructor_id": instructor_oid,
            "max_participants": max_participants,
            "recording_url": None,
            "is_recorded": False,
            "status": "scheduled",
            "created_by": created_by_oid,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
