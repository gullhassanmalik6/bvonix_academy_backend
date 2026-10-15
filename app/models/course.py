from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Course:
    """
    Domain model for a course document.
    
    Why: Typed domain model ensures type safety and clear field definitions.
    """

    id: str
    title: str
    description: str
    instructor_id: str
    duration_hours: int
    price: float
    is_published: bool
    created_at: datetime
    updated_at: datetime
    image_url: str | None = None
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
