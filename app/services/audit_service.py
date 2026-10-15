"""Reusable audit logger for sensitive administrative actions."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository
from app.services.audit_context import current_actor, current_request_context
from app.utils.exceptions import AppError

logger = logging.getLogger(__name__)


class AuditPersistenceError(AppError):
    """The business change was saved and the history record was not."""

    def __init__(self) -> None:
        super().__init__(
            "The decision was saved, but the review history was not recorded.",
            status_code=500,
        )

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
    "payment_receipt_url",
    "receipt_url",
    "invoice_url",
    "transaction_id",
    "phone_number",
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "father_guardian_name",
    "date_of_birth",
    "profile_image_url",
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
            if str(key) != "audit_pending"
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
        operation_id = request_context.get("operation_id")
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
        if operation_id:
            document["operation_id"] = operation_id
        try:
            return await self._audits.create(document)
        except DuplicateKeyError:
            if operation_id:
                return await self._audits.find_by_operation_id(operation_id)
            logger.exception("Failed to write audit log for %s %s", action, entity_id)
            return None
        except Exception:
            logger.exception("Failed to write audit log for %s %s", action, entity_id)
            return None

    async def find_by_operation(self, operation_id: str) -> AuditLog | None:
        finder = getattr(self._audits, "find_by_operation_id", None)
        if finder is None:
            return None
        return await finder(operation_id)


async def write_audit(audit: AuditService | None, **kwargs: Any) -> None:
    if audit is None:
        return
    await audit.record(**kwargs)


def new_operation_id() -> str:
    return str(uuid.uuid4())


def audit_intent(
    *,
    operation_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    actor_id: str | None,
    actor_role: str | None,
    previous: Any,
) -> dict:
    """Decision marker stored in the same document write as the business change."""
    return {
        "operation_id": operation_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "previous_state": snapshot(previous),
    }


async def complete_required_audit(
    audit: AuditService,
    *,
    pending: dict,
    current: Any,
    clear,
) -> AuditLog:
    """Insert the history row for a saved decision, then clear the pending marker.

    A repeated call uses operation_id so it does not insert a second history row.
    Clearing the marker is required before the caller reports success.
    """
    operation_id = pending.get("operation_id")
    if not operation_id:
        raise AuditPersistenceError()
    finder = getattr(audit, "find_by_operation", None)
    existing = await finder(operation_id) if finder is not None else None
    recorded = existing
    if recorded is None:
        recorded = await audit.record(
            action=pending.get("action") or "audit.unknown",
            entity_type=pending.get("entity_type") or "record",
            entity_id=pending.get("entity_id"),
            previous=pending.get("previous_state"),
            current=snapshot(current),
            actor_id=pending.get("actor_id"),
            actor_role=pending.get("actor_role"),
            context={"operation_id": operation_id},
        )
        if recorded is None and finder is not None:
            recorded = await finder(operation_id)
    if recorded is None:
        raise AuditPersistenceError()
    try:
        cleared = await clear()
    except Exception:
        logger.exception("Failed to clear pending audit %s", operation_id)
        raise AuditPersistenceError() from None
    if not cleared:
        raise AuditPersistenceError()
    return recorded


async def recover_pending_decision(audit: AuditService, record: Any, clear) -> bool:
    """Finish a decision whose business write was saved and whose history row was not."""
    pending = getattr(record, "audit_pending", None)
    if not isinstance(pending, dict) or not pending.get("operation_id"):
        return False
    await complete_required_audit(audit, pending=pending, current=record, clear=clear)
    if hasattr(record, "audit_pending"):
        record.audit_pending = None
    return True


async def commit_required_decision(
    audit: AuditService,
    save,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    actor_id: str | None,
    actor_role: str | None,
    previous: Any,
    updates: dict,
) -> Any:
    """Save the business change and its history marker together, then record the audit row.

    The marker is one field on the same document. If the audit insert fails, a
    later call to recover_pending_decision writes that one history row and does
    not apply the business change again.
    """
    stored = dict(updates)
    stored["audit_pending"] = audit_intent(
        operation_id=new_operation_id(),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        actor_role=actor_role,
        previous=previous,
    )

    async def persist(data: dict) -> Any:
        return await save(data)

    saved = await persist(stored)
    if saved is None:
        return None

    async def clear() -> Any:
        return await persist({"audit_pending": None})

    marker = getattr(saved, "audit_pending", None) or stored["audit_pending"]
    await complete_required_audit(audit, pending=marker, current=saved, clear=clear)
    if hasattr(saved, "audit_pending"):
        saved.audit_pending = None
    return saved


def require_audit_record(recorded: AuditLog | None) -> AuditLog:
    """Reject a missing history record instead of treating the decision as fully recorded."""
    if recorded is None:
        raise AuditPersistenceError()
    return recorded
