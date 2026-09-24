"""
Admin authentication and authorization.

Why: Separate admin dependency ensures only admins can access admin routes.
"""

from __future__ import annotations

from fastapi import Depends

from app.core.auth import get_current_user
from app.models.user import User
from app.utils.exceptions import ForbiddenError


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Ensure the current user is an admin.
    
    This dependency should be used on admin-only routes.
    """
    if current_user.role != "admin":
        raise ForbiddenError("Admin access required")
    return current_user
