from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.core.dependencies import get_auth_service
from app.models.user import User
from app.schemas.auth import LoginRequest, Token
from app.schemas.user import UserCreate, UserPublic
from app.services.auth_service import AuthService
from app.utils.exceptions import UnauthorizedError

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


def _assert_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    if origin not in set(get_settings().allowed_origins_list()):
        raise UnauthorizedError("Invalid origin")


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> Token:
    _assert_trusted_origin(request)
    issued = await auth.login(payload)
    set_refresh_cookie(response, issued.refresh_token)
    return Token(access_token=issued.access_token)


@router.post("/refresh", response_model=Token)
async def refresh(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> Token:
    """Rotate the refresh cookie and return a new short-lived access token."""
    _assert_trusted_origin(request)
    issued = await auth.refresh(request.cookies.get(REFRESH_COOKIE_NAME))
    set_refresh_cookie(response, issued.refresh_token)
    return Token(access_token=issued.access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Revoke the current refresh session and clear its cookie."""
    _assert_trusted_origin(request)
    await auth.logout(request.cookies.get(REFRESH_COOKIE_NAME))
    clear_refresh_cookie(response)


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
