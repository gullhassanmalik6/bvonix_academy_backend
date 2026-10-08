"""Shared archival filter.

Documents created before archival have no `archived_at` field. MongoDB treats
a query for `archived_at: null` as matching both null and a missing field, so
existing rows stay active without a data migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def with_active(query: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a query that excludes archived documents."""
    merged = dict(query or {})
    merged.setdefault("archived_at", None)
    return merged


def record_is_active(record: Any) -> bool:
    """True when a document or model has not been archived."""
    if isinstance(record, dict):
        return record.get("archived_at") is None
    return getattr(record, "archived_at", None) is None


def archive_values(*, archived_by: str | None, deactivate: bool = False) -> dict[str, Any]:
    """Fields written when a sensitive record is archived."""
    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "archived_at": now,
        "archived_by": archived_by,
        "updated_at": now,
    }
    if deactivate:
        values["is_active"] = False
    return values
