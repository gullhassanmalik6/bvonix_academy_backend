from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import get_user_repository
from app.core.security import decode_token
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.exceptions import UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    users: UserRepository = Depends(get_user_repository),
) -> User:
    """
    Resolve the authenticated user from the Bearer token.

    This uses FastAPI dependency injection so it's testable and easy to swap.
    """

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()

    token = credentials.credentials
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token")

    user = await users.get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("User not found")
    return user

