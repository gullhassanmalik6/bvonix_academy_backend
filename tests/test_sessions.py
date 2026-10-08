"""Session lifecycle. These tests use the real token and session rules, not a fake login."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from starlette.responses import Response

from app.core.admin import get_admin_user, get_management_user, get_super_admin_user
from app.core.auth import get_current_user
from app.core.config import Settings
from app.core.cookies import set_refresh_cookie
from app.core.security import create_access_token, decode_token
from app.models.auth_session import AuthSession
from app.models.user import User
from app.schemas.auth import LoginRequest, Token
from app.services.auth_service import AuthService
from app.utils.exceptions import ForbiddenError, UnauthorizedError


def _user(role: str, user_id: str) -> User:
    return User(
        id=user_id,
        email=f"{role}@example.com",
        full_name=role,
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=datetime.now(timezone.utc),
    )


class _Users:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get_by_email(self, email: str) -> User | None:
        if email.lower() == self.user.email:
            return self.user
        return None

    async def get_by_id(self, user_id: str) -> User | None:
        if user_id == self.user.id:
            return self.user
        return None


class _Sessions:
    def __init__(self) -> None:
        self.rows: dict[str, AuthSession] = {}

    async def create(self, *, user_id: str, token_hash: str, expires_at: datetime) -> AuthSession:
        session = AuthSession(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
            replaced_by=None,
            created_at=datetime.now(timezone.utc),
        )
        self.rows[session.id] = session
        return session

    async def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        for row in self.rows.values():
            if row.token_hash == token_hash:
                return row
        return None

    async def get_active(self, session_id: str) -> AuthSession | None:
        row = self.rows.get(session_id)
        if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(timezone.utc):
            return None
        return row

    async def revoke(self, session_id: str, *, replaced_by: str | None = None) -> None:
        row = self.rows.get(session_id)
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            row.replaced_by = replaced_by

    async def revoke_all_for_user(self, user_id: str) -> None:
        now = datetime.now(timezone.utc)
        for row in self.rows.values():
            if row.user_id == user_id and row.revoked_at is None:
                row.revoked_at = now


def _run(coro):
    return asyncio.run(coro)


def _status(coro) -> int:
    try:
        _run(coro)
    except (UnauthorizedError, ForbiddenError) as exc:
        return exc.status_code
    return 200


class _Creds:
    def __init__(self, token: str) -> None:
        self.scheme = "bearer"
        self.credentials = token


class AccessTokenTests(unittest.TestCase):
    def test_access_token_has_required_claims_and_short_lifetime(self) -> None:
        token = create_access_token(subject="user-1", session_id="sess-1")
        payload = decode_token(token)
        self.assertEqual(payload["sub"], "user-1")
        self.assertEqual(payload["iss"], "bvonix-academy")
        self.assertEqual(payload["aud"], "bvonix-academy-api")
        self.assertEqual(payload["typ"], "access")
        self.assertEqual(payload["sid"], "sess-1")
        self.assertIn("iat", payload)
        self.assertIn("jti", payload)
        self.assertEqual(
            payload["exp"] - payload["iat"],
            Settings.model_fields["access_token_expire_minutes"].default * 60,
        )
        self.assertEqual(Settings.model_fields["access_token_expire_minutes"].default, 15)

    def test_expired_access_token_is_rejected(self) -> None:
        token = create_access_token(subject="user-1", session_id="sess-1", expires_minutes=-1)
        with self.assertRaises(ValueError):
            decode_token(token)
        status = _status(
            get_current_user(credentials=_Creds(token), users=_Users(_user("user", "user-1")), sessions=_Sessions())
        )
        self.assertEqual(status, 401)

    def test_refresh_cookie_is_httponly(self) -> None:
        response = Response()
        set_refresh_cookie(response, "refresh-secret")
        header = response.headers["set-cookie"].lower()
        self.assertIn("httponly", header)
        self.assertIn("secure", header)
        self.assertIn("samesite=none", header)
        self.assertNotIn("refresh_token", Token.model_fields)


class SessionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = _user("user", "user-1")
        self.users = _Users(self.user)
        self.sessions = _Sessions()
        self.service = AuthService(self.users, self.sessions)

    def _login(self):
        with patch("app.services.auth_service.verify_password", return_value=True):
            return _run(self.service.login(LoginRequest(email=self.user.email, password="password1")))

    def test_invalid_refresh_token_is_rejected(self) -> None:
        with self.assertRaises(UnauthorizedError):
            _run(self.service.refresh("not-a-session"))

    def test_refresh_rotates_and_reuse_revokes_the_session(self) -> None:
        issued = self._login()
        rotated = _run(self.service.refresh(issued.refresh_token))
        self.assertNotEqual(rotated.refresh_token, issued.refresh_token)
        current = _run(self.service.refresh(rotated.refresh_token))
        _run(get_current_user(credentials=_Creds(current.access_token), users=self.users, sessions=self.sessions))
        with self.assertRaises(UnauthorizedError):
            _run(self.service.refresh(issued.refresh_token))
        with self.assertRaises(UnauthorizedError):
            _run(self.service.refresh(current.refresh_token))

    def test_logout_revokes_refresh_and_access(self) -> None:
        issued = self._login()
        _run(self.service.logout(issued.refresh_token))
        with self.assertRaises(UnauthorizedError):
            _run(self.service.refresh(issued.refresh_token))
        status = _status(
            get_current_user(credentials=_Creds(issued.access_token), users=self.users, sessions=self.sessions)
        )
        self.assertEqual(status, 401)

    def test_revoked_session_blocks_a_valid_access_token(self) -> None:
        issued = self._login()
        _run(self.sessions.revoke_all_for_user(self.user.id))
        status = _status(
            get_current_user(credentials=_Creds(issued.access_token), users=self.users, sessions=self.sessions)
        )
        self.assertEqual(status, 401)
        with self.assertRaises(UnauthorizedError):
            _run(self.service.refresh(issued.refresh_token))

    def test_student_access_token_stays_out_of_admin_and_admin_token_is_allowed(self) -> None:
        issued = self._login()
        student = _run(
            get_current_user(credentials=_Creds(issued.access_token), users=self.users, sessions=self.sessions)
        )
        self.assertEqual(_status(get_management_user(current_user=student)), 403)
        self.assertEqual(_status(get_admin_user(current_user=student)), 403)

        admin = _user("admin", "admin-1")
        admin_users = _Users(admin)
        admin_sessions = _Sessions()
        admin_service = AuthService(admin_users, admin_sessions)
        with patch("app.services.auth_service.verify_password", return_value=True):
            admin_issued = _run(admin_service.login(LoginRequest(email=admin.email, password="password1")))
        resolved = _run(
            get_current_user(
                credentials=_Creds(admin_issued.access_token),
                users=admin_users,
                sessions=admin_sessions,
            )
        )
        self.assertEqual(_status(get_admin_user(current_user=resolved)), 200)
        self.assertEqual(_status(get_management_user(current_user=resolved)), 200)
        self.assertEqual(_status(get_super_admin_user(current_user=resolved)), 403)

        manager = _user("academic_manager", "manager-1")
        self.assertEqual(_status(get_management_user(current_user=manager)), 200)
        self.assertEqual(_status(get_admin_user(current_user=manager)), 403)
        super_admin = _user("super_admin", "super-1")
        self.assertEqual(_status(get_super_admin_user(current_user=super_admin)), 200)
        self.assertEqual(_status(get_admin_user(current_user=super_admin)), 200)


if __name__ == "__main__":
    unittest.main()
