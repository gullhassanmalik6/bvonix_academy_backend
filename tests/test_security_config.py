"""Production signing-secret checks. These tests do not print secret values."""

from __future__ import annotations

import inspect
import unittest

from jose import jwt

from app.core.admin import get_payment_admin
from app.core.security import decode_token
from app.core.security_config import ensure_production_origins, ensure_production_secret
from app.main import lifespan
from app.models.user import User
from app.repositories.audit_log_repository import AuditLogRepository
from app.utils.exceptions import ForbiddenError

try:
    from tests.test_pagination import NOW, _run
except ImportError:
    from test_pagination import NOW, _run


def _user(role: str) -> User:
    return User(
        id="user-id",
        email="person@example.com",
        full_name="Person",
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=NOW,
    )


class ProductionSecretTests(unittest.TestCase):
    def test_production_rejects_a_missing_or_placeholder_secret(self) -> None:
        for secret in (None, "", "   ", "CHANGE_ME", "change_me_to_a_long_random_secret", "secret"):
            with self.assertRaises(RuntimeError) as raised:
                ensure_production_secret(app_env="production", jwt_secret=secret, jwt_algorithm="HS256")
            message = raised.exception.args[0]
            self.assertNotIn("CHANGE_ME", message)
            if secret and secret.strip() and secret.strip().lower() != "secret":
                self.assertNotIn(secret.strip(), message)

    def test_production_rejects_a_short_secret_and_the_wrong_algorithm(self) -> None:
        with self.assertRaises(RuntimeError):
            ensure_production_secret(app_env="prod", jwt_secret="k" * 31, jwt_algorithm="HS256")
        with self.assertRaises(RuntimeError):
            ensure_production_secret(app_env="production", jwt_secret="k" * 32, jwt_algorithm="none")

    def test_production_accepts_a_long_hs256_secret(self) -> None:
        ensure_production_secret(app_env="production", jwt_secret="k" * 32, jwt_algorithm="HS256")

    def test_production_rejects_empty_origins_and_development_allows_them(self) -> None:
        with self.assertRaises(RuntimeError) as raised:
            ensure_production_origins(app_env="production", allowed_origins="  , ")
        self.assertIn("ALLOWED_ORIGINS", str(raised.exception))
        ensure_production_origins(app_env="development", allowed_origins="")
        ensure_production_origins(app_env="production", allowed_origins="https://academy.example")

    def test_development_can_start_with_the_local_placeholder(self) -> None:
        ensure_production_secret(app_env="development", jwt_secret="CHANGE_ME", jwt_algorithm="HS256")
        ensure_production_secret(app_env="testing", jwt_secret="", jwt_algorithm="HS256")

    def test_startup_validates_the_secret_before_serving(self) -> None:
        source = inspect.getsource(lifespan)
        self.assertIn("ensure_production_secret", source)

    def test_a_token_signed_with_another_secret_is_rejected(self) -> None:
        token = jwt.encode({"sub": "person"}, "k" * 32, algorithm="HS256")
        with self.assertRaises(ValueError):
            decode_token(token)

    def test_a_student_cannot_use_a_payment_admin_route(self) -> None:
        with self.assertRaises(ForbiddenError):
            _run(get_payment_admin(_user("user")))
        with self.assertRaises(ForbiddenError):
            _run(get_payment_admin(_user("academic_manager")))

    def test_operation_index_is_sparse_and_unique(self) -> None:
        source = inspect.getsource(AuditLogRepository.ensure_indexes)
        self.assertIn("operation_id", source)
        self.assertIn("unique=True", source)
        self.assertIn("sparse=True", source)
