"""
User management routes.

Why: Separate routes file for user CRUD operations keeps
the codebase organized and follows single responsibility principle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.auth import get_current_user
from app.core.dependencies import get_user_repository, get_user_service
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginatedResponse
from app.schemas.user import UserPublic, UserUpdate
from app.services.user_service import UserService

router = APIRouter()


@router.get("", response_model=PaginatedResponse[UserPublic])
async def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[UserPublic]:
    """List all users (paginated)."""
    users, total = await service.list_users(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[
            UserPublic(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                is_active=u.is_active,
                role=u.role,
                created_at=u.created_at,
            )
            for u in users
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(
    user_id: str,
    service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    """Get a user by ID."""
    user = await service.get_user(user_id)
    return UserPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.patch("/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    """Update a user."""
    user = await service.update_user(user_id, payload)
    return UserPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    service: UserService = Depends(get_user_service),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a user."""
    await service.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
