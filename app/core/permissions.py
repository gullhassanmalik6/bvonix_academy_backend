"""Central permission rules.

Stored account roles stay compatible with existing records:
- user: student account (the existing default)
- academic_manager: academic operations only
- admin: existing management account
- super_admin: admin permissions plus sensitive system changes

Instructor is not a login role. A user manages instructor resources only when
an instructor profile is linked to that user and the resource belongs to it.
"""

from __future__ import annotations

from app.utils.exceptions import ForbiddenError

ROLE_USER = "user"
ROLE_ACADEMIC_MANAGER = "academic_manager"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"

STORED_ROLES = frozenset(
    {ROLE_USER, ROLE_ACADEMIC_MANAGER, ROLE_ADMIN, ROLE_SUPER_ADMIN}
)
MANAGEMENT_ROLES = frozenset({ROLE_ACADEMIC_MANAGER, ROLE_ADMIN, ROLE_SUPER_ADMIN})
ADMIN_ROLES = frozenset({ROLE_ADMIN, ROLE_SUPER_ADMIN})

ROLE_PATTERN = "^(user|academic_manager|admin|super_admin)$"


def is_management(role: str) -> bool:
    return role in MANAGEMENT_ROLES


def is_admin(role: str) -> bool:
    return role in ADMIN_ROLES


def is_super_admin(role: str) -> bool:
    return role == ROLE_SUPER_ADMIN


def can_approve_payments(role: str) -> bool:
    """Students, instructors, and academic managers cannot approve payments."""
    return is_admin(role)


def can_manage_scholarships(role: str) -> bool:
    """Scholarship management is admin-only unless a future permission grants it."""
    return is_admin(role)


def can_manage_course(
    role: str,
    instructor_profile_id: str | None,
    course_instructor_id: str,
) -> bool:
    if is_management(role):
        return True
    return bool(instructor_profile_id) and instructor_profile_id == course_instructor_id


def assert_user_admin_update(
    actor_role: str,
    target_role: str,
    new_role: str | None,
    new_is_active: bool | None,
) -> None:
    """Role and activation changes are system operations."""
    if not is_admin(actor_role):
        raise ForbiddenError("Admin access required")
    if new_role is not None and new_role != target_role:
        if new_role not in STORED_ROLES:
            raise ForbiddenError("Invalid role")
        if new_role == ROLE_SUPER_ADMIN or target_role == ROLE_SUPER_ADMIN:
            if not is_super_admin(actor_role):
                raise ForbiddenError("Super admin access required")
    if (
        new_is_active is not None
        and target_role == ROLE_SUPER_ADMIN
        and not is_super_admin(actor_role)
    ):
        raise ForbiddenError("Super admin access required")


def assert_can_delete_user(actor_role: str, target_role: str) -> None:
    if not is_admin(actor_role):
        raise ForbiddenError("Admin access required")
    if target_role == ROLE_SUPER_ADMIN and not is_super_admin(actor_role):
        raise ForbiddenError("Super admin access required")
