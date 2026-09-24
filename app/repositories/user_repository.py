from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.user import User
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class UserRepository(BaseRepository[User]):
    collection_name = "users"

    async def ensure_indexes(self) -> None:
        # Unique email for login/identity.
        await self.collection.create_index([("email", ASCENDING)], unique=True)

    def _to_model(self, doc: dict[str, Any]) -> User:
        return User(
            id=oid_str(doc["_id"]),
            email=doc["email"],
            full_name=doc.get("full_name"),
            hashed_password=doc["hashed_password"],
            is_active=doc.get("is_active", True),
            role=doc.get("role", "user"),  # Default to "user" if not set
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
        )

    async def get_by_email(self, email: str) -> User | None:
        doc = await self.collection.find_one({"email": email.lower()})
        return self._to_model(doc) if doc else None

    async def get_by_id(self, user_id: str) -> User | None:
        try:
            oid = ObjectId(user_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"_id": oid})
        return self._to_model(doc) if doc else None

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        full_name: str | None,
        role: str = "user",
    ) -> User:
        now = datetime.now(timezone.utc)
        payload = {
            "email": email.lower(),
            "full_name": full_name,
            "hashed_password": hashed_password,
            "is_active": True,
            "role": role,
            "created_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

