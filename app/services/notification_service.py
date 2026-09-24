from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.notification_repository import NotificationRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.notification import NotificationCreate, NotificationUpdate
from app.models.notification import Notification
from app.utils.exceptions import NotFoundError


class NotificationService:
    def __init__(
        self,
        notification_repo: NotificationRepository,
        user_repo: UserRepository | None = None,
        student_repo: StudentRepository | None = None,
    ) -> None:
        self._notifications = notification_repo
        self._users = user_repo
        self._students = student_repo

    async def create_notification(
        self,
        payload: NotificationCreate,
    ) -> Notification:
        """Create a new notification."""
        return await self._notifications.create_notification(
            user_id=payload.user_id,
            title=payload.title,
            message=payload.message,
            notification_type=payload.notification_type,
            related_entity_type=payload.related_entity_type,
            related_entity_id=payload.related_entity_id,
            priority=payload.priority,
        )

    async def create_scholarship_at_risk_notification(
        self,
        user_id: str,
        scholarship_id: str,
        course_title: str | None = None,
        absences: int = 0,
        max_absences: int = 3,
    ) -> Notification:
        """Create notification when scholarship is at risk."""
        course_text = f" for {course_title}" if course_title else ""
        return await self._notifications.create_notification(
            user_id=user_id,
            title="Scholarship At Risk",
            message=f"Your scholarship{course_text} is at risk. You have {absences} out of {max_absences} allowed absences this month. One more absence will result in termination.",
            notification_type="scholarship_at_risk",
            related_entity_type="scholarship",
            related_entity_id=scholarship_id,
            priority="high",
        )

    async def create_enrollment_verified_notification(
        self,
        user_id: str,
        enrollment_id: str,
        course_title: str | None = None,
    ) -> Notification:
        """Create notification when admin verifies enrollment payment."""
        course_text = f" for {course_title}" if course_title else ""
        return await self._notifications.create_notification(
            user_id=user_id,
            title="Enrollment Verified",
            message=f"Your enrollment{course_text} has been verified. You now have full access to course materials, assignments, and more.",
            notification_type="enrollment_verified",
            related_entity_type="enrollment",
            related_entity_id=enrollment_id,
            priority="high",
        )

    async def create_scholarship_terminated_notification(
        self,
        user_id: str,
        scholarship_id: str,
        course_title: str | None = None,
        reason: str | None = None,
    ) -> Notification:
        """Create notification when scholarship is terminated."""
        course_text = f" for {course_title}" if course_title else ""
        reason_text = f" Reason: {reason}" if reason else ""
        return await self._notifications.create_notification(
            user_id=user_id,
            title="Scholarship Terminated",
            message=f"Your scholarship{course_text} has been terminated.{reason_text}",
            notification_type="scholarship_terminated",
            related_entity_type="scholarship",
            related_entity_id=scholarship_id,
            priority="urgent",
        )

    async def get_notifications(
        self,
        user_id: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[Notification]:
        """Get notifications for a user."""
        return await self._notifications.get_by_user(user_id, unread_only, limit)

    async def get_notification(self, notification_id: str) -> Notification:
        """Get a notification by ID."""
        notification = await self._notifications.get_by_id(notification_id)
        if not notification:
            raise NotFoundError("Notification not found")
        return notification

    async def mark_as_read(self, notification_id: str) -> Notification:
        """Mark a notification as read."""
        notification = await self._notifications.mark_as_read(notification_id)
        if not notification:
            raise NotFoundError("Notification not found")
        return notification

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        return await self._notifications.mark_all_as_read(user_id)

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications for a user."""
        return await self._notifications.get_unread_count(user_id)
