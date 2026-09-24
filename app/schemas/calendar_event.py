from __future__ import annotations

from datetime import datetime

from app.schemas.common import APIModel


class CalendarEventCreate(APIModel):
    """Schema for creating a calendar event."""
    course_id: str | None = None
    event_type: str  # "class", "assignment_due", "exam", "live_session", "announcement", "holiday"
    title: str
    description: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    location: str | None = None
    meeting_link: str | None = None
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    is_all_day: bool = False


class CalendarEventUpdate(APIModel):
    """Schema for updating a calendar event."""
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    meeting_link: str | None = None
    is_all_day: bool | None = None


class CalendarEventPublic(APIModel):
    """Public schema for calendar event."""
    id: str
    course_id: str | None
    event_type: str
    title: str
    description: str | None
    start_time: datetime
    end_time: datetime | None
    location: str | None
    meeting_link: str | None
    related_entity_type: str | None
    related_entity_id: str | None
    is_all_day: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
