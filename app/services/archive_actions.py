"""Archive and privileged purge for sensitive records."""

from __future__ import annotations

from typing import Any

from app.core.permissions import assert_can_purge
from app.repositories.archival import record_is_active
from app.services.audit_service import AuditService, write_audit
from app.utils.exceptions import NotFoundError


async def archive_record(
    repo: Any,
    record: Any,
    *,
    archived_by: str | None,
    deactivate: bool,
    audit: AuditService | None,
    action: str,
    entity_type: str,
    not_found: str,
) -> Any:
    """Keep the document, stamp who archived it, and write an audit record."""
    if not record_is_active(record):
        raise NotFoundError(not_found)
    archived = await repo.archive(record.id, archived_by=archived_by, deactivate=deactivate)
    if archived is None:
        raise NotFoundError(not_found)
    await write_audit(
        audit,
        action=action,
        entity_type=entity_type,
        entity_id=record.id,
        previous=record,
        current=archived,
    )
    return archived


async def purge_record(
    repo: Any,
    record: Any,
    *,
    actor_role: str,
    actor_id: str,
    audit: AuditService | None,
    entity_type: str,
    not_found: str,
) -> None:
    """Permanently remove a record. Caller must already be a super admin."""
    assert_can_purge(actor_role)
    removed = await repo.delete(record.id)
    if not removed:
        raise NotFoundError(not_found)
    await write_audit(
        audit,
        action=f"{entity_type}.purge",
        entity_type=entity_type,
        entity_id=record.id,
        previous=record,
        actor_id=actor_id,
        actor_role=actor_role,
    )
