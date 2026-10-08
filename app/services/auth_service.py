from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate
from app.utils.exceptions import ConflictError, UnauthorizedError


@dataclass(slots=True)
class IssuedCredentials:
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(self, user_repo: UserRepository, sessions: SessionRepository | None = None) -> None:
        self._users = user_repo
        self._sessions = sessions

    async def register(self, payload: UserCreate) -> User:
        """Register a student account. Public registration cannot choose a role."""
        try:
            return await self._users.create_user(
                email=payload.email,
                full_name=payload.full_name,
                hashed_password=hash_password(payload.password),
                role="user",
            )
        except DuplicateKeyError as e:
            # Convert MongoDB duplicate key error to our ConflictError
            raise ConflictError("Email already registered") from e
        except Exception as e:
            # Log unexpected errors
            import logging
            logger = logging.getLogger(__name__)
            logger.exception(f"Unexpected error during registration: {e}")
            raise

    async def login(self, payload: LoginRequest) -> IssuedCredentials:
        user = await self._users.get_by_email(payload.email)
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")
        if not user.is_active:
            raise UnauthorizedError("Inactive user")
        issued, _session_id = await self._issue(user)
        return issued

    async def refresh(self, raw_token: str | None) -> IssuedCredentials:
        if not raw_token or self._sessions is None:
            raise UnauthorizedError("Invalid refresh token")
        current = await self._sessions.get_by_token_hash(hash_refresh_token(raw_token))
        if current is None:
            raise UnauthorizedError("Invalid refresh token")
        if current.revoked_at is not None or current.expires_at <= datetime.now(timezone.utc):
            await self._sessions.revoke_all_for_user(current.user_id)
            raise UnauthorizedError("Invalid refresh token")
        user = await self._users.get_by_id(current.user_id)
        if user is None or not user.is_active:
            await self._sessions.revoke_all_for_user(current.user_id)
            raise UnauthorizedError("Inactive user")
        issued, new_session_id = await self._issue(user)
        await self._sessions.revoke(current.id, replaced_by=new_session_id)
        return issued

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token or self._sessions is None:
            return
        current = await self._sessions.get_by_token_hash(hash_refresh_token(raw_token))
        if current is not None and current.revoked_at is None:
            await self._sessions.revoke(current.id)

    async def _issue(self, user: User) -> tuple[IssuedCredentials, str]:
        if self._sessions is None:
            raise UnauthorizedError("Session store is unavailable")
        settings = get_settings()
        raw_refresh = new_refresh_token()
        session = await self._sessions.create(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        )
        return (
            IssuedCredentials(
                access_token=create_access_token(subject=user.id, session_id=session.id),
                refresh_token=raw_refresh,
            ),
            session.id,
        )

