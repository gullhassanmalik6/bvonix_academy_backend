from __future__ import annotations

from datetime import datetime, timezone

from app.core.permissions import is_management
from app.repositories.announcement_repository import AnnouncementRepository
from app.repositories.course_repository import CourseRepository
from app.schemas.announcement import AnnouncementCreate, AnnouncementUpdate
from app.models.announcement import Announcement
from app.services.archive_actions import archive_record
from app.services.audit_service import AuditService
from app.services.course_service import course_is_operational, require_active_course
from app.utils.exceptions import ForbiddenError, NotFoundError


class AnnouncementService:
    def __init__(
        self,
        announcement_repo: AnnouncementRepository,
        *,
        courses: CourseRepository | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._announcements = announcement_repo
        self._courses = courses
        self._audit = audit

    async def create_announcement(
        self,
        payload: AnnouncementCreate,
        created_by: str,
    ) -> Announcement:
        """Create a new announcement."""
        await require_active_course(self._courses, payload.course_id)
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
        if course_id and not await course_is_operational(self._courses, course_id):
            return [], 0
        return await self._announcements.list_page(skip=skip, limit=limit, course_id=course_id)

    async def get_course_announcements(
        self,
        course_id: str | None,
        published_only: bool = True,
    ) -> list[Announcement]:
        """Get announcements for a course or system-wide."""
        if course_id and not await course_is_operational(self._courses, course_id):
            return []
        return await self._announcements.get_by_course(course_id, published_only)

    async def page_published(
        self,
        course_id: str | None,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Announcement], int]:
        if course_id and not await course_is_operational(self._courses, course_id):
            return [], 0
        return await self._announcements.page_published(course_id, skip=skip, limit=limit)

    async def update_announcement(
        self,
        announcement_id: str,
        payload: AnnouncementUpdate,
    ) -> Announcement:
        """Update an announcement."""
        announcement = await self.get_announcement(announcement_id)
        await require_active_course(self._courses, announcement.course_id)
        
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

    async def delete_announcement(
        self,
        announcement_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive an announcement."""
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        announcement = await self.get_announcement(announcement_id)
        await archive_record(
            self._announcements,
            announcement,
            archived_by=archived_by,
            deactivate=False,
            audit=self._audit,
            action="announcement.delete",
            entity_type="announcement",
            not_found="Announcement not found",
        )
