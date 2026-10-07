from __future__ import annotations

from datetime import datetime
from typing import Any

from app.schemas.common import APIModel


class AuditLogPublic(APIModel):
    id: str
    actor_id: str | None = None
    actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    context: dict[str, Any] = {}
    created_at: datetime
