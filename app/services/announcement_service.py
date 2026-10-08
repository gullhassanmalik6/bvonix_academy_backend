from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.announcement_repository import AnnouncementRepository
from app.schemas.announcement import AnnouncementCreate, AnnouncementUpdate
from app.models.announcement import Announcement
from app.utils.exceptions import NotFoundError


class AnnouncementService:
    def __init__(self, announcement_repo: AnnouncementRepository) -> None:
        self._announcements = announcement_repo

    async def create_announcement(
        self,
        payload: AnnouncementCreate,
        created_by: str,
    ) -> Announcement:
        """Create a new announcement."""
        return await self._announcements.create_announcement(
            course_id=payload.course_id,
            title=payload.title,
            content=payload.content,
            priority=payload.priority,
            is_published=payload.is_published,
            published_at=payload.published_at,
            expires_at=payload.expires_at,
            created_by=created_by,
        )

    async def get_announcement(self, announcement_id: str) -> Announcement:
        """Get announcement by ID."""
        announcement = await self._announcements.get_by_id(announcement_id)
        if not announcement:
            raise NotFoundError("Announcement not found")
        return announcement

    async def list_announcements(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        course_id: str | None = None,
    ) -> tuple[list[Announcement], int]:
        """Page announcements in MongoDB. No course id keeps system-wide rows."""
        return await self._announcements.list_page(skip=skip, limit=limit, course_id=course_id)

    async def get_course_announcements(
        self,
        course_id: str | None,
        published_only: bool = True,
    ) -> list[Announcement]:
        """Get announcements for a course or system-wide."""
        return await self._announcements.get_by_course(course_id, published_only)

    async def update_announcement(
        self,
        announcement_id: str,
        payload: AnnouncementUpdate,
    ) -> Announcement:
        """Update an announcement."""
        announcement = await self.get_announcement(announcement_id)
        
        update_data: dict[str, any] = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.content is not None:
            update_data["content"] = payload.content
        if payload.priority is not None:
            update_data["priority"] = payload.priority
        if payload.is_published is not None:
            update_data["is_published"] = payload.is_published
            if payload.is_published and not announcement.published_at:
                update_data["published_at"] = datetime.now(timezone.utc)
        if payload.expires_at is not None:
            update_data["expires_at"] = payload.expires_at
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._announcements.update(announcement_id, update_data)
        if not updated:
            raise NotFoundError("Announcement not found")
        return updated

    async def delete_announcement(self, announcement_id: str) -> None:
        """Delete an announcement."""
        announcement = await self.get_announcement(announcement_id)
        deleted = await self._announcements.delete(announcement_id)
        if not deleted:
            raise NotFoundError("Announcement not found")
