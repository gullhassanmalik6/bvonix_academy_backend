from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.forum import ForumPost
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class ForumPostRepository(BaseRepository[ForumPost]):
    collection_name = "forum_posts"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("parent_post_id", ASCENDING)])
        await self.collection.create_index([("author_id", ASCENDING)])
        await self.collection.create_index([("is_pinned", ASCENDING), ("created_at", -1)])

    def _to_model(self, doc: dict[str, Any]) -> ForumPost:
        return ForumPost(
            id=oid_str(doc["_id"]),
            course_id=oid_str(doc["course_id"]),
            parent_post_id=oid_str(doc["parent_post_id"]) if doc.get("parent_post_id") else None,
            author_id=oid_str(doc["author_id"]),
            title=doc.get("title"),
            content=doc.get("content", ""),
            post_type=doc.get("post_type", "question"),
            is_resolved=doc.get("is_resolved", False),
            is_pinned=doc.get("is_pinned", False),
            upvotes=doc.get("upvotes", 0),
            downvotes=doc.get("downvotes", 0),
            views=doc.get("views", 0),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_course(
        self,
        course_id: str,
        top_level_only: bool = True,
    ) -> list[ForumPost]:
        """Get forum posts for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        filter_dict: dict[str, Any] = {"course_id": course_oid}
        if top_level_only:
            filter_dict["parent_post_id"] = None
        
        cursor = self.collection.find(filter_dict).sort("is_pinned", -1).sort("created_at", -1)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_replies(self, post_id: str) -> list[ForumPost]:
        """Get replies to a post."""
        try:
            post_oid = ObjectId(post_id)
        except Exception:
            return []
        
        cursor = self.collection.find({"parent_post_id": post_oid}).sort("created_at", ASCENDING)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def create_post(
        self,
        *,
        course_id: str,
        parent_post_id: str | None,
        author_id: str,
        title: str | None,
        content: str,
        post_type: str,
    ) -> ForumPost:
        now = datetime.now(timezone.utc)
        try:
            course_oid = ObjectId(course_id)
            parent_oid = ObjectId(parent_post_id) if parent_post_id else None
            author_oid = ObjectId(author_id)
        except Exception:
            raise ValueError("Invalid IDs")
        
        payload = {
            "course_id": course_oid,
            "parent_post_id": parent_oid,
            "author_id": author_oid,
            "title": title,
            "content": content,
            "post_type": post_type,
            "is_resolved": False,
            "is_pinned": False,
            "upvotes": 0,
            "downvotes": 0,
            "views": 0,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    async def increment_views(self, post_id: str) -> ForumPost | None:
        """Increment view count for a post."""
        try:
            oid = ObjectId(post_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            {"_id": oid},
            {"$inc": {"views": 1}},
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def vote(self, post_id: str, vote_type: str) -> ForumPost | None:
        """Vote on a post (upvote/downvote/remove)."""
        try:
            oid = ObjectId(post_id)
        except Exception:
            return None
        
        update_dict: dict[str, Any] = {}
        if vote_type == "upvote":
            update_dict["$inc"] = {"upvotes": 1}
        elif vote_type == "downvote":
            update_dict["$inc"] = {"downvotes": 1}
        elif vote_type == "remove":
            # Remove vote (decrement both)
            update_dict["$inc"] = {"upvotes": -1, "downvotes": -1}
        
        if not update_dict:
            return None
        
        result = await self.collection.find_one_and_update(
            {"_id": oid},
            update_dict,
            return_document=True,
        )
        return self._to_model(result) if result else None
