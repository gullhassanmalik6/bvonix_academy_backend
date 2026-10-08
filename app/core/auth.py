from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import get_session_repository, get_user_repository
from app.core.security import decode_token
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_context import set_audit_actor
from app.utils.exceptions import UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    users: UserRepository = Depends(get_user_repository),
    sessions: SessionRepository | None = Depends(get_session_repository),
) -> User:
    """
    Resolve the authenticated user from a short-lived Bearer access token.

    Tokens issued with a session id are rejected when that session is revoked.
    """

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise UnauthorizedError("Invalid token") from exc
    if payload.get("typ") not in (None, "access"):
        raise UnauthorizedError("Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token")

    session_id = payload.get("sid")
    if session_id:
        if sessions is None or not hasattr(sessions, "get_active"):
            raise UnauthorizedError("Session expired")
        session = await sessions.get_active(session_id)
        if session is None or session.user_id != user_id:
            raise UnauthorizedError("Session expired")

    user = await users.get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise UnauthorizedError("Inactive user")
    set_audit_actor(user)
    return user

