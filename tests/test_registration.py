"""Public registration cannot create administrators."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from pydantic import ValidationError

from app.core.permissions import assert_user_admin_update
from app.models.user import User
from app.schemas.user import AdminUserCreate, UserCreate
from app.services.auth_service import AuthService
from app.utils.exceptions import ForbiddenError


class _Users:
    def __init__(self) -> None:
        self.created: dict | None = None

    async def create_user(self, **kwargs) -> User:
        self.created = kwargs
        return User(
            id="new-user",
            email=kwargs["email"],
            full_name=kwargs["full_name"],
            hashed_password=kwargs["hashed_password"],
            is_active=True,
            role=kwargs["role"],
            created_at=datetime.now(timezone.utc),
        )


class PublicRegistrationTests(unittest.TestCase):
    def test_public_payload_has_no_role_field(self) -> None:
        payload = UserCreate.model_validate(
            {
                "email": "student@example.com",
                "password": "password1",
                "full_name": "Student",
                "role": "admin",
            }
        )
        self.assertFalse(hasattr(payload, "role"))

    def test_register_always_creates_a_student(self) -> None:
        repo = _Users()
        service = AuthService(repo)
        with patch("app.services.auth_service.hash_password", return_value="hashed"):
            user = asyncio.run(
                service.register(
                    UserCreate(email="student@example.com", password="password1", full_name="Student")
                )
            )
        self.assertEqual(user.role, "user")
        self.assertEqual(repo.created["role"], "user")

    def test_admin_schema_rejects_unknown_role(self) -> None:
        with self.assertRaises(ValidationError):
            AdminUserCreate(
                email="person@example.com",
                password="password1",
                role="owner",
            )

    def test_existing_admin_can_create_an_admin_but_not_a_super_admin(self) -> None:
        assert_user_admin_update("admin", "user", "admin", None)
        assert_user_admin_update("admin", "user", "user", None)
        with self.assertRaises(ForbiddenError) as raised:
            assert_user_admin_update("admin", "user", "super_admin", None)
        self.assertEqual(raised.exception.status_code, 403)
        assert_user_admin_update("super_admin", "user", "super_admin", None)

    def test_student_cannot_create_an_admin(self) -> None:
        with self.assertRaises(ForbiddenError) as raised:
            assert_user_admin_update("user", "user", "admin", None)
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
