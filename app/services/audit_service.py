"""Reusable audit logger for sensitive administrative actions."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from app.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository
from app.services.audit_context import current_actor, current_request_context

logger = logging.getLogger(__name__)

_SECRET_KEYS = {
    "password",
    "hashed_password",
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "admin_secret",
    "secret",
    "x-admin-secret",
}


def _is_secret(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SECRET_KEYS or "password" in normalized or normalized.endswith("_token")


def snapshot(value: Any) -> Any:
    """Convert a domain object to a plain value with secrets removed."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _is_secret(str(key)) else snapshot(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [snapshot(item) for item in value]
    if is_dataclass(value):
        return snapshot(asdict(value))
    if hasattr(value, "model_dump"):
        return snapshot(value.model_dump())
    return str(value)


class AuditService:
    def __init__(self, audit_repo: AuditLogRepository) -> None:
        self._audits = audit_repo

    async def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        previous: Any = None,
        current: Any = None,
        actor_id: str | None = None,
        actor_role: str | None = None,
        context: dict | None = None,
    ) -> AuditLog | None:
        """Persist one audit record. A logging failure does not undo the action."""
        actor = current_actor() or {}
        request_context = current_request_context()
        if context:
            request_context.update(snapshot(context))
        document = {
            "actor_id": actor_id if actor_id is not None else actor.get("id"),
            "actor_role": actor_role if actor_role is not None else actor.get("role"),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "previous_state": snapshot(previous),
            "new_state": snapshot(current),
            "context": request_context,
            "created_at": AuditLog.now_utc(),
        }
        try:
            return await self._audits.create(document)
        except Exception:
            logger.exception("Failed to write audit log for %s %s", action, entity_id)
            return None


async def write_audit(audit: AuditService | None, **kwargs: Any) -> None:
    if audit is None:
        return
    await audit.record(**kwargs)
