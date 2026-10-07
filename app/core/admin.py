from __future__ import annotations

from fastapi import Depends

from app.core.auth import get_current_user
from app.core.permissions import (
    can_approve_payments,
    can_manage_scholarships,
    is_admin,
    is_management,
    is_super_admin,
)
from app.models.user import User
from app.utils.exceptions import ForbiddenError


async def get_management_user(current_user: User = Depends(get_current_user)) -> User:
    """Academic managers, admins, and super admins."""
    if not is_management(current_user.role):
        raise ForbiddenError("Management access required")
    return current_user


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Admins and super admins. Existing admin accounts keep this access."""
    if not is_admin(current_user.role):
        raise ForbiddenError("Admin access required")
    return current_user


async def get_super_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not is_super_admin(current_user.role):
        raise ForbiddenError("Super admin access required")
    return current_user


async def get_payment_admin(current_user: User = Depends(get_current_user)) -> User:
    if not can_approve_payments(current_user.role):
        raise ForbiddenError("You cannot approve or manage payments")
    return current_user


async def get_scholarship_admin(current_user: User = Depends(get_current_user)) -> User:
    if not can_manage_scholarships(current_user.role):
        raise ForbiddenError("You cannot manage scholarships")
    return current_user
