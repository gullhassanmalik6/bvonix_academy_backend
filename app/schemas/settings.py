"""
Settings schemas for user preferences and profile management.
"""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import APIModel


class ProfileUpdate(APIModel):
    """Profile update schema."""
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)


class PasswordChange(APIModel):
    """Password change schema."""
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class NotificationPreferences(APIModel):
    """Notification preferences schema."""
    email_notifications: bool = True
    push_notifications: bool = True
    scholarship_alerts: bool = True
    assignment_reminders: bool = True
    course_updates: bool = True


class SettingsResponse(APIModel):
    """Settings response schema."""
    profile: dict
    notification_preferences: dict
    message: str
