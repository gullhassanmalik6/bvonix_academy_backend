from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class User:
    """
    Domain model for a user document.

    Why a lightweight model: MongoDB documents are dicts, but having a typed
    domain model makes services clearer and reduces field-name mistakes.
    """

    id: str
    email: str
    full_name: str | None
    hashed_password: str
    is_active: bool
    role: str  # user, academic_manager, admin, or super_admin
    created_at: datetime
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)

