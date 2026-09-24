from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.models.notification import Notification
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class NotificationRepository(BaseRepository[Notification]):
    collection_name = "notifications"

    async def ensure_indexes(self) -> None:
        # Index on user_id for quick lookups
        await self.collection.create_index([("user_id", ASCENDING)])
        await self.collection.create_index([("user_id", ASCENDING), ("is_read", ASCENDING)])
        await self.collection.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        await self.collection.create_index([("notification_type", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Notification:
        return Notification(
            id=oid_str(doc["_id"]),
            user_id=oid_str(doc["user_id"]),
            title=doc.get("title", ""),
            message=doc.get("message", ""),
            notification_type=doc.get("notification_type", "info"),
            related_entity_type=doc.get("related_entity_type"),
            related_entity_id=oid_str(doc["related_entity_id"]) if doc.get("related_entity_id") else None,
            is_read=doc.get("is_read", False),
            read_at=doc.get("read_at"),
            priority=doc.get("priority", "normal"),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def create_notification(
        self,
        *,
        user_id: str,
        title: str,
        message: str,
        notification_type: str,
        related_entity_type: str | None = None,
        related_entity_id: str | None = None,
        priority: str = "normal",
    ) -> Notification:
        now = datetime.now(timezone.utc)
        try:
            user_oid = ObjectId(user_id)
            related_oid = ObjectId(related_entity_id) if related_entity_id else None
        except Exception:
            raise ValueError("Invalid user_id or related_entity_id")
        
        payload = {
            "user_id": user_oid,
            "title": title,
            "message": message,
            "notification_type": notification_type,
            "related_entity_type": related_entity_type,
            "related_entity_id": related_oid,
            "is_read": False,
            "read_at": None,
            "priority": priority,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    async def get_by_user(
        self,
        user_id: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[Notification]:
        """Get notifications for a user."""
        try:
            user_oid = ObjectId(user_id)
        except Exception:
            return []
        
        filter_dict: dict[str, Any] = {"user_id": user_oid}
        if unread_only:
            filter_dict["is_read"] = False
        
        cursor = self.collection.find(filter_dict).sort("created_at", DESCENDING).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._to_model(doc) for doc in docs]

    async def mark_as_read(self, notification_id: str) -> Notification | None:
        """Mark a notification as read."""
        now = datetime.now(timezone.utc)
        try:
            oid = ObjectId(notification_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            {"_id": oid},
            {
                "$set": {
                    "is_read": True,
                    "read_at": now,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        now = datetime.now(timezone.utc)
        try:
            user_oid = ObjectId(user_id)
        except Exception:
            return 0
        
        result = await self.collection.update_many(
            {"user_id": user_oid, "is_read": False},
            {
                "$set": {
                    "is_read": True,
                    "read_at": now,
                    "updated_at": now,
                }
            },
        )
        return result.modified_count

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications for a user."""
        try:
            user_oid = ObjectId(user_id)
        except Exception:
            return 0
        
        count = await self.collection.count_documents({"user_id": user_oid, "is_read": False})
        return count
