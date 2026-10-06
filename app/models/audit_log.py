from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class AuditLog:
    """Record of a sensitive administrative action."""

    id: str
    actor_id: str | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str | None
    previous_state: dict | None
    new_state: dict | None
    context: dict
    created_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
