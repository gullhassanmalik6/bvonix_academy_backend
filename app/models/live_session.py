from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class LiveSession:
    """
    Domain model for live class sessions.
    
    Tracks scheduled live sessions (online or physical).
    """

    id: str
    course_id: str  # Reference to Course
    title: str
    description: str | None
    session_type: str  # "online", "physical", "hybrid"
    start_time: datetime
    end_time: datetime
    meeting_link: str | None  # For online sessions (Zoom, Meet, etc.)
    location: str | None  # For physical sessions (classroom, address)
    instructor_id: str  # Reference to Instructor
    max_participants: int | None
    recording_url: str | None  # URL to recorded session
    is_recorded: bool
    status: str  # "scheduled", "ongoing", "completed", "cancelled"
    created_by: str  # Admin/Instructor user_id
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
