from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.db.index_status import ensure_required_index
from app.models.instructor import Instructor
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class InstructorRepository(BaseRepository[Instructor]):
    collection_name = "instructors"

    async def ensure_indexes(self) -> None:
        # Unique user_id - one instructor per user
        await ensure_required_index(self.collection, [("user_id", ASCENDING)], unique=True)
        # Index on is_active for filtering
        await self.collection.create_index([("is_active", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Instructor:
        return Instructor(
            id=oid_str(doc["_id"]),
            user_id=oid_str(doc["user_id"]),
            bio=doc.get("bio"),
            specialization=doc.get("specialization"),
            years_of_experience=doc.get("years_of_experience"),
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
        )

    async def get_by_id(self, instructor_id: str) -> Instructor | None:
        doc = await self.find_document_by_id(instructor_id)
        return self._to_model(doc) if doc else None

    async def get_by_user_id(self, user_id: str) -> Instructor | None:
        """Get instructor by user_id."""
        try:
            user_oid = ObjectId(user_id)
        except Exception:
            return None
        doc = await self.collection.find_one(with_active({"user_id": user_oid}))
        return self._to_model(doc) if doc else None

    async def create_instructor(
        self,
        *,
        user_id: str,
        bio: str | None = None,
        specialization: str | None = None,
        years_of_experience: int | None = None,
    ) -> Instructor:
        now = datetime.now(timezone.utc)
        try:
            user_oid = ObjectId(user_id)
        except Exception:
            raise ValueError("Invalid user_id")
        
        payload = {
            "user_id": user_oid,
            "bio": bio,
            "specialization": specialization,
            "years_of_experience": years_of_experience,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
