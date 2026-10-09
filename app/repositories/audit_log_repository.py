from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from app.db.index_status import ensure_required_index
from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository
from app.repositories.listing import clamp_limit, clamp_skip, stable_sort, text_clause
from app.utils.helpers import oid_str


class AuditLogRepository(BaseRepository[AuditLog]):
    collection_name = "audit_logs"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("created_at", DESCENDING)])
        await self.collection.create_index([("actor_id", ASCENDING), ("created_at", DESCENDING)])
        await self.collection.create_index(
            [("entity_type", ASCENDING), ("entity_id", ASCENDING), ("created_at", DESCENDING)]
        )
        await self.collection.create_index([("action", ASCENDING), ("created_at", DESCENDING)])
        await ensure_required_index(self.collection, [("operation_id", ASCENDING)], unique=True, sparse=True)

    def _to_model(self, doc: dict[str, Any]) -> AuditLog:
        return AuditLog(
            id=oid_str(doc["_id"]),
            actor_id=doc.get("actor_id"),
            actor_role=doc.get("actor_role"),
            action=doc["action"],
            entity_type=doc["entity_type"],
            entity_id=doc.get("entity_id"),
            previous_state=doc.get("previous_state"),
            new_state=doc.get("new_state"),
            context=doc.get("context") or {},
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
        )

    async def list_recent(
        self,
        *,
        skip: int,
        limit: int,
        action: str | None = None,
        entity_type: str | None = None,
        q: str | None = None,
    ) -> tuple[list[AuditLog], int]:
        """Page audit rows in MongoDB. Newest records come first."""
        safe_skip = clamp_skip(skip)
        safe_limit = clamp_limit(limit)
        query: dict[str, Any] = {}
        if action:
            query["action"] = action
        if entity_type:
            query["entity_type"] = entity_type
        if q and q.strip():
            query["$or"] = text_clause(q, ("action", "entity_type", "entity_id"))["$or"]
        total = await self.collection.count_documents(query)
        cursor = (
            self.collection.find(query)
            .sort(stable_sort([("created_at", DESCENDING)]))
            .skip(safe_skip)
            .limit(safe_limit)
        )
        docs = await cursor.to_list(length=safe_limit)
        return [self._to_model(doc) for doc in docs], total

    async def find_by_operation_id(self, operation_id: str) -> AuditLog | None:
        if not operation_id:
            return None
        doc = await self.collection.find_one({"operation_id": operation_id})
        return self._to_model(doc) if doc else None

    async def update(self, doc_id: str, update_data: dict[str, Any]) -> AuditLog | None:
        """Audit rows are not edited through the application."""
        del doc_id, update_data
        return None

    async def purge_document(self, doc_id: str) -> bool:
        """Audit rows are not deleted through the application."""
        del doc_id
        return False

    async def create(self, document: dict[str, Any]) -> AuditLog:
        result = await self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return self._to_model(document)
