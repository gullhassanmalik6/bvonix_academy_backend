"""Sensitive operations write real audit records through the audit service."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.assignment import AssignmentSubmission
from app.models.attendance import Attendance
from app.models.audit_log import AuditLog
from app.models.enrollment import Enrollment
from app.models.payment import Payment
from app.models.scholarship import Scholarship
from app.models.user import User
from app.routes.admin import admin_cancel_enrollment, admin_list_audit_logs
from app.schemas.attendance import AttendanceUpdate
from app.schemas.payment import PaymentUpdate
from app.schemas.user import UserUpdate
from app.services.assignment_service import AssignmentService
from app.services.attendance_service import AttendanceService
from app.services.audit_context import set_audit_actor
from app.services.audit_service import AuditService, snapshot
from app.services.payment_service import PaymentService
from app.services.scholarship_service import ScholarshipService
from app.services.user_service import UserService
from app.utils.exceptions import NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _admin() -> User:
    return User(
        id="admin-1",
        email="admin@example.com",
        full_name="Admin",
        hashed_password="hashed-secret",
        is_active=True,
        role="admin",
        created_at=_now(),
    )


class MemoryAuditRepository:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def create(self, document: dict) -> AuditLog:
        stored = dict(document)
        stored["_id"] = f"audit-{len(self.documents) + 1}"
        self.documents.append(stored)
        return AuditLog(
            id=stored["_id"],
            actor_id=stored.get("actor_id"),
            actor_role=stored.get("actor_role"),
            action=stored["action"],
            entity_type=stored["entity_type"],
            entity_id=stored.get("entity_id"),
            previous_state=stored.get("previous_state"),
            new_state=stored.get("new_state"),
            context=stored.get("context") or {},
            created_at=stored["created_at"],
        )


def _audit() -> tuple[AuditService, MemoryAuditRepository]:
    repo = MemoryAuditRepository()
    return AuditService(repo), repo


def _payment(status: str = "pending") -> Payment:
    return Payment(
        id="pay-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_id="enroll-1",
        amount=100.0,
        currency="PKR",
        payment_method="cash",
        payment_status=status,
        transaction_id=None,
        invoice_number=None,
        invoice_url=None,
        payment_date=None,
        due_date=None,
        scholarship_discount=0.0,
        notes=None,
        created_by="admin-1",
        created_at=_now(),
        updated_at=_now(),
    )


class _Payments:
    def __init__(self, payment: Payment) -> None:
        self.payment = payment

    async def get_by_id(self, payment_id: str) -> Payment | None:
        return self.payment if payment_id == self.payment.id else None

    async def update(self, payment_id: str, data: dict) -> Payment | None:
        if payment_id != self.payment.id:
            return None
        self.payment = replace(self.payment, **data)
        return self.payment


class _Users:
    def __init__(self, user: User) -> None:
        self.user = user
        self.deleted = False

    async def get_by_id(self, user_id: str) -> User | None:
        if self.deleted or user_id != self.user.id:
            return None
        return self.user

    async def update(self, user_id: str, data: dict) -> User | None:
        if user_id != self.user.id:
            return None
        self.user = replace(self.user, **{key: value for key, value in data.items() if key != "updated_at"})
        return self.user

    async def delete(self, user_id: str) -> bool:
        self.deleted = user_id == self.user.id
        return self.deleted

    async def archive(self, user_id: str, *, archived_by: str | None = None, deactivate: bool = False) -> User | None:
        if self.deleted or user_id != self.user.id:
            return None
        self.user = replace(
            self.user,
            is_active=False if deactivate else self.user.is_active,
            archived_at=_now(),
            archived_by=archived_by,
        )
        return self.user


class _Scholarships:
    def __init__(self, scholarship: Scholarship) -> None:
        self.scholarship = scholarship

    async def get_by_id(self, scholarship_id: str) -> Scholarship | None:
        return self.scholarship if scholarship_id == self.scholarship.id else None

    async def terminate_scholarship(self, scholarship_id: str, reason: str, terminated_by: str | None) -> Scholarship:
        self.scholarship = replace(
            self.scholarship,
            status="terminated",
            termination_reason=reason,
            terminated_by=terminated_by,
            terminated_at=_now(),
        )
        return self.scholarship


class _AttendanceRepo:
    def __init__(self, attendance: Attendance) -> None:
        self.attendance = attendance

    async def get_by_id(self, attendance_id: str) -> Attendance | None:
        return self.attendance if attendance_id == self.attendance.id else None

    async def update(self, attendance_id: str, data: dict) -> Attendance | None:
        self.attendance = replace(
            self.attendance,
            status=data.get("status", self.attendance.status),
            notes=data.get("notes", self.attendance.notes),
        )
        return self.attendance


class _Submissions:
    def __init__(self, submission: AssignmentSubmission) -> None:
        self.submission = submission

    async def get_by_id(self, submission_id: str) -> AssignmentSubmission | None:
        return self.submission if submission_id == self.submission.id else None

    async def update(self, submission_id: str, data: dict) -> AssignmentSubmission:
        self.submission = replace(
            self.submission,
            marks_obtained=data["marks_obtained"],
            feedback=data["feedback"],
            graded_by=data["graded_by"],
            graded_at=data["graded_at"],
            status=data["status"],
            updated_at=data["updated_at"],
        )
        return self.submission


class _Enrollments:
    def __init__(self, enrollment: Enrollment) -> None:
        self.enrollment = enrollment

    async def get_by_id(self, enrollment_id: str) -> Enrollment | None:
        return self.enrollment if enrollment_id == self.enrollment.id else None

    async def update(self, enrollment_id: str, data: dict) -> Enrollment:
        if enrollment_id != self.enrollment.id:
            return None
        self.enrollment = replace(
            self.enrollment,
            status=data.get("status", self.enrollment.status),
            review_state=data.get("review_state", self.enrollment.review_state),
            updated_at=data.get("updated_at", self.enrollment.updated_at),
            audit_pending=data["audit_pending"] if "audit_pending" in data else self.enrollment.audit_pending,
        )
        return self.enrollment

    async def registration_course_ids(self, student_id: str) -> list[str]:
        if student_id != self.enrollment.student_id or self.enrollment.status == "cancelled":
            return []
        return [self.enrollment.course_id]


class _StudentRepo:
    def __init__(self) -> None:
        self.courses = ["course-1"]

    async def get_by_id(self, student_id: str):
        return SimpleNamespace(id=student_id, enrolled_courses=list(self.courses))

    async def set_enrolled_courses(self, student_id: str, course_ids: list[str], *, include_archived: bool = False):
        del include_archived
        self.courses = list(course_ids)
        return SimpleNamespace(id=student_id, enrolled_courses=list(self.courses))


def _scholarship() -> Scholarship:
    return Scholarship(
        id="sch-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_id="enroll-1",
        scholarship_type="merit",
        amount=50.0,
        status="active",
        start_date=_now(),
        end_date=None,
        termination_reason=None,
        terminated_at=None,
        terminated_by=None,
        max_absences_per_month=3,
        current_month_absences=0,
        current_month_start=_now(),
        notes=None,
        created_at=_now(),
        updated_at=_now(),
    )


def _attendance() -> Attendance:
    return Attendance(
        id="att-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_id="enroll-1",
        date=_now(),
        status="present",
        marked_by="admin-1",
        notes=None,
        absence_reason=None,
        absence_reason_submitted_at=None,
        is_excused=False,
        created_at=_now(),
        updated_at=_now(),
    )


def _submission() -> AssignmentSubmission:
    return AssignmentSubmission(
        id="sub-1",
        assignment_id="assign-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_id="enroll-1",
        submission_text="answer",
        file_urls=[],
        submitted_at=_now(),
        status="submitted",
        marks_obtained=None,
        feedback=None,
        graded_by=None,
        graded_at=None,
        created_at=_now(),
        updated_at=_now(),
    )


def _enrollment() -> Enrollment:
    return Enrollment(
        id="enroll-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_date=_now(),
        status="active",
        payment_status="paid",
        payment_date=_now(),
        completion_date=None,
        progress_percentage=0.0,
        class_type="online",
        phone_number=None,
        address=None,
        emergency_contact_name=None,
        emergency_contact_phone=None,
        father_guardian_name=None,
        date_of_birth=None,
        gender=None,
        profile_image_url=None,
        enrollment_card_number=None,
        enrollment_card_url=None,
        payment_receipt_url=None,
        verified_by_admin=True,
        verified_at=_now(),
        verified_by="admin-1",
        created_at=_now(),
        updated_at=_now(),
    )


class AuditLogTests(unittest.TestCase):
    def setUp(self) -> None:
        set_audit_actor(_admin())

    def test_snapshot_redacts_secrets(self) -> None:
        recorded = snapshot(
            {
                "email": "student@example.com",
                "password": "plain-secret",
                "hashed_password": "hash",
                "access_token": "jwt",
                "authorization": "Bearer jwt",
            }
        )
        self.assertEqual(recorded["email"], "student@example.com")
        self.assertEqual(recorded["password"], "[redacted]")
        self.assertEqual(recorded["hashed_password"], "[redacted]")
        self.assertEqual(recorded["access_token"], "[redacted]")
        self.assertEqual(recorded["authorization"], "[redacted]")

    def test_payment_approval_creates_an_audit_record(self) -> None:
        audit, repo = _audit()
        service = PaymentService(_Payments(_payment("pending")), audit=audit)
        updated = asyncio.run(service.update_payment("pay-1", PaymentUpdate(payment_status="completed"), actor_role="admin"))
        self.assertEqual(updated.payment_status, "completed")
        self.assertEqual(len(repo.documents), 1)
        record = repo.documents[0]
        self.assertEqual(record["action"], "payment.approve")
        self.assertEqual(record["actor_id"], "admin-1")
        self.assertEqual(record["actor_role"], "admin")
        self.assertEqual(record["entity_type"], "payment")
        self.assertEqual(record["entity_id"], "pay-1")
        self.assertEqual(record["previous_state"]["payment_status"], "pending")
        self.assertEqual(record["new_state"]["payment_status"], "completed")

    def test_failed_payment_update_does_not_write_an_audit_record(self) -> None:
        audit, repo = _audit()

        class _Missing(_Payments):
            async def update(self, payment_id: str, data: dict) -> None:
                return None

        service = PaymentService(_Missing(_payment()), audit=audit)
        with self.assertRaises(NotFoundError):
            asyncio.run(service.update_payment("pay-1", PaymentUpdate(payment_status="failed"), actor_role="admin"))
        self.assertEqual(repo.documents, [])

    def test_scholarship_termination_creates_an_audit_record(self) -> None:
        audit, repo = _audit()
        service = ScholarshipService(_Scholarships(_scholarship()), audit=audit)
        terminated = asyncio.run(service.terminate_scholarship("sch-1", "attendance", "admin-1"))
        self.assertEqual(terminated.status, "terminated")
        self.assertEqual(len(repo.documents), 1)
        record = repo.documents[0]
        self.assertEqual(record["action"], "scholarship.terminate")
        self.assertEqual(record["previous_state"]["status"], "active")
        self.assertEqual(record["new_state"]["status"], "terminated")
        self.assertEqual(record["actor_id"], "admin-1")

    def test_attendance_change_creates_an_audit_record(self) -> None:
        audit, repo = _audit()
        service = AttendanceService(_AttendanceRepo(_attendance()), audit=audit)
        updated = asyncio.run(service.update_attendance("att-1", AttendanceUpdate(status="absent")))
        self.assertEqual(updated.status, "absent")
        self.assertEqual(repo.documents[0]["action"], "attendance.update")
        self.assertEqual(repo.documents[0]["previous_state"]["status"], "present")
        self.assertEqual(repo.documents[0]["new_state"]["status"], "absent")

    def test_grade_change_creates_an_audit_record(self) -> None:
        audit, repo = _audit()
        service = AssignmentService(object(), _Submissions(_submission()), audit=audit)
        graded = asyncio.run(service.grade_submission("sub-1", 18, "Good", "admin-1"))
        self.assertEqual(graded.marks_obtained, 18)
        record = repo.documents[0]
        self.assertEqual(record["action"], "grade.update")
        self.assertEqual(record["entity_type"], "assignment_submission")
        self.assertIsNone(record["previous_state"]["marks_obtained"])
        self.assertEqual(record["new_state"]["marks_obtained"], 18)
        self.assertEqual(record["new_state"]["graded_by"], "admin-1")

    def test_permission_change_and_delete_create_audit_records(self) -> None:
        audit, repo = _audit()
        student = User(
            id="user-2",
            email="student@example.com",
            full_name="Student",
            hashed_password="stored-hash",
            is_active=True,
            role="user",
            created_at=_now(),
        )
        users = _Users(student)
        service = UserService(users, audit=audit)
        asyncio.run(service.update_user("user-2", UserUpdate(role="admin")))
        asyncio.run(
            service.delete_user(
                "user-2",
                archived_by="admin-1",
                actor_role="admin",
                actor_id="admin-1",
            )
        )
        self.assertEqual([item["action"] for item in repo.documents], ["user.permission_change", "user.delete"])
        self.assertEqual(repo.documents[0]["previous_state"]["role"], "user")
        self.assertEqual(repo.documents[0]["new_state"]["role"], "admin")
        self.assertEqual(repo.documents[1]["previous_state"]["hashed_password"], "[redacted]")
        self.assertNotIn("stored-hash", str(repo.documents[1]))

    def test_enrollment_cancellation_creates_an_audit_record(self) -> None:
        audit, repo = _audit()
        updated = asyncio.run(
            admin_cancel_enrollment(
                "enroll-1",
                admin_user=_admin(),
                enrollment_repo=_Enrollments(_enrollment()),
                student_repo=_StudentRepo(),
                audit=audit,
            )
        )
        self.assertEqual(updated.status, "cancelled")
        record = repo.documents[0]
        self.assertEqual(record["action"], "enrollment.cancel")
        self.assertEqual(record["entity_type"], "enrollment")
        self.assertEqual(record["entity_id"], "enroll-1")
        self.assertEqual(record["previous_state"]["status"], "active")
        self.assertEqual(record["new_state"]["status"], "cancelled")
        self.assertEqual(record["actor_id"], "admin-1")

    def test_audit_list_redacts_secrets_again(self) -> None:
        created = _now()
        stored = AuditLog(
            id="audit-1",
            actor_id="admin-1",
            actor_role="admin",
            action="user.permission_change",
            entity_type="user",
            entity_id="user-2",
            previous_state={"role": "user", "hashed_password": "stored-hash"},
            new_state={"role": "admin", "access_token": "secret-token"},
            context={"authorization": "Bearer secret"},
            created_at=created,
        )

        class _Logs:
            async def list_recent(self, *, skip: int, limit: int, action=None, entity_type=None, q=None):
                self.skip = skip
                self.limit = limit
                return [stored], 1

        page = asyncio.run(
            admin_list_audit_logs(skip=0, limit=20, admin_user=_admin(), audits=_Logs())
        )
        item = page.items[0]
        self.assertEqual(page.total, 1)
        self.assertEqual(item.actor_id, "admin-1")
        self.assertEqual(item.action, "user.permission_change")
        self.assertEqual(item.previous_state["role"], "user")
        self.assertEqual(item.previous_state["hashed_password"], "[redacted]")
        self.assertEqual(item.new_state["access_token"], "[redacted]")
        self.assertEqual(item.context["authorization"], "[redacted]")
        self.assertNotIn("stored-hash", str(item.previous_state))
        self.assertNotIn("secret-token", str(item.new_state))


if __name__ == "__main__":
    unittest.main()
