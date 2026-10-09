from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING

from app.db.index_status import ensure_required_index
from app.models.auth_session import AuthSession
from app.repositories.base import BaseRepository


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class SessionRepository(BaseRepository[AuthSession]):
    collection_name = "auth_sessions"

    async def ensure_indexes(self) -> None:
        await ensure_required_index(self.collection, [("token_hash", ASCENDING)], unique=True)
        await self.collection.create_index([("user_id", ASCENDING), ("revoked_at", ASCENDING)])
        await self.collection.create_index([("expires_at", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> AuthSession:
        return AuthSession(
            id=str(doc["_id"]),
            user_id=doc["user_id"],
            token_hash=doc["token_hash"],
            expires_at=_aware(doc["expires_at"]),
            revoked_at=_aware(doc["revoked_at"]) if doc.get("revoked_at") else None,
            replaced_by=doc.get("replaced_by"),
            created_at=_aware(doc.get("created_at") or datetime.now(timezone.utc)),
        )

    async def create(self, *, user_id: str, token_hash: str, expires_at: datetime) -> AuthSession:
        session_id = str(uuid.uuid4())
        document = {
            "_id": session_id,
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "revoked_at": None,
            "replaced_by": None,
            "created_at": datetime.now(timezone.utc),
        }
        await self.collection.insert_one(document)
        return self._to_model(document)

    async def get_by_id(self, session_id: str) -> AuthSession | None:
        doc = await self.collection.find_one({"_id": session_id})
        return self._to_model(doc) if doc else None

    async def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        doc = await self.collection.find_one({"token_hash": token_hash})
        return self._to_model(doc) if doc else None

    async def get_active(self, session_id: str) -> AuthSession | None:
        session = await self.get_by_id(session_id)
        if session is None or session.revoked_at is not None:
            return None
        if session.expires_at <= datetime.now(timezone.utc):
            return None
        return session

    async def revoke(self, session_id: str, *, replaced_by: str | None = None) -> None:
        await self.collection.update_one(
            {"_id": session_id, "revoked_at": None},
            {"$set": {"revoked_at": datetime.now(timezone.utc), "replaced_by": replaced_by}},
        )

    async def revoke_all_for_user(self, user_id: str) -> None:
        await self.collection.update_many(
            {"user_id": user_id, "revoked_at": None},
            {"$set": {"revoked_at": datetime.now(timezone.utc)}},
        )
