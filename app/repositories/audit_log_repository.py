from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository
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

    async def list_recent(self, *, skip: int, limit: int) -> tuple[list[AuditLog], int]:
        total = await self.collection.count_documents({})
        cursor = self.collection.find({}).sort("created_at", DESCENDING).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._to_model(doc) for doc in docs], total

    async def create(self, document: dict[str, Any]) -> AuditLog:
        result = await self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return self._to_model(document)
