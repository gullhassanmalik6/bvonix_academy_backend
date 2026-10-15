from __future__ import annotations

from datetime import datetime, timezone

from app.core.permissions import is_management
from app.repositories.course_repository import CourseRepository
from app.repositories.live_session_repository import LiveSessionRepository
from app.schemas.live_session import LiveSessionCreate, LiveSessionUpdate
from app.models.live_session import LiveSession
from app.services.archive_actions import archive_record
from app.services.audit_service import AuditService
from app.services.course_service import course_is_operational, require_active_course
from app.utils.exceptions import ForbiddenError, NotFoundError


class LiveSessionService:
    def __init__(
        self,
        session_repo: LiveSessionRepository,
        *,
        courses: CourseRepository | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._sessions = session_repo
        self._courses = courses
        self._audit = audit

    async def create_session(self, payload: LiveSessionCreate, created_by: str) -> LiveSession:
        """Create a new live session."""
        await require_active_course(self._courses, payload.course_id)
        return await self._sessions.create_session(
            course_id=payload.course_id,
            title=payload.title,
            description=payload.description,
            session_type=payload.session_type,
            start_time=payload.start_time,
            end_time=payload.end_time,
            meeting_link=payload.meeting_link,
            location=payload.location,
            instructor_id=payload.instructor_id,
            max_participants=payload.max_participants,
            created_by=created_by,
        )

    async def get_session(self, session_id: str) -> LiveSession:
        """Get session by ID."""
        session = await self._sessions.get_by_id(session_id)
        if not session:
            raise NotFoundError("Live session not found")
        return session

    async def list_course_sessions(
        self,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[LiveSession], int]:
        """Page sessions for one course without loading the whole set into Python."""
        if not await course_is_operational(self._courses, course_id):
            return [], 0
        return await self._sessions.list_page(course_id, skip=skip, limit=limit)

    async def get_course_sessions(
        self,
        course_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[LiveSession]:
        """Get all sessions for a course."""
        if not await course_is_operational(self._courses, course_id):
            return []
        return await self._sessions.get_by_course(course_id, start_date, end_date)

    async def page_upcoming_for_courses(
        self,
        course_ids: list[str],
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[LiveSession], int]:
        """Page upcoming sessions for courses that are still operational."""
        active = await self._courses.load_by_ids(course_ids) if self._courses is not None else None
        ids = list(active) if active is not None else course_ids
        return await self._sessions.page_upcoming(ids, skip=skip, limit=limit)

    async def get_upcoming_sessions(self, course_id: str | None = None) -> list[LiveSession]:
        """Get upcoming sessions."""
        if course_id and not await course_is_operational(self._courses, course_id):
            return []
        return await self._sessions.get_upcoming(course_id)

    async def update_session(
        self,
        session_id: str,
        payload: LiveSessionUpdate,
    ) -> LiveSession:
        """Update a live session."""
        session = await self.get_session(session_id)
        await require_active_course(self._courses, session.course_id)
        
        update_data: dict[str, any] = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.description is not None:
            update_data["description"] = payload.description
        if payload.start_time is not None:
            update_data["start_time"] = payload.start_time
        if payload.end_time is not None:
            update_data["end_time"] = payload.end_time
        if payload.meeting_link is not None:
            update_data["meeting_link"] = payload.meeting_link
        if payload.location is not None:
            update_data["location"] = payload.location
        if payload.status is not None:
            update_data["status"] = payload.status
        if payload.recording_url is not None:
            update_data["recording_url"] = payload.recording_url
        if payload.is_recorded is not None:
            update_data["is_recorded"] = payload.is_recorded
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._sessions.update(session_id, update_data)
        if not updated:
            raise NotFoundError("Live session not found")
        return updated

    async def delete_session(
        self,
        session_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive a live session."""
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        session = await self.get_session(session_id)
        await archive_record(
            self._sessions,
            session,
            archived_by=archived_by,
            deactivate=False,
            audit=self._audit,
            action="session.delete",
            entity_type="live_session",
            not_found="Live session not found",
        )
