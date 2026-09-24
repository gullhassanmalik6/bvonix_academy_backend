from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class CalendarEvent:
    """
    Domain model for calendar events.
    
    Tracks scheduled events like classes, assignments, exams, etc.
    """

    id: str
    course_id: str | None  # None for system-wide events
    event_type: str  # "class", "assignment_due", "exam", "live_session", "announcement", "holiday"
    title: str
    description: str | None
    start_time: datetime
    end_time: datetime | None
    location: str | None  # For physical classes
    meeting_link: str | None  # For online sessions
    related_entity_type: str | None  # "assignment", "live_session", etc.
    related_entity_id: str | None  # ID of related entity
    is_all_day: bool
    created_by: str  # User ID who created the event
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
