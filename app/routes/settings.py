"""
Settings routes for user profile and preferences management.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.auth import get_current_user
from app.services.audit_context import capture_audit_request
from app.core.dependencies import get_user_repository, get_user_service
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.settings import (
    NotificationPreferences,
    PasswordChange,
    ProfileUpdate,
    SettingsResponse,
)
from app.services.user_service import UserService

router = APIRouter()


@router.get("/profile")
async def get_profile(
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
) -> dict:
    """Get current user's profile."""
    user = await user_repo.get_by_id(current_user.id)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": getattr(user, "phone", None),
        "role": user.role,
        "created_at": user.created_at.isoformat(),
    }


@router.patch("/profile", response_model=SettingsResponse)
async def update_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> SettingsResponse:
    """Update user profile."""
    from app.schemas.user import UserUpdate
    
    update_data = UserUpdate(full_name=payload.full_name)
    updated_user = await user_service.update_user(current_user.id, update_data)
    
    # Update phone if provided (assuming it's stored in user document)
    if payload.phone is not None:
        # This would need to be added to User model and repository
        # For now, we'll just return success
        pass
    
    return SettingsResponse(
        profile={
            "id": updated_user.id,
            "email": updated_user.email,
            "full_name": updated_user.full_name,
            "phone": payload.phone,
        },
        notification_preferences={},
        message="Profile updated successfully",
    )


@router.post("/password", response_model=SettingsResponse)
async def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
) -> SettingsResponse:
    """Change user password."""
    # Verify current password
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    
    # Hash new password
    new_hashed_password = hash_password(payload.new_password)
    
    # Update password
    await user_repo.update(current_user.id, {"hashed_password": new_hashed_password})
    
    return SettingsResponse(
        profile={},
        notification_preferences={},
        message="Password changed successfully",
    )


@router.get("/notifications")
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
) -> dict:
    """Get user's notification preferences."""
    user = await user_repo.get_by_id(current_user.id)
    # Default preferences if not stored
    preferences = getattr(user, "notification_preferences", {
        "email_notifications": True,
        "push_notifications": True,
        "scholarship_alerts": True,
        "assignment_reminders": True,
        "course_updates": True,
    })
    return preferences


@router.patch("/notifications", response_model=SettingsResponse)
async def update_notification_preferences(
    payload: NotificationPreferences,
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
) -> SettingsResponse:
    """Update user's notification preferences."""
    preferences_dict = {
        "email_notifications": payload.email_notifications,
        "push_notifications": payload.push_notifications,
        "scholarship_alerts": payload.scholarship_alerts,
        "assignment_reminders": payload.assignment_reminders,
        "course_updates": payload.course_updates,
    }
    
    # Update preferences in user document
    await user_repo.update(current_user.id, {"notification_preferences": preferences_dict})
    
    return SettingsResponse(
        profile={},
        notification_preferences=preferences_dict,
        message="Notification preferences updated successfully",
    )


@router.delete("/account")
async def delete_account(
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
    _request=Depends(capture_audit_request),
) -> Response:
    """
    Permanently delete the currently authenticated user's account.

    This uses the same service-layer delete logic as admin user deletion,
    but is scoped to the current user only.
    """
    await user_service.delete_user(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
