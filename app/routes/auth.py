from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.core.auth import get_current_user
from app.core.dependencies import get_auth_service
from app.models.user import User
from app.schemas.auth import LoginRequest, Token
from app.schemas.user import UserCreate, UserPublic
from app.services.auth_service import AuthService

router = APIRouter()


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    auth: AuthService = Depends(get_auth_service),
) -> UserPublic:
    """Register a student account. Administrator accounts are created by an existing admin."""
    user = await auth.register(payload)
    return UserPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        role=user.role,
        created_at=user.created_at,
    )


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> Token:
    return await auth.login(payload)


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        role=current_user.role,
        created_at=current_user.created_at,
    )
