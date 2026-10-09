from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.course_repository import CourseRepository
from app.repositories.forum_repository import ForumPostRepository
from app.repositories.user_repository import UserRepository
from app.schemas.forum import ForumPostCreate, ForumPostUpdate, ForumVote
from app.models.forum import ForumPost
from app.services.archive_actions import archive_record
from app.services.course_service import course_is_operational, require_active_course
from app.utils.exceptions import NotFoundError


class ForumService:
    def __init__(
        self,
        forum_repo: ForumPostRepository,
        user_repo: UserRepository | None = None,
        *,
        courses: CourseRepository | None = None,
    ) -> None:
        self._posts = forum_repo
        self._users = user_repo
        self._courses = courses

    async def create_post(
        self,
        payload: ForumPostCreate,
        author_id: str,
    ) -> ForumPost:
        """Create a new forum post."""
        await require_active_course(self._courses, payload.course_id)
        return await self._posts.create_post(
            course_id=payload.course_id,
            parent_post_id=payload.parent_post_id,
            author_id=author_id,
            title=payload.title,
            content=payload.content,
            post_type=payload.post_type,
        )

    async def get_post(self, post_id: str, *, operational: bool = False) -> ForumPost:
        """Get post by ID and increment views."""
        post = await self._posts.get_by_id(post_id)
        if not post:
            raise NotFoundError("Forum post not found")
        if operational and not await course_is_operational(self._courses, post.course_id):
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
        if not await course_is_operational(self._courses, course_id):
            return []
        return await self._posts.get_by_course(course_id, top_level_only)

    async def page_course_posts(
        self,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        top_level_only: bool = True,
    ) -> tuple[list[ForumPost], int]:
        if not await course_is_operational(self._courses, course_id):
            return [], 0
        return await self._posts.page_by_course(
            course_id, top_level_only=top_level_only, skip=skip, limit=limit
        )

    async def get_replies(self, post_id: str) -> list[ForumPost]:
        """Get replies to a post."""
        return await self._posts.get_replies(post_id)

    async def reply_counts(self, post_ids: list[str]) -> dict[str, int]:
        return await self._posts.count_replies_for(post_ids)

    async def page_replies(
        self,
        post_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ForumPost], int]:
        return await self._posts.page_replies(post_id, skip=skip, limit=limit)

    async def update_post(
        self,
        post_id: str,
        payload: ForumPostUpdate,
    ) -> ForumPost:
        """Update a forum post."""
        post = await self.get_post(post_id, operational=True)
        
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

    async def delete_post(self, post_id: str, *, archived_by: str | None = None) -> None:
        """Archive a forum post. There is no public hard-delete route."""
        post = await self.get_post(post_id)
        await archive_record(
            self._posts,
            post,
            archived_by=archived_by,
            deactivate=False,
            audit=None,
            action="forum.delete",
            entity_type="forum_post",
            not_found="Forum post not found",
        )
