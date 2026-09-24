from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Announcement:
    """
    Domain model for announcements.
    
    Course-specific or system-wide announcements.
    """

    id: str
    course_id: str | None  # None for system-wide announcements
    title: str
    content: str
    priority: str  # "low", "normal", "high", "urgent"
    is_published: bool
    published_at: datetime | None
    expires_at: datetime | None
    created_by: str  # Admin/Instructor user_id
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
