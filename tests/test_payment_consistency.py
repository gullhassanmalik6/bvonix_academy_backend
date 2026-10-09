"""Enrollment payment fields and the payments ledger stay independent and authorized."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId

from app.core.admin import get_payment_admin
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.admin import admin_verify_enrollment
from app.routes.lms import get_my_payments, upload_payment_receipt
from app.schemas.enrollment import PaymentReceiptUpload
from app.schemas.payment import PaymentUpdate
from app.services.audit_service import snapshot
from app.services.payment_consistency import payment_consistency_report
from app.services.payment_service import PaymentService
from app.utils.exceptions import ConflictError, ForbiddenError
from scripts.payment_consistency_report import main, refuse_write

try:
    from tests.test_pagination import NOW, _Database, _run
except ImportError:
    from test_pagination import NOW, _Database, _run


RECEIPT = "/uploads/payment_receipts/private-receipt.pdf"
EMAIL = "ada.private@example.com"


def _user(user_id: ObjectId, role: str = "user") -> User:
    return User(
        id=str(user_id),
        email=EMAIL,
        full_name="Ada",
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=NOW,
    )


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(self, **kwargs):
        self.records.append(kwargs)
        return SimpleNamespace(id="audit-1")


class _Notify:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def create_enrollment_verified_notification(self, **kwargs) -> None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("notification failed")


class PaymentConsistencyTests(unittest.TestCase):
    def _world(self):
        user_id, other_user = ObjectId(), ObjectId()
        student_id, other_student = ObjectId(), ObjectId()
        course_id, enrollment_id = ObjectId(), ObjectId()
        payment_id = ObjectId()
        db = _Database()
        db.add("users", [{
            "_id": user_id,
            "email": EMAIL,
            "full_name": "Ada",
            "hashed_password": "hashed",
            "is_active": True,
            "role": "user",
            "created_at": NOW,
        }])
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
        db.add("courses", [{
            "_id": course_id,
            "title": "Speech",
            "description": "Speech description",
            "instructor_id": ObjectId(),
            "duration_hours": 4,
            "price": 1500,
            "is_published": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("enrollments", [{
            "_id": enrollment_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_date": NOW,
            "status": "pending",
            "payment_status": "pending",
            "verified_by_admin": False,
            "class_type": "online",
            "payment_receipt_url": RECEIPT,
            "phone_number": "03001112233",
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("payments", [{
            "_id": payment_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_id": enrollment_id,
            "amount": 1500.0,
            "currency": "PKR",
            "payment_method": "bank_transfer",
            "payment_status": "pending",
            "transaction_id": "gateway-secret",
            "invoice_url": RECEIPT,
            "scholarship_discount": 0.0,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        return db, {
            "user_id": user_id,
            "other_user": other_user,
            "student_id": student_id,
            "other_student": other_student,
            "course_id": course_id,
            "enrollment_id": enrollment_id,
            "payment_id": payment_id,
        }

    def _verify(self, db, ids, notify):
        audit = _Audit()

        def _skip_card(self, enrollment, student, course):
            raise RuntimeError("card generation skipped")

        with patch("app.services.enrollment_card_service.EnrollmentCardService.generate_enrollment_card", _skip_card):
            with self.assertLogs("app.routes.admin", level="INFO") as captured:
                updated = _run(admin_verify_enrollment(
                    str(ids["enrollment_id"]),
                    _user(ObjectId(), "admin"),
                    EnrollmentRepository(db),
                    CourseRepository(db),
                    UserRepository(db),
                    StudentRepository(db),
                    notify,
                    audit,
                ))
        logged = "\n".join(captured.output)
        self.assertNotIn(RECEIPT, logged)
        self.assertNotIn(EMAIL, logged)
        return updated, audit

    def test_verification_does_not_fabricate_or_rewrite_a_ledger_payment(self) -> None:
        db, ids = self._world()
        updated, audit = self._verify(db, ids, _Notify())
        self.assertTrue(updated.verified_by_admin)
        self.assertEqual(updated.payment_status, "paid")
        self.assertEqual(len(db["payments"].documents), 1)
        payment = db["payments"].documents[0]
        self.assertEqual(payment["amount"], 1500.0)
        self.assertEqual(payment["payment_method"], "bank_transfer")
        self.assertEqual(payment["payment_status"], "pending")
        recorded = str(audit.records)
        self.assertNotIn(RECEIPT, recorded)
        self.assertNotIn("gateway-secret", recorded)
        self.assertIn("paid", recorded)

        db["payments"].documents.clear()
        db["enrollments"].documents[0]["verified_by_admin"] = False
        db["enrollments"].documents[0]["status"] = "pending"
        db["enrollments"].documents[0]["payment_status"] = "pending"
        db["enrollments"].documents[0]["review_state"] = None
        again, _audit = self._verify(db, ids, _Notify(fail=True))
        self.assertTrue(again.verified_by_admin)
        self.assertEqual(db["payments"].documents, [])

    def test_receipt_upload_does_not_complete_a_ledger_payment(self) -> None:
        db, ids = self._world()
        db["enrollments"].documents[0]["payment_receipt_url"] = None
        updated = _run(upload_payment_receipt(
            str(ids["enrollment_id"]),
            PaymentReceiptUpload(receipt_url=RECEIPT),
            _user(ids["user_id"]),
            EnrollmentRepository(db),
            StudentRepository(db),
            _Audit(),
        ))
        self.assertEqual(updated.payment_receipt_url, RECEIPT)
        self.assertEqual(updated.payment_status, "pending")
        self.assertFalse(updated.verified_by_admin)
        self.assertEqual(db["payments"].documents[0]["payment_status"], "pending")
        with self.assertRaises(ForbiddenError):
            _run(upload_payment_receipt(
                str(ids["enrollment_id"]),
                PaymentReceiptUpload(receipt_url=RECEIPT),
                _user(ids["other_user"]),
                EnrollmentRepository(db),
                StudentRepository(db),
                _Audit(),
            ))

    def test_students_read_only_their_payments_and_cannot_change_status(self) -> None:
        db, ids = self._world()
        other_payment = ObjectId()
        db["payments"].documents.append({
            "_id": other_payment,
            "student_id": ids["other_student"],
            "course_id": ids["course_id"],
            "enrollment_id": ObjectId(),
            "amount": 50.0,
            "currency": "PKR",
            "payment_method": "cash",
            "payment_status": "completed",
            "scholarship_discount": 0.0,
            "created_at": NOW,
            "updated_at": NOW,
        })
        db["enrollments"].documents[0]["status"] = "active"
        db["enrollments"].documents[0]["verified_by_admin"] = True
        page = _run(get_my_payments(
            0,
            100,
            (SimpleNamespace(id=str(ids["student_id"])), None),
            PaymentService(PaymentRepository(db)),
        ))
        self.assertEqual([item.id for item in page.items], [str(ids["payment_id"])])
        service = PaymentService(PaymentRepository(db))
        with self.assertRaises(ForbiddenError):
            _run(get_payment_admin(_user(ids["user_id"])))
        with self.assertRaises(ForbiddenError):
            _run(service.update_payment(
                str(ids["payment_id"]),
                PaymentUpdate(payment_status="completed"),
                actor_role="user",
            ))
        with self.assertRaises(ForbiddenError):
            _run(service.update_payment(
                str(ids["payment_id"]),
                PaymentUpdate(payment_status="refunded"),
                actor_role="academic_manager",
            ))
        self.assertEqual(db["payments"].documents[0]["payment_status"], "pending")
        self.assertEqual(db["payments"].documents[0]["amount"], 1500.0)

    def test_refund_and_invalid_transition_follow_the_ledger_rules(self) -> None:
        db, ids = self._world()
        db["payments"].documents[0]["payment_status"] = "completed"
        service = PaymentService(PaymentRepository(db))
        with self.assertRaises(ConflictError):
            _run(service.update_payment(
                str(ids["payment_id"]),
                PaymentUpdate(payment_status="pending"),
                actor_role="admin",
            ))
        refunded = _run(service.update_payment(
            str(ids["payment_id"]),
            PaymentUpdate(payment_status="refunded"),
            actor_role="super_admin",
        ))
        self.assertEqual(refunded.payment_status, "refunded")
        self.assertEqual(refunded.amount, 1500.0)
        self.assertEqual(refunded.payment_method, "bank_transfer")
        self.assertEqual(db["enrollments"].documents[0]["payment_status"], "pending")
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")

    def test_report_classifies_disagreements_without_changing_records(self) -> None:
        student_id, course_id = ObjectId(), ObjectId()
        paid_id, pending_id, refunded_enrollment = ObjectId(), ObjectId(), ObjectId()
        missing_enrollment = ObjectId()
        db = _Database()
        db.add("enrollments", [
            {"_id": paid_id, "student_id": student_id, "course_id": course_id, "payment_status": "paid", "status": "active"},
            {"_id": pending_id, "student_id": student_id, "course_id": course_id, "payment_status": "pending", "status": "pending"},
            {"_id": refunded_enrollment, "student_id": student_id, "course_id": course_id, "payment_status": "refunded", "status": "active"},
        ])
        db.add("payments", [
            {"_id": ObjectId(), "student_id": student_id, "enrollment_id": paid_id, "amount": 10, "payment_method": "cash", "payment_status": "pending"},
            {"_id": ObjectId(), "student_id": student_id, "enrollment_id": paid_id, "amount": 20, "payment_method": "card", "payment_status": "failed"},
            {"_id": ObjectId(), "student_id": student_id, "enrollment_id": pending_id, "amount": 30, "payment_method": "cash", "payment_status": "completed"},
            {"_id": ObjectId(), "student_id": student_id, "enrollment_id": refunded_enrollment, "amount": 40, "payment_method": "cash", "payment_status": "refunded"},
            {"_id": ObjectId(), "student_id": student_id, "enrollment_id": missing_enrollment, "amount": 50, "payment_method": "cash", "payment_status": "completed"},
            {"_id": ObjectId(), "student_id": student_id, "enrollment_id": None, "amount": 60, "payment_method": "cash", "payment_status": "pending"},
            {"_id": ObjectId(), "student_id": "not-a-student", "enrollment_id": "not-an-enrollment", "amount": 70, "payment_method": "cash", "payment_status": "pending", "phone_number": "03009998877"},
        ])
        before = [dict(item) for item in db["payments"].documents]
        report = _run(payment_consistency_report(db))
        self.assertEqual(db["payments"].documents, before)
        counts = report["counts"]
        self.assertEqual(counts["multiple_payments_for_enrollment"], 1)
        self.assertIn(str(paid_id), report["ids"]["multiple_payments_for_enrollment"])
        self.assertEqual(counts["paid_enrollment_pending_or_missing_ledger"], 1)
        self.assertEqual(counts["completed_ledger_unpaid_enrollment"], 1)
        self.assertEqual(counts["payment_without_enrollment"], 1)
        self.assertEqual(counts["refunded_ledger_inconsistent_enrollment"], 0)
        self.assertEqual(counts["invalid_relationship_id"], 1)
        self.assertEqual(counts["enrollment_without_payment"], 0)
        rendered = str(report)
        self.assertNotIn("03009998877", rendered)
        self.assertNotIn("not-an-enrollment", rendered)
        self.assertEqual(db["payments"].documents[0]["amount"], 10)
        self.assertEqual(db["payments"].documents[1]["amount"], 20)

    def test_snapshot_redacts_receipt_and_transaction_details(self) -> None:
        recorded = snapshot({
            "payment_status": "paid",
            "amount": 1500.0,
            "payment_method": "bank_transfer",
            "payment_receipt_url": RECEIPT,
            "invoice_url": RECEIPT,
            "transaction_id": "gateway-secret",
        })
        self.assertEqual(recorded["payment_status"], "paid")
        self.assertEqual(recorded["amount"], 1500.0)
        self.assertEqual(recorded["payment_receipt_url"], "[redacted]")
        self.assertEqual(recorded["invoice_url"], "[redacted]")
        self.assertEqual(recorded["transaction_id"], "[redacted]")

    def test_report_script_does_not_select_or_write_a_database(self) -> None:
        self.assertEqual(main([]), 2)
        with self.assertRaises(SystemExit) as raised:
            refuse_write("bvonix_academy")
        self.assertIn("read-only", str(raised.exception))
        with self.assertRaises(SystemExit):
            main(["--write", "--uri", "mongodb://localhost:27017", "--database", "bvonix_academy"])
