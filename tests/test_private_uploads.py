"""Private receipts and profile files require the owner or a management role."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from bson import ObjectId
from starlette.routing import Mount

from app.core.auth import get_current_user
from app.main import create_app
from app.models.user import User
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.student_repository import StudentRepository
from app.routes.uploads import download_private_upload
from app.utils.exceptions import ForbiddenError, NotFoundError, UnauthorizedError

try:
    from tests.test_pagination import NOW, _Database, _run
except ImportError:
    from test_pagination import NOW, _Database, _run


def _account(user_id: ObjectId, role: str) -> User:
    return User(
        id=str(user_id),
        email=f"{role}@example.com",
        full_name=role,
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=NOW,
    )


class PrivateUploadTests(unittest.TestCase):
    def _world(self, filename: str):
        user_id, other_user = ObjectId(), ObjectId()
        student_id, other_student = ObjectId(), ObjectId()
        enrollment_id = ObjectId()
        receipt = f"/uploads/payment_receipts/{filename}"
        profile = f"/uploads/profile_images/{filename.replace('.pdf', '.png')}"
        db = _Database()
        db.add("students", [
            {
                "_id": student_id,
                "user_id": user_id,
                "enrollment_date": NOW,
                "enrolled_courses": [],
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "_id": other_student,
                "user_id": other_user,
                "enrollment_date": NOW,
                "enrolled_courses": [],
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ])
        db.add("enrollments", [{
            "_id": enrollment_id,
            "student_id": student_id,
            "course_id": ObjectId(),
            "enrollment_date": NOW,
            "status": "pending",
            "payment_status": "pending",
            "verified_by_admin": False,
            "class_type": "online",
            "payment_receipt_url": receipt,
            "profile_image_url": profile,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        return db, {
            "user_id": user_id,
            "other_user": other_user,
            "filename": filename,
            "profile_name": filename.replace(".pdf", ".png"),
        }

    def test_owner_and_management_can_read_a_receipt_and_others_cannot(self) -> None:
        filename = "receiptowner01.pdf"
        directory = Path("uploads/payment_receipts")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_bytes(b"%PDF-1.4 receipt")
        db, ids = self._world(filename)
        try:
            response = _run(download_private_upload(
                "payment-receipts",
                filename,
                _account(ids["user_id"], "user"),
                EnrollmentRepository(db),
                StudentRepository(db),
            ))
            self.assertEqual(response.status_code, 200)
            with self.assertRaises(ForbiddenError) as forbidden:
                _run(download_private_upload(
                    "payment-receipts",
                    filename,
                    _account(ids["other_user"], "user"),
                    EnrollmentRepository(db),
                    StudentRepository(db),
                ))
            self.assertEqual(forbidden.exception.status_code, 403)
            self.assertNotIn("payment_receipts", forbidden.exception.detail)
            for role in ("academic_manager", "admin"):
                allowed = _run(download_private_upload(
                    "payment-receipts",
                    filename,
                    _account(ObjectId(), role),
                    EnrollmentRepository(db),
                    StudentRepository(db),
                ))
                self.assertEqual(allowed.status_code, 200)
        finally:
            path.unlink(missing_ok=True)

    def test_profile_file_missing_file_and_traversal_use_a_generic_error(self) -> None:
        db, ids = self._world("missingprofile01.pdf")
        with self.assertRaises(NotFoundError) as missing:
            _run(download_private_upload(
                "profile-images",
                ids["profile_name"],
                _account(ids["user_id"], "user"),
                EnrollmentRepository(db),
                StudentRepository(db),
            ))
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(missing.exception.detail, "File not found")
        for filename in ("../secret.pdf", "..\\secret.pdf", "a/b.pdf", ""):
            with self.assertRaises(NotFoundError) as invalid:
                _run(download_private_upload(
                    "payment-receipts",
                    filename,
                    _account(ids["user_id"], "user"),
                    EnrollmentRepository(db),
                    StudentRepository(db),
                ))
            self.assertEqual(invalid.exception.detail, "File not found")
            self.assertNotIn("secret", invalid.exception.detail)

    def test_public_assets_stay_public_and_private_directories_are_not_mounted(self) -> None:
        app = create_app()
        mounts = [route.path for route in app.routes if isinstance(route, Mount)]
        self.assertIn("/uploads/logos", mounts)
        self.assertNotIn("/uploads", mounts)
        self.assertNotIn("/uploads/payment_receipts", mounts)
        self.assertNotIn("/uploads/profile_images", mounts)
        self.assertNotIn("/uploads/enrollment_cards", mounts)
        public_routes = [
            getattr(route, "path", "")
            for route in app.routes
            if getattr(route, "path", "") == "/uploads/academy_logo.png"
        ]
        self.assertEqual(public_routes, ["/uploads/academy_logo.png"])

    def test_private_download_requires_authentication(self) -> None:
        parameter = inspect.signature(download_private_upload).parameters["current_user"]
        self.assertIs(parameter.default.dependency, get_current_user)
        with self.assertRaises(UnauthorizedError) as raised:
            _run(get_current_user(credentials=None, users=object(), sessions=None))
        self.assertEqual(raised.exception.status_code, 401)
        self.assertNotIn("uploads", raised.exception.detail.lower())
