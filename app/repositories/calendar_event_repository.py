from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.calendar_event import CalendarEvent
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class CalendarEventRepository(BaseRepository[CalendarEvent]):
    collection_name = "calendar_events"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("event_type", ASCENDING)])
        await self.collection.create_index([("start_time", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING), ("start_time", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> CalendarEvent:
        return CalendarEvent(
            id=oid_str(doc["_id"]),
            course_id=oid_str(doc["course_id"]) if doc.get("course_id") else None,
            event_type=doc.get("event_type", "class"),
            title=doc.get("title", ""),
            description=doc.get("description"),
            start_time=doc.get("start_time") or datetime.now(timezone.utc),
            end_time=doc.get("end_time"),
            location=doc.get("location"),
            meeting_link=doc.get("meeting_link"),
            related_entity_type=doc.get("related_entity_type"),
            related_entity_id=oid_str(doc["related_entity_id"]) if doc.get("related_entity_id") else None,
            is_all_day=doc.get("is_all_day", False),
            created_by=oid_str(doc["created_by"]),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def create_event(
        self,
        *,
        course_id: str | None,
        event_type: str,
        title: str,
        description: str | None,
        start_time: datetime,
        end_time: datetime | None,
        location: str | None,
        meeting_link: str | None,
        related_entity_type: str | None,
        related_entity_id: str | None,
        is_all_day: bool,
        created_by: str,
    ) -> CalendarEvent:
        now = datetime.now(timezone.utc)
        try:
            course_oid = ObjectId(course_id) if course_id else None
            related_oid = ObjectId(related_entity_id) if related_entity_id else None
            created_by_oid = ObjectId(created_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        payload = {
            "course_id": course_oid,
            "event_type": event_type,
            "title": title,
            "description": description,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
            "meeting_link": meeting_link,
            "related_entity_type": related_entity_type,
            "related_entity_id": related_oid,
            "is_all_day": is_all_day,
            "created_by": created_by_oid,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    async def get_by_course(
        self,
        course_id: str | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CalendarEvent]:
        """Get events for a course or all courses."""
        filter_dict: dict[str, Any] = {}
        if course_id:
            try:
                course_oid = ObjectId(course_id)
                filter_dict["course_id"] = course_oid
            except Exception:
                return []
        else:
            # Get system-wide events (course_id is None)
            filter_dict["course_id"] = None
        
        if start_date:
            filter_dict["start_time"] = {"$gte": start_date}
        if end_date:
            if "start_time" in filter_dict:
                filter_dict["start_time"]["$lte"] = end_date
            else:
                filter_dict["start_time"] = {"$lte": end_date}
        
        cursor = self.collection.find(filter_dict).sort("start_time", ASCENDING)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_student_events(
        self,
        course_ids: list[str],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CalendarEvent]:
        """Get events for a student's enrolled courses."""
        try:
            course_oids = [ObjectId(cid) for cid in course_ids]
        except Exception:
            return []
        
        filter_dict: dict[str, Any] = {
            "$or": [
                {"course_id": {"$in": course_oids}},
                {"course_id": None},  # System-wide events
            ]
        }
        
        if start_date:
            filter_dict["start_time"] = {"$gte": start_date}
        if end_date:
            if "start_time" in filter_dict:
                filter_dict["start_time"]["$lte"] = end_date
            else:
                filter_dict["start_time"] = {"$lte": end_date}
        
        cursor = self.collection.find(filter_dict).sort("start_time", ASCENDING)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]
