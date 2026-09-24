from __future__ import annotations

from datetime import datetime

from app.schemas.common import APIModel


class NotificationCreate(APIModel):
    """Schema for creating a notification."""
    user_id: str
    title: str
    message: str
    notification_type: str
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    priority: str = "normal"


class NotificationUpdate(APIModel):
    """Schema for updating a notification."""
    is_read: bool | None = None


class NotificationPublic(APIModel):
    """Public schema for notification."""
    id: str
    user_id: str
    title: str
    message: str
    notification_type: str
    related_entity_type: str | None
    related_entity_id: str | None
    is_read: bool
    read_at: datetime | None
    priority: str
    created_at: datetime
    updated_at: datetime
