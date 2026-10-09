"""Operational lookups hide archived rows. Maintenance reads and purge still see them."""

from __future__ import annotations

import asyncio
import inspect
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId

from app.core.auth import get_current_user
from app.core.security import create_access_token, hash_refresh_token
from app.models.auth_session import AuthSession
from app.models.user import User
from app.repositories.attendance_correction_repository import AttendanceCorrectionRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.certificate_repository import CertificateRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.scholarship_repository import ScholarshipRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.lms import get_student_dashboard
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.utils.exceptions import UnauthorizedError


def _matches(document: dict, query: dict) -> bool:
    for key, expected in query.items():
        if key == "archived_at" and expected is None:
            if document.get("archived_at") is not None:
                return False
            continue
        if isinstance(expected, dict) and "$in" in expected:
            if document.get(key) not in expected["$in"]:
                return False
            continue
        if document.get(key) != expected:
            return False
    return True


class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents

    def sort(self, spec):
        del spec
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        if length is None:
            return list(self.documents)
        return list(self.documents)[:length]


class _Collection:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents

    async def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if _matches(document, query):
                return document
        return None

    def find(self, query: dict):
        return _Cursor([document for document in self.documents if _matches(document, query)])

    async def find_one_and_update(self, query: dict, update: dict, return_document: bool = False) -> dict | None:
        del return_document
        for document in self.documents:
            if _matches(document, query):
                document.update(update.get("$set", {}))
                return document
        return None

    async def delete_one(self, query: dict) -> SimpleNamespace:
        before = len(self.documents)
        self.documents = [document for document in self.documents if not _matches(document, query)]
        return SimpleNamespace(deleted_count=before - len(self.documents))


class _Database:
    def __init__(self, documents: list[dict]) -> None:
        self.collection = _Collection(documents)

    def __getitem__(self, name: str) -> _Collection:
        return self.collection


def _run(coro):
    return asyncio.run(coro)


NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _ref() -> ObjectId:
    return ObjectId()


class LookupTests(unittest.TestCase):
    def _repo(self, repository_type, active_id: ObjectId, archived_id: ObjectId, legacy_id: ObjectId, **common):
        archived_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        documents = [
            {"_id": active_id, **common, "archived_at": None},
            {"_id": archived_id, **common, "archived_at": archived_at, "archived_by": "admin-1"},
            {"_id": legacy_id, **common},
        ]
        return repository_type(_Database(documents))

    def test_direct_id_lookups_hide_archived_rows_and_keep_legacy_rows(self) -> None:
        cases = [
            (UserRepository, {"email": "ada@example.com", "hashed_password": "hashed", "full_name": "Ada", "is_active": True, "role": "user", "created_at": NOW}),
            (StudentRepository, {"user_id": _ref(), "enrollment_date": NOW, "enrolled_courses": [], "is_active": True, "created_at": NOW, "updated_at": NOW}),
            (InstructorRepository, {"user_id": _ref(), "bio": "Teaches", "specialization": "Speech", "is_active": True, "created_at": NOW, "updated_at": NOW}),
            (ScholarshipRepository, {"student_id": _ref(), "enrollment_id": _ref(), "scholarship_type": "merit", "amount": 10, "status": "active", "start_date": NOW, "created_at": NOW, "updated_at": NOW}),
            (AttendanceRepository, {"student_id": _ref(), "course_id": _ref(), "enrollment_id": _ref(), "date": NOW, "status": "present", "marked_by": _ref(), "is_excused": False, "created_at": NOW, "updated_at": NOW}),
            (CertificateRepository, {"student_id": _ref(), "course_id": _ref(), "enrollment_id": _ref(), "certificate_number": "BVX-ACTIVE", "issued_by": _ref(), "is_verified": True, "created_at": NOW, "updated_at": NOW}),
        ]
        for repository_type, common in cases:
            active_id, archived_id, legacy_id = ObjectId(), ObjectId(), ObjectId()
            if repository_type is CertificateRepository:
                common = {**common, "certificate_number": f"BVX-{active_id}"}
            repo = self._repo(repository_type, active_id, archived_id, legacy_id, **common)
            self.assertEqual(_run(repo.get_by_id(str(active_id))).id, str(active_id))
            self.assertIsNone(_run(repo.get_by_id(str(archived_id))))
            self.assertEqual(_run(repo.get_by_id(str(legacy_id))).id, str(legacy_id))
            self.assertIsNone(_run(repo.get_by_id("not-an-id")))
            kept = _run(repo.get_including_archived(str(archived_id)))
            self.assertEqual(kept.id, str(archived_id))
            self.assertIsNotNone(kept.archived_at)

    def test_archived_certificate_number_is_hidden_but_still_reserved(self) -> None:
        number = "BVX-ARCHIVED"
        archived = {
            "_id": ObjectId(),
            "student_id": _ref(),
            "course_id": _ref(),
            "enrollment_id": _ref(),
            "certificate_number": number,
            "issued_by": _ref(),
            "archived_at": NOW,
        }
        repo = CertificateRepository(_Database([archived]))
        self.assertIsNone(_run(repo.get_by_certificate_number(number)))
        self.assertIsNone(_run(repo.get_by_id(str(archived["_id"]))))
        reserved = _run(repo.get_by_certificate_number(number, include_archived=True))
        self.assertEqual(reserved.certificate_number, number)

    def test_enrollment_lookup_is_not_given_archive_behavior(self) -> None:
        self.assertNotIn("with_active", inspect.getsource(EnrollmentRepository.get_by_id))
        self.assertNotIn("with_active", inspect.getsource(AttendanceCorrectionRepository.get_by_id))
        enrollment_id = ObjectId()
        repo = EnrollmentRepository(
            _Database(
                [
                    {
                        "_id": enrollment_id,
                        "student_id": _ref(),
                        "course_id": _ref(),
                        "status": "cancelled",
                        "payment_status": "paid",
                        "archived_at": NOW,
                    }
                ]
            )
        )
        enrollment = _run(repo.get_by_id(str(enrollment_id)))
        self.assertEqual(enrollment.status, "cancelled")
        self.assertEqual(enrollment.payment_status, "paid")

    def test_normal_update_does_not_change_an_archived_record(self) -> None:
        active_id, archived_id, legacy_id = ObjectId(), ObjectId(), ObjectId()
        common = {
            "student_id": _ref(),
            "course_id": _ref(),
            "enrollment_id": _ref(),
            "date": NOW,
            "status": "present",
            "marked_by": _ref(),
            "notes": "original",
            "created_at": NOW,
            "updated_at": NOW,
        }
        repo = self._repo(AttendanceRepository, active_id, archived_id, legacy_id, **common)
        self.assertIsNone(_run(repo.update(str(archived_id), {"notes": "changed"})))
        stored = _run(repo.get_including_archived(str(archived_id)))
        self.assertEqual(stored.notes, "original")
        changed = _run(repo.update(str(active_id), {"notes": "checked"}))
        self.assertEqual(changed.notes, "checked")
        legacy = _run(repo.update(str(legacy_id), {"notes": "legacy"}))
        self.assertEqual(legacy.notes, "legacy")


class _Sessions:
    def __init__(self) -> None:
        self.rows: dict[str, AuthSession] = {}
        self.revoked: list[str] = []

    async def create(self, *, user_id: str, token_hash: str, expires_at: datetime) -> AuthSession:
        session = AuthSession(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
            replaced_by=None,
            created_at=NOW,
        )
        self.rows[session.id] = session
        return session

    async def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        return next((row for row in self.rows.values() if row.token_hash == token_hash), None)

    async def get_active(self, session_id: str) -> AuthSession | None:
        row = self.rows.get(session_id)
        if row is None or row.revoked_at is not None:
            return None
        return row

    async def revoke(self, session_id: str, *, replaced_by: str | None = None) -> None:
        row = self.rows.get(session_id)
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            row.replaced_by = replaced_by

    async def revoke_all_for_user(self, user_id: str) -> None:
        self.revoked.append(user_id)
        now = datetime.now(timezone.utc)
        for row in self.rows.values():
            if row.user_id == user_id and row.revoked_at is None:
                row.revoked_at = now


class AuthArchiveTests(unittest.TestCase):
    def _account(self, *, archived_at=None, is_active: bool = True) -> tuple[UserRepository, dict, _Sessions]:
        user_id = ObjectId()
        document = {
            "_id": user_id,
            "email": "ada@example.com",
            "full_name": "Ada Lovelace",
            "hashed_password": "hashed",
            "is_active": is_active,
            "role": "user",
            "created_at": NOW,
        }
        if archived_at is not None:
            document["archived_at"] = archived_at
        return UserRepository(_Database([document])), document, _Sessions()

    def test_archived_user_cannot_log_in_refresh_or_use_an_old_access_token(self) -> None:
        users, document, sessions = self._account()
        auth = AuthService(users, sessions)
        with patch("app.services.auth_service.verify_password", return_value=True):
            issued = _run(auth.login(LoginRequest(email="ada@example.com", password="password1")))
        document["archived_at"] = NOW
        document["is_active"] = False
        with self.assertRaises(UnauthorizedError):
            _run(auth.login(LoginRequest(email="ada@example.com", password="password1")))
        with self.assertRaises(UnauthorizedError):
            _run(auth.refresh(issued.refresh_token))
        self.assertIn(str(document["_id"]), sessions.revoked)
        fresh_sessions = _Sessions()
        fresh_sessions.rows["sess-1"] = AuthSession(
            id="sess-1",
            user_id=str(document["_id"]),
            token_hash=hash_refresh_token("unused"),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            revoked_at=None,
            replaced_by=None,
            created_at=NOW,
        )
        token = create_access_token(subject=str(document["_id"]), session_id="sess-1")

        class _Creds:
            scheme = "bearer"
            credentials = token

        with self.assertRaises(UnauthorizedError):
            _run(get_current_user(credentials=_Creds(), users=users, sessions=fresh_sessions))

    def test_archive_revokes_sessions_and_purge_can_still_load_the_row(self) -> None:
        users, document, sessions = self._account()
        service = UserService(users, sessions=sessions)
        user_id = str(document["_id"])
        _run(service.delete_user(user_id, archived_by="admin-1", actor_role="admin", actor_id="admin-1"))
        self.assertEqual(sessions.revoked, [user_id])
        self.assertIsNone(_run(users.get_by_id(user_id)))
        archived = _run(users.get_including_archived(user_id))
        self.assertEqual(archived.archived_by, "admin-1")
        self.assertFalse(archived.is_active)
        _run(service.purge_user(user_id, actor_role="super_admin", actor_id="root"))
        self.assertIsNone(_run(users.get_including_archived(user_id)))


class DashboardArchiveTests(unittest.TestCase):
    def test_archived_instructor_is_not_shown_as_an_active_mentor(self) -> None:
        student_user_id = ObjectId()
        instructor_user_id = ObjectId()
        instructor_id = ObjectId()
        course_id = ObjectId()
        users = UserRepository(
            _Database(
                [
                    {
                        "_id": instructor_user_id,
                        "email": "hidden@example.com",
                        "full_name": "Hidden Instructor",
                        "hashed_password": "hashed",
                        "is_active": False,
                        "role": "user",
                        "created_at": NOW,
                        "archived_at": NOW,
                    }
                ]
            )
        )
        instructors = InstructorRepository(
            _Database(
                [
                    {
                        "_id": instructor_id,
                        "user_id": instructor_user_id,
                        "bio": "Hidden",
                        "specialization": "Secret",
                        "is_active": False,
                        "created_at": NOW,
                        "updated_at": NOW,
                        "archived_at": NOW,
                    }
                ]
            )
        )
        current = User(
            id=str(student_user_id),
            email="student@example.com",
            full_name="Student",
            hashed_password="hashed",
            is_active=True,
            role="user",
            created_at=NOW,
        )

        class _Students:
            async def get_by_user_id(self, user_id: str):
                return SimpleNamespace(id="student-1")

        class _Enrollments:
            async def page_current_for_student(self, student_id: str, *, skip: int = 0, limit: int = 100):
                return [
                    SimpleNamespace(
                        id="enroll-1",
                        verified_by_admin=True,
                        course_id=str(course_id),
                        progress_percentage=0,
                        enrollment_date=NOW,
                    )
                ], 1

        class _Courses:
            async def load_by_ids(self, ids, *, include_archived: bool = False):
                return {
                    requested_id: SimpleNamespace(
                        id=requested_id,
                        title="Speech",
                        instructor_id=str(instructor_id),
                    )
                    for requested_id in ids
                }

        class _Materials:
            async def published_for_courses(self, course_ids):
                return {}

        payload = _run(
            get_student_dashboard(
                current,
                _Enrollments(),
                _Students(),
                _Courses(),
                instructors,
                users,
                _Materials(),
            )
        )
        self.assertEqual(payload["mentors"], [])
        self.assertEqual(payload["enrollments"][0]["instructor_name"], "Instructor")
        self.assertNotIn("Hidden Instructor", str(payload))
        self.assertNotIn("Secret", str(payload))


if __name__ == "__main__":
    unittest.main()
