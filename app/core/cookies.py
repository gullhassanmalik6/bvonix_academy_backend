from __future__ import annotations

from fastapi import Response

from app.core.config import get_settings

REFRESH_COOKIE_NAME = "bvonix_refresh"


def refresh_cookie_path() -> str:
    return f"{get_settings().api_prefix}/auth"


def set_refresh_cookie(response: Response, token: str) -> None:
    """Store the refresh secret where page scripts cannot read it."""
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=refresh_cookie_path(),
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=refresh_cookie_path(),
        httponly=True,
        secure=True,
        samesite="none",
    )
