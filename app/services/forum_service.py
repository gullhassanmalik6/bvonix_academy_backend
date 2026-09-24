from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.forum_repository import ForumPostRepository
from app.repositories.user_repository import UserRepository
from app.schemas.forum import ForumPostCreate, ForumPostUpdate, ForumVote
from app.models.forum import ForumPost
from app.utils.exceptions import NotFoundError


class ForumService:
    def __init__(
        self,
        forum_repo: ForumPostRepository,
        user_repo: UserRepository | None = None,
    ) -> None:
        self._posts = forum_repo
        self._users = user_repo

    async def create_post(
        self,
        payload: ForumPostCreate,
        author_id: str,
    ) -> ForumPost:
        """Create a new forum post."""
        return await self._posts.create_post(
            course_id=payload.course_id,
            parent_post_id=payload.parent_post_id,
            author_id=author_id,
            title=payload.title,
            content=payload.content,
            post_type=payload.post_type,
        )

    async def get_post(self, post_id: str) -> ForumPost:
        """Get post by ID and increment views."""
        post = await self._posts.get_by_id(post_id)
        if not post:
            raise NotFoundError("Forum post not found")
        
        # Increment views
        await self._posts.increment_views(post_id)
        return await self._posts.get_by_id(post_id) or post

    async def get_course_posts(
        self,
        course_id: str,
        top_level_only: bool = True,
    ) -> list[ForumPost]:
        """Get forum posts for a course."""
        return await self._posts.get_by_course(course_id, top_level_only)

    async def get_replies(self, post_id: str) -> list[ForumPost]:
        """Get replies to a post."""
        return await self._posts.get_replies(post_id)

    async def update_post(
        self,
        post_id: str,
        payload: ForumPostUpdate,
    ) -> ForumPost:
        """Update a forum post."""
        post = await self.get_post(post_id)
        
        update_data: dict[str, any] = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.content is not None:
            update_data["content"] = payload.content
        if payload.is_resolved is not None:
            update_data["is_resolved"] = payload.is_resolved
        if payload.is_pinned is not None:
            update_data["is_pinned"] = payload.is_pinned
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._posts.update(post_id, update_data)
        if not updated:
            raise NotFoundError("Forum post not found")
        return updated

    async def vote_post(self, post_id: str, payload: ForumVote) -> ForumPost:
        """Vote on a forum post."""
        post = await self.get_post(post_id)
        voted = await self._posts.vote(post_id, payload.vote_type)
        if not voted:
            raise NotFoundError("Forum post not found")
        return voted

    async def delete_post(self, post_id: str) -> None:
        """Delete a forum post."""
        post = await self.get_post(post_id)
        deleted = await self._posts.delete(post_id)
        if not deleted:
            raise NotFoundError("Forum post not found")
