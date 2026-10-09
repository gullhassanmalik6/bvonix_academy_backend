"""
Notification routes for LMS.

Why: Separate routes for notification management.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.auth import get_current_user
from app.core.dependencies import get_notification_service
from app.models.user import User
from app.schemas.notification import NotificationPublic
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get("", response_model=list[NotificationPublic])
async def get_my_notifications(
    unread_only: bool = Query(default=False, description="Filter to unread notifications only"),
    skip: int = Query(default=0, ge=0, description="Number of matching notifications to skip"),
    limit: int = Query(default=50, ge=1, le=100, description="Page size. This route returns one page, not the full inbox."),
    current_user: User = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
) -> list[NotificationPublic]:
    """Get one page of notifications for the current user."""
    notifications = await notification_service.get_notifications(
        current_user.id,
        unread_only=unread_only,
        limit=limit,
        skip=skip,
    )
    return [
        NotificationPublic(
            id=n.id,
            user_id=n.user_id,
            title=n.title,
            message=n.message,
            notification_type=n.notification_type,
            related_entity_type=n.related_entity_type,
            related_entity_id=n.related_entity_id,
            is_read=n.is_read,
            read_at=n.read_at,
            priority=n.priority,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in notifications
    ]


@router.get("/unread-count", response_model=dict)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
) -> dict:
    """Get count of unread notifications for current user."""
    count = await notification_service.get_unread_count(current_user.id)
    return {"unread_count": count}


@router.post("/{notification_id}/read", response_model=NotificationPublic)
async def mark_notification_as_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
) -> NotificationPublic:
    """Mark a notification as read."""
    notification = await notification_service.mark_as_read(notification_id)
    
    # Verify notification belongs to current user
    if notification.user_id != current_user.id:
        from app.utils.exceptions import NotFoundError
        raise NotFoundError("Notification not found")
    
    return NotificationPublic(
        id=notification.id,
        user_id=notification.user_id,
        title=notification.title,
        message=notification.message,
        notification_type=notification.notification_type,
        related_entity_type=notification.related_entity_type,
        related_entity_id=notification.related_entity_id,
        is_read=notification.is_read,
        read_at=notification.read_at,
        priority=notification.priority,
        created_at=notification.created_at,
        updated_at=notification.updated_at,
    )


@router.post("/mark-all-read", response_model=dict)
async def mark_all_notifications_as_read(
    current_user: User = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
) -> dict:
    """Mark all notifications as read for current user."""
    count = await notification_service.mark_all_as_read(current_user.id)
    return {"marked_count": count}
