"""Soft-delete keeps sensitive rows, hides them from active use, and audits the action."""

from __future__ import annotations

import asyncio
import inspect
import unittest
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path

from app.core.permissions import assert_can_purge
from app.models.attendance import Attendance
from app.models.instructor import Instructor
from app.models.payment import Payment
from app.models.scholarship import Scholarship
from app.models.student import Student
from app.models.user import User
from app.repositories.archival import archive_values, record_is_active, with_active
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.certificate_repository import CertificateRepository
from app.services.attendance_service import AttendanceService
from app.services.audit_service import AuditService
from app.services.audit_context import set_audit_actor
from app.services.instructor_service import InstructorService
from app.services.payment_service import PaymentService
from app.services.scholarship_service import ScholarshipService
from app.services.student_service import StudentService
from app.services.user_service import UserService
from app.utils.exceptions import ForbiddenError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(user_id: str, name: str, role: str = "user") -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.com",
        full_name=name,
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=_now(),
    )


class MemoryAudit:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def create(self, document: dict) -> dict:
        self.documents.append(document)
        return document


class MemoryRepo:
    """In-memory stand-in that applies the same active-record rule as Mongo list/count."""

    def __init__(self, records: list) -> None:
        self.records = list(records)

    def _stored(self, record_id: str):
        return next((item for item in self.records if item.id == record_id), None)

    async def get_by_id(self, record_id: str):
        return self._stored(record_id)

    async def list(self, skip: int = 0, limit: int = 100):
        active = [item for item in self.records if record_is_active(item)]
        return active[skip : skip + limit]

    async def list_page(self, *, skip: int = 0, limit: int = 100, q: str | None = None, sort: str | None = None):
        del q, sort
        active = [item for item in self.records if record_is_active(item)]
        return active[skip : skip + limit], len(active)

    async def count(self, filter: dict | None = None) -> int:
        del filter
        return len([item for item in self.records if record_is_active(item)])

    async def archive(self, record_id: str, *, archived_by: str | None = None, deactivate: bool = False):
        current = self._stored(record_id)
        if current is None:
            return None
        allowed = {item.name for item in fields(current)}
        values = {
            key: value
            for key, value in archive_values(archived_by=archived_by, deactivate=deactivate).items()
            if key in allowed
        }
        updated = replace(current, **values)
        self.records = [updated if item.id == record_id else item for item in self.records]
        return updated

    async def delete(self, record_id: str) -> bool:
        before = len(self.records)
        self.records = [item for item in self.records if item.id != record_id]
        return len(self.records) != before

    async def search(self, query: str) -> list:
        needle = query.lower()
        matches = []
        for item in await self.list():
            if not record_is_active(item):
                continue
            name = (getattr(item, "full_name", None) or getattr(item, "email", "") or "").lower()
            email = (getattr(item, "email", "") or "").lower()
            if needle in name or needle in email:
                matches.append(item)
        return matches


class Sessions:
    def __init__(self) -> None:
        self.revoked: list[str] = []

    async def revoke_all_for_user(self, user_id: str) -> None:
        self.revoked.append(user_id)


class ArchivalTests(unittest.TestCase):
    def setUp(self) -> None:
        set_audit_actor(_user("admin-1", "Admin", role="admin"))

    def _audit(self) -> tuple[AuditService, MemoryAudit]:
        repo = MemoryAudit()
        return AuditService(repo), repo

    def test_existing_rows_without_archived_at_stay_active(self) -> None:
        self.assertTrue(record_is_active({}))
        self.assertTrue(record_is_active({"archived_at": None}))
        self.assertFalse(record_is_active({"archived_at": _now()}))
        self.assertEqual(
            with_active({"status": "present"}),
            {"status": "present", "archived_at": None},
        )

    def test_dashboard_count_queries_exclude_archived_rows(self) -> None:
        self.assertIn("with_active()", inspect.getsource(CertificateRepository.count_issued))
        self.assertIn("with_active()", inspect.getsource(AttendanceRepository.count_statuses))

    def test_http_routes_do_not_expose_permanent_deletion(self) -> None:
        routes = Path(__file__).resolve().parents[1] / "app" / "routes"
        text = "\n".join(path.read_text(encoding="utf-8") for path in routes.glob("*.py"))
        self.assertNotIn("purge_", text)

    def test_user_archive_hides_the_row_and_records_who_and_when(self) -> None:
        audit, repo = self._audit()
        sessions = Sessions()
        users = MemoryRepo([_user("user-2", "Ada Lovelace"), _user("user-3", "Grace Hopper")])
        service = UserService(users, audit=audit, sessions=sessions)
        before = _now()
        asyncio.run(
            service.delete_user(
                "user-2",
                archived_by="admin-1",
                actor_role="admin",
                actor_id="admin-1",
            )
        )
        stored = asyncio.run(users.get_by_id("user-2"))
        self.assertIsNotNone(stored)
        self.assertFalse(stored.is_active)
        self.assertEqual(stored.archived_by, "admin-1")
        self.assertIsNotNone(stored.archived_at)
        self.assertGreaterEqual(stored.archived_at, before)
        self.assertEqual(sessions.revoked, ["user-2"])
        listed, total = asyncio.run(service.list_users())
        self.assertEqual([item.id for item in listed], ["user-3"])
        self.assertEqual(total, 1)
        self.assertEqual(asyncio.run(users.search("ada")), [])
        self.assertEqual([item.id for item in asyncio.run(users.search("grace"))], ["user-3"])
        record = repo.documents[-1]
        self.assertEqual(record["action"], "user.delete")
        self.assertEqual(record["entity_type"], "user")
        self.assertEqual(record["entity_id"], "user-2")
        self.assertEqual(record["new_state"]["archived_by"], "admin-1")
        self.assertIsNotNone(record["new_state"]["archived_at"])
        self.assertEqual(record["previous_state"]["hashed_password"], "[redacted]")

    def test_archiving_again_leaves_the_stored_row(self) -> None:
        audit, _repo = self._audit()
        users = MemoryRepo([_user("user-2", "Ada Lovelace")])
        service = UserService(users, audit=audit, sessions=Sessions())
        asyncio.run(
            service.delete_user("user-2", archived_by="admin-1", actor_role="admin", actor_id="admin-1")
        )
        with self.assertRaises(NotFoundError):
            asyncio.run(
                service.delete_user("user-2", archived_by="admin-1", actor_role="admin", actor_id="admin-1")
            )
        self.assertIsNotNone(asyncio.run(users.get_by_id("user-2")))

    def test_ordinary_roles_cannot_archive_another_user(self) -> None:
        users = MemoryRepo([_user("user-2", "Ada Lovelace")])
        service = UserService(users, audit=self._audit()[0], sessions=Sessions())
        for role in ("user", "academic_manager"):
            with self.assertRaises(ForbiddenError):
                asyncio.run(
                    service.delete_user(
                        "user-2",
                        archived_by="actor",
                        actor_role=role,
                        actor_id="actor",
                    )
                )
        stored = asyncio.run(users.get_by_id("user-2"))
        self.assertTrue(record_is_active(stored))
        self.assertEqual(asyncio.run(users.count()), 1)

    def test_account_owner_can_archive_their_own_user(self) -> None:
        users = MemoryRepo([_user("user-2", "Ada Lovelace")])
        service = UserService(users, audit=self._audit()[0], sessions=Sessions())
        asyncio.run(
            service.delete_user(
                "user-2",
                archived_by="user-2",
                actor_role="user",
                actor_id="user-2",
            )
        )
        stored = asyncio.run(users.get_by_id("user-2"))
        self.assertEqual(stored.archived_by, "user-2")
        self.assertEqual(asyncio.run(users.count()), 0)

    def test_permanent_user_deletion_is_super_admin_only_and_audited(self) -> None:
        audit, repo = self._audit()
        sessions = Sessions()
        users = MemoryRepo([_user("user-2", "Ada Lovelace")])
        service = UserService(users, audit=audit, sessions=sessions)
        for role in ("user", "academic_manager", "admin"):
            with self.assertRaises(ForbiddenError):
                asyncio.run(service.purge_user("user-2", actor_role=role, actor_id="actor"))
            self.assertEqual(sessions.revoked, [])
            self.assertIsNotNone(asyncio.run(users.get_by_id("user-2")))
        asyncio.run(service.purge_user("user-2", actor_role="super_admin", actor_id="root"))
        self.assertIsNone(asyncio.run(users.get_by_id("user-2")))
        self.assertEqual(sessions.revoked, ["user-2"])
        self.assertEqual(repo.documents[-1]["action"], "user.purge")
        self.assertEqual(repo.documents[-1]["actor_id"], "root")
        self.assertEqual(repo.documents[-1]["actor_role"], "super_admin")
        with self.assertRaises(ForbiddenError):
            assert_can_purge("admin")
        assert_can_purge("super_admin")

    def test_student_and_instructor_archive_drop_out_of_active_counts(self) -> None:
        audit, repo = self._audit()
        now = _now()
        students = MemoryRepo(
            [
                Student(
                    id="student-1",
                    user_id="user-1",
                    enrollment_date=now,
                    enrolled_courses=[],
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        instructors = MemoryRepo(
            [
                Instructor(
                    id="instructor-1",
                    user_id="user-9",
                    bio=None,
                    specialization="Math",
                    years_of_experience=4,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        student_service = StudentService(students, audit=audit)
        instructor_service = InstructorService(instructors, audit=audit)
        with self.assertRaises(ForbiddenError):
            asyncio.run(
                student_service.delete_student("student-1", archived_by="user-2", actor_role="user")
            )
        asyncio.run(
            student_service.delete_student("student-1", archived_by="admin-1", actor_role="admin")
        )
        asyncio.run(
            instructor_service.delete_instructor(
                "instructor-1",
                archived_by="admin-1",
                actor_role="admin",
            )
        )
        self.assertIsNotNone(asyncio.run(students.get_by_id("student-1")))
        self.assertEqual(asyncio.run(students.count()), 0)
        self.assertEqual(asyncio.run(instructors.count()), 0)
        self.assertEqual(asyncio.run(students.get_by_id("student-1")).archived_by, "admin-1")
        actions = [item["action"] for item in repo.documents]
        self.assertEqual(actions, ["student.delete", "instructor.delete"])
        with self.assertRaises(ForbiddenError):
            asyncio.run(student_service.purge_student("student-1", actor_role="admin", actor_id="admin-1"))
        self.assertIsNotNone(asyncio.run(students.get_by_id("student-1")))

    def test_payment_scholarship_and_attendance_archive(self) -> None:
        audit, repo = self._audit()
        now = _now()
        payments = MemoryRepo(
            [
                Payment(
                    id="pay-1",
                    student_id="student-1",
                    course_id="course-1",
                    enrollment_id="enroll-1",
                    amount=100.0,
                    currency="PKR",
                    payment_method="cash",
                    payment_status="pending",
                    transaction_id=None,
                    invoice_number=None,
                    invoice_url=None,
                    payment_date=None,
                    due_date=None,
                    scholarship_discount=0.0,
                    notes=None,
                    created_by="admin-1",
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        scholarships = MemoryRepo(
            [
                Scholarship(
                    id="sch-1",
                    student_id="student-1",
                    course_id="course-1",
                    enrollment_id="enroll-1",
                    scholarship_type="merit",
                    amount=50.0,
                    status="active",
                    start_date=now,
                    end_date=None,
                    termination_reason=None,
                    terminated_at=None,
                    terminated_by=None,
                    max_absences_per_month=3,
                    current_month_absences=0,
                    current_month_start=now,
                    notes=None,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        attendances = MemoryRepo(
            [
                Attendance(
                    id="att-1",
                    student_id="student-1",
                    course_id="course-1",
                    enrollment_id="enroll-1",
                    date=now,
                    status="present",
                    marked_by="admin-1",
                    notes=None,
                    absence_reason=None,
                    absence_reason_submitted_at=None,
                    is_excused=False,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        payment_service = PaymentService(payments, audit=audit)
        scholarship_service = ScholarshipService(scholarships, audit=audit)
        attendance_service = AttendanceService(attendances, audit=audit)
        with self.assertRaises(ForbiddenError):
            asyncio.run(
                payment_service.delete_payment("pay-1", archived_by="user-2", actor_role="academic_manager")
            )
        asyncio.run(payment_service.delete_payment("pay-1", archived_by="admin-1", actor_role="admin"))
        asyncio.run(
            scholarship_service.delete_scholarship("sch-1", archived_by="admin-1", actor_role="admin")
        )
        asyncio.run(
            attendance_service.delete_attendance("att-1", archived_by="admin-1", actor_role="admin")
        )
        self.assertIsNotNone(asyncio.run(payments.get_by_id("pay-1")))
        self.assertEqual(asyncio.run(payments.count()), 0)
        self.assertEqual(asyncio.run(scholarships.count()), 0)
        self.assertEqual(asyncio.run(attendances.count()), 0)
        self.assertEqual(asyncio.run(attendances.get_by_id("att-1")).archived_by, "admin-1")
        self.assertIsNotNone(asyncio.run(payments.get_by_id("pay-1")).archived_at)
        self.assertEqual(
            [item["action"] for item in repo.documents],
            ["payment.delete", "scholarship.delete", "attendance.delete"],
        )
        with self.assertRaises(ForbiddenError):
            asyncio.run(payment_service.purge_payment("pay-1", actor_role="admin", actor_id="admin-1"))
        asyncio.run(payment_service.purge_payment("pay-1", actor_role="super_admin", actor_id="root"))
        self.assertIsNone(asyncio.run(payments.get_by_id("pay-1")))
        self.assertEqual(repo.documents[-1]["action"], "payment.purge")


if __name__ == "__main__":
    unittest.main()
