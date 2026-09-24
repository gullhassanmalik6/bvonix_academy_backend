from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.calendar_event_repository import CalendarEventRepository
from app.schemas.calendar_event import CalendarEventCreate, CalendarEventUpdate
from app.models.calendar_event import CalendarEvent
from app.utils.exceptions import NotFoundError


class CalendarEventService:
    def __init__(self, event_repo: CalendarEventRepository) -> None:
        self._events = event_repo

    async def create_event(
        self,
        payload: CalendarEventCreate,
        created_by: str,
    ) -> CalendarEvent:
        """Create a new calendar event."""
        return await self._events.create_event(
            course_id=payload.course_id,
            event_type=payload.event_type,
            title=payload.title,
            description=payload.description,
            start_time=payload.start_time,
            end_time=payload.end_time,
            location=payload.location,
            meeting_link=payload.meeting_link,
            related_entity_type=payload.related_entity_type,
            related_entity_id=payload.related_entity_id,
            is_all_day=payload.is_all_day,
            created_by=created_by,
        )

    async def get_event(self, event_id: str) -> CalendarEvent:
        """Get an event by ID."""
        event = await self._events.get_by_id(event_id)
        if not event:
            raise NotFoundError("Event not found")
        return event

    async def get_course_events(
        self,
        course_id: str | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CalendarEvent]:
        """Get events for a course."""
        return await self._events.get_by_course(course_id, start_date, end_date)

    async def get_student_events(
        self,
        course_ids: list[str],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CalendarEvent]:
        """Get events for a student's enrolled courses."""
        return await self._events.get_student_events(course_ids, start_date, end_date)

    async def update_event(
        self,
        event_id: str,
        payload: CalendarEventUpdate,
    ) -> CalendarEvent:
        """Update an event."""
        event = await self.get_event(event_id)
        
        update_data: dict[str, Any] = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.description is not None:
            update_data["description"] = payload.description
        if payload.start_time is not None:
            update_data["start_time"] = payload.start_time
        if payload.end_time is not None:
            update_data["end_time"] = payload.end_time
        if payload.location is not None:
            update_data["location"] = payload.location
        if payload.meeting_link is not None:
            update_data["meeting_link"] = payload.meeting_link
        if payload.is_all_day is not None:
            update_data["is_all_day"] = payload.is_all_day
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._events.update(event_id, update_data)
        if not updated:
            raise NotFoundError("Event not found")
        return updated

    async def delete_event(self, event_id: str) -> None:
        """Delete an event."""
        event = await self.get_event(event_id)
        deleted = await self._events.delete(event_id)
        if not deleted:
            raise NotFoundError("Event not found")
