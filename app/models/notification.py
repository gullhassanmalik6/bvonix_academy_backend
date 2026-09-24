from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Notification:
    """
    Domain model for user notifications.
    
    Tracks in-app notifications for students, instructors, and admins.
    """

    id: str
    user_id: str  # Reference to User
    title: str
    message: str
    notification_type: str  # "scholarship_at_risk", "scholarship_terminated", "assignment_due", "announcement", "grade", "certificate", etc.
    related_entity_type: str | None  # "scholarship", "assignment", "announcement", etc.
    related_entity_id: str | None  # ID of related entity
    is_read: bool
    read_at: datetime | None
    priority: str  # "low", "normal", "high", "urgent"
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
