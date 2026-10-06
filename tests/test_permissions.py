"""Authorization checks. These do not need MongoDB."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from pydantic import ValidationError

from app.core.admin import (
    get_admin_user,
    get_management_user,
    get_payment_admin,
    get_scholarship_admin,
    get_super_admin_user,
)
from app.core.auth import get_current_user
from app.core.permissions import (
    assert_can_delete_user,
    assert_user_admin_update,
    can_approve_payments,
    can_manage_course,
    can_manage_scholarships,
)
from app.models.user import User
from app.schemas.user import UserUpdate
from app.utils.exceptions import ForbiddenError, UnauthorizedError


def _user(role: str, user_id: str = "user-1", is_active: bool = True) -> User:
    return User(
        id=user_id,
        email=f"{role}@example.com",
        full_name=role,
        hashed_password="hashed",
        is_active=is_active,
        role=role,
        created_at=datetime.now(timezone.utc),
    )


def _status(coro) -> int:
    try:
        asyncio.run(coro)
    except (ForbiddenError, UnauthorizedError) as exc:
        return exc.status_code
    return 200


class PermissionRuleTests(unittest.TestCase):
    def test_student_cannot_approve_payments_or_scholarships(self) -> None:
        self.assertFalse(can_approve_payments("user"))
        self.assertFalse(can_manage_scholarships("user"))

    def test_academic_manager_cannot_approve_payments_or_scholarships(self) -> None:
        self.assertFalse(can_approve_payments("academic_manager"))
        self.assertFalse(can_manage_scholarships("academic_manager"))

    def test_admin_and_super_admin_can_approve_payments_and_scholarships(self) -> None:
        self.assertTrue(can_approve_payments("admin"))
        self.assertTrue(can_manage_scholarships("admin"))
        self.assertTrue(can_approve_payments("super_admin"))
        self.assertTrue(can_manage_scholarships("super_admin"))

    def test_instructor_can_edit_only_assigned_course(self) -> None:
        self.assertTrue(can_manage_course("user", "inst-1", "inst-1"))
        self.assertFalse(can_manage_course("user", "inst-1", "inst-2"))
        self.assertFalse(can_manage_course("user", None, "inst-1"))
        self.assertTrue(can_manage_course("academic_manager", None, "inst-1"))
        self.assertTrue(can_manage_course("admin", None, "inst-9"))

    def test_only_super_admin_can_grant_super_admin(self) -> None:
        assert_user_admin_update("admin", "user", "admin", None)
        with self.assertRaises(ForbiddenError) as raised:
            assert_user_admin_update("admin", "user", "super_admin", None)
        self.assertEqual(raised.exception.status_code, 403)
        with self.assertRaises(ForbiddenError):
            assert_user_admin_update("admin", "super_admin", "admin", False)
        assert_user_admin_update("super_admin", "user", "super_admin", None)

    def test_student_cannot_change_roles(self) -> None:
        with self.assertRaises(ForbiddenError) as raised:
            assert_user_admin_update("user", "user", "admin", None)
        self.assertEqual(raised.exception.status_code, 403)

    def test_admin_cannot_delete_super_admin(self) -> None:
        assert_can_delete_user("admin", "user")
        with self.assertRaises(ForbiddenError):
            assert_can_delete_user("admin", "super_admin")
        assert_can_delete_user("super_admin", "super_admin")
        with self.assertRaises(ForbiddenError):
            assert_can_delete_user("academic_manager", "user")

    def test_user_update_accepts_existing_and_new_roles(self) -> None:
        self.assertEqual(UserUpdate(role="user").role, "user")
        self.assertEqual(UserUpdate(role="admin").role, "admin")
        self.assertEqual(UserUpdate(role="academic_manager").role, "academic_manager")
        self.assertEqual(UserUpdate(role="super_admin").role, "super_admin")
        with self.assertRaises(ValidationError):
            UserUpdate(role="instructor")


class DependencyTests(unittest.TestCase):
    def test_missing_token_is_unauthorized(self) -> None:
        status = _status(get_current_user(credentials=None, users=object()))
        self.assertEqual(status, 401)

    def test_inactive_user_is_unauthorized(self) -> None:
        class _Users:
            async def get_by_id(self, user_id: str) -> User:
                return _user("user", is_active=False)

        with patch("app.core.auth.decode_token", return_value={"sub": "user-1"}):
            credentials = type("Creds", (), {"scheme": "bearer", "credentials": "token"})()
            status = _status(get_current_user(credentials=credentials, users=_Users()))
        self.assertEqual(status, 401)

    def test_student_is_forbidden_from_management(self) -> None:
        student = _user("user")
        self.assertEqual(_status(get_management_user(current_user=student)), 403)
        self.assertEqual(_status(get_payment_admin(current_user=student)), 403)
        self.assertEqual(_status(get_scholarship_admin(current_user=student)), 403)
        self.assertEqual(_status(get_admin_user(current_user=student)), 403)

    def test_academic_manager_can_manage_but_not_payments_or_scholarships(self) -> None:
        manager = _user("academic_manager")
        self.assertEqual(_status(get_management_user(current_user=manager)), 200)
        self.assertEqual(_status(get_payment_admin(current_user=manager)), 403)
        self.assertEqual(_status(get_scholarship_admin(current_user=manager)), 403)
        self.assertEqual(_status(get_admin_user(current_user=manager)), 403)

    def test_admin_keeps_management_and_cannot_act_as_super_admin(self) -> None:
        admin = _user("admin")
        self.assertEqual(_status(get_admin_user(current_user=admin)), 200)
        self.assertEqual(_status(get_payment_admin(current_user=admin)), 200)
        self.assertEqual(_status(get_scholarship_admin(current_user=admin)), 200)
        self.assertEqual(_status(get_super_admin_user(current_user=admin)), 403)

    def test_super_admin_can_access_sensitive_dependency(self) -> None:
        super_admin = _user("super_admin")
        self.assertEqual(_status(get_super_admin_user(current_user=super_admin)), 200)
        self.assertEqual(_status(get_admin_user(current_user=super_admin)), 200)
        self.assertEqual(_status(get_management_user(current_user=super_admin)), 200)


if __name__ == "__main__":
    unittest.main()
