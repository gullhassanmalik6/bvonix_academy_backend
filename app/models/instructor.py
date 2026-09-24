from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Instructor:
    """
    Domain model for an instructor document.
    
    Why: Typed domain model ensures type safety and clear field definitions.
    """

    id: str
    user_id: str  # Reference to User
    bio: str | None
    specialization: str | None
    years_of_experience: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
