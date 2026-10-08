from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Student:
    """
    Domain model for a student document.
    
    Why: Typed domain model ensures type safety and clear field definitions.
    """

    id: str
    user_id: str  # Reference to User
    enrollment_date: datetime
    enrolled_courses: list[str]  # List of course IDs
    is_active: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
