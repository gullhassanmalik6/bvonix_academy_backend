"""Payment-review decisions stay in the audit log, without a second history collection."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId

from app.core.admin import get_payment_admin
from app.models.user import User
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.admin import admin_transition_enrollment, admin_verify_enrollment
from app.routes.lms import upload_payment_receipt
from app.schemas.enrollment import EnrollmentTransitionRequest, PaymentReceiptUpload
from app.schemas.payment import PaymentUpdate
from app.services.audit_service import AuditPersistenceError, AuditService, snapshot
from app.services.payment_service import PaymentService
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError

try:
    from tests.test_pagination import NOW, _Database, _run
except ImportError:
    from test_pagination import NOW, _Database, _run


PHONE = "03001112233"
ADDRESS = "12 Private Road"
GUARDIAN = "Guardian Name"
RECEIPT = "/uploads/payment_receipts/private-receipt.pdf"


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


class _Notify:
    async def create_enrollment_verified_notification(self, **kwargs) -> None:
        raise RuntimeError("notification failed")


class ReviewHistoryTests(unittest.TestCase):
    def _world(self):
        user_id, other_user = ObjectId(), ObjectId()
        student_id, other_student = ObjectId(), ObjectId()
        course_id = ObjectId()
        enrollment_id, other_enrollment = ObjectId(), ObjectId()
        db = _Database()
        db.add("users", [{
            "_id": user_id,
            "email": "ada@example.com",
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
            "price": 0,
            "is_published": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("enrollments", [
            {
                "_id": enrollment_id,
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_date": NOW,
                "status": "pending",
                "payment_status": "pending",
                "verified_by_admin": False,
                "class_type": "online",
                "payment_receipt_url": RECEIPT,
                "phone_number": PHONE,
                "address": ADDRESS,
                "father_guardian_name": GUARDIAN,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "_id": other_enrollment,
                "student_id": other_student,
                "course_id": course_id,
                "enrollment_date": NOW,
                "status": "pending",
                "payment_status": "pending",
                "verified_by_admin": False,
                "class_type": "online",
                "created_at": NOW,
                "updated_at": NOW,
            },
        ])
        db.add("payments", [])
        db.add("audit_logs", [])
        return db, {
            "user_id": user_id,
            "other_user": other_user,
            "enrollment_id": enrollment_id,
            "other_enrollment": other_enrollment,
        }

    def _audit(self, db):
        return AuditService(AuditLogRepository(db))

    def test_review_decisions_record_actor_and_states_without_private_fields(self) -> None:
        db, ids = self._world()
        admin = _account(ObjectId(), "admin")
        audit = self._audit(db)
        enrollments = EnrollmentRepository(db)
        reviewed = _run(admin_transition_enrollment(
            str(ids["enrollment_id"]),
            EnrollmentTransitionRequest(workflow_state="under_review"),
            admin,
            enrollments,
            audit,
        ))
        self.assertEqual(reviewed.review_state, "under_review")
        approved = _run(admin_transition_enrollment(
            str(ids["enrollment_id"]),
            EnrollmentTransitionRequest(workflow_state="approved"),
            admin,
            enrollments,
            audit,
        ))
        self.assertEqual(approved.payment_status, "paid")
        self.assertFalse(approved.verified_by_admin)

        def _skip_card(self, enrollment, student, course):
            raise RuntimeError("card generation skipped")

        with patch("app.services.enrollment_card_service.EnrollmentCardService.generate_enrollment_card", _skip_card):
            verified = _run(admin_verify_enrollment(
                str(ids["enrollment_id"]),
                admin,
                enrollments,
                CourseRepository(db),
                UserRepository(db),
                StudentRepository(db),
                _Notify(),
                audit,
            ))
        self.assertTrue(verified.verified_by_admin)
        self.assertEqual(db["payments"].documents, [])
        with self.assertRaises(ConflictError):
            _run(admin_verify_enrollment(
                str(ids["enrollment_id"]),
                admin,
                enrollments,
                CourseRepository(db),
                UserRepository(db),
                StudentRepository(db),
                _Notify(),
                audit,
            ))
        actions = [item["action"] for item in db["audit_logs"].documents]
        self.assertEqual(actions, ["enrollment.under_review", "enrollment.approved", "enrollment.verify"])
        for record in db["audit_logs"].documents:
            self.assertEqual(record["actor_id"], admin.id)
            self.assertEqual(record["actor_role"], "admin")
            self.assertEqual(record["entity_type"], "enrollment")
            self.assertEqual(record["entity_id"], str(ids["enrollment_id"]))
            self.assertIn("created_at", record)
            rendered = str(record)
            self.assertNotIn(PHONE, rendered)
            self.assertNotIn(ADDRESS, rendered)
            self.assertNotIn(GUARDIAN, rendered)
            self.assertNotIn(RECEIPT, rendered)
        self.assertIsNone(db["audit_logs"].documents[0]["previous_state"]["review_state"])
        self.assertEqual(db["audit_logs"].documents[0]["new_state"]["review_state"], "under_review")
        self.assertEqual(db["audit_logs"].documents[1]["previous_state"]["payment_status"], "pending")
        self.assertEqual(db["audit_logs"].documents[1]["new_state"]["payment_status"], "paid")
        self.assertFalse(db["audit_logs"].documents[1]["new_state"]["verified_by_admin"])
        self.assertTrue(db["audit_logs"].documents[2]["new_state"]["verified_by_admin"])
        self.assertIsNone(db["enrollments"].documents[1].get("review_state"))

    def test_unauthorized_and_invalid_decisions_do_not_write_history(self) -> None:
        db, ids = self._world()
        audit = self._audit(db)
        enrollments = EnrollmentRepository(db)
        with self.assertRaises(ForbiddenError):
            _run(get_payment_admin(_account(ids["user_id"], "user")))
        with self.assertRaises(ForbiddenError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                _account(ids["user_id"], "user"),
                enrollments,
                audit,
            ))
        with self.assertRaises(ForbiddenError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                _account(ObjectId(), "academic_manager"),
                enrollments,
                audit,
            ))
        db["enrollments"].documents[0]["payment_receipt_url"] = None
        with self.assertRaises(ConflictError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                _account(ObjectId(), "admin"),
                enrollments,
                audit,
            ))
        self.assertEqual(db["audit_logs"].documents, [])
        self.assertEqual(db["enrollments"].documents[0]["payment_status"], "pending")
        self.assertIsNone(db["enrollments"].documents[1].get("review_state"))
        with self.assertRaises(ForbiddenError):
            _run(upload_payment_receipt(
                str(ids["enrollment_id"]),
                PaymentReceiptUpload(receipt_url=RECEIPT),
                _account(ids["other_user"], "user"),
                enrollments,
                StudentRepository(db),
                audit,
            ))

    def test_same_receipt_and_same_ledger_status_do_not_create_another_decision(self) -> None:
        db, ids = self._world()
        db["enrollments"].documents[0]["payment_receipt_url"] = None
        audit = self._audit(db)
        uploaded = _run(upload_payment_receipt(
            str(ids["enrollment_id"]),
            PaymentReceiptUpload(receipt_url=RECEIPT),
            _account(ids["user_id"], "user"),
            EnrollmentRepository(db),
            StudentRepository(db),
            audit,
        ))
        repeated = _run(upload_payment_receipt(
            str(ids["enrollment_id"]),
            PaymentReceiptUpload(receipt_url=RECEIPT),
            _account(ids["user_id"], "user"),
            EnrollmentRepository(db),
            StudentRepository(db),
            audit,
        ))
        self.assertEqual(uploaded.payment_receipt_url, repeated.payment_receipt_url)
        self.assertEqual([item["action"] for item in db["audit_logs"].documents], ["enrollment.receipt_uploaded"])

        payment_id = ObjectId()
        db.add("payments", [{
            "_id": payment_id,
            "student_id": ObjectId(),
            "course_id": ObjectId(),
            "enrollment_id": ids["enrollment_id"],
            "amount": 80.0,
            "currency": "PKR",
            "payment_method": "cash",
            "payment_status": "pending",
            "transaction_id": "gateway-secret",
            "invoice_url": RECEIPT,
            "scholarship_discount": 0.0,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        service = PaymentService(PaymentRepository(db), audit=audit)
        admin = _account(ObjectId(), "admin")
        _run(service.update_payment(
            str(payment_id),
            PaymentUpdate(payment_status="completed"),
            actor_role=admin.role,
            actor_id=admin.id,
        ))
        again = _run(service.update_payment(
            str(payment_id),
            PaymentUpdate(payment_status="completed"),
            actor_role=admin.role,
            actor_id=admin.id,
        ))
        self.assertEqual(again.payment_status, "completed")
        self.assertEqual(again.amount, 80.0)
        self.assertEqual(
            [item["action"] for item in db["audit_logs"].documents],
            ["enrollment.receipt_uploaded", "payment.approve"],
        )
        rendered = str(db["audit_logs"].documents[-1])
        self.assertNotIn("gateway-secret", rendered)
        self.assertNotIn(RECEIPT, rendered)
        self.assertEqual(db["enrollments"].documents[0]["verified_by_admin"], False)

    def test_audit_failure_is_explicit_and_notification_failure_keeps_the_decision(self) -> None:
        db, ids = self._world()
        admin = _account(ObjectId(), "admin")
        audit = self._audit(db)
        enrollments = EnrollmentRepository(db)
        original = db["audit_logs"].insert_one

        async def fail_insert(document):
            raise RuntimeError("audit store unavailable")

        db["audit_logs"].insert_one = fail_insert
        with self.assertRaises(AuditPersistenceError) as raised:
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                admin,
                enrollments,
                audit,
            ))
        self.assertIn("not recorded", raised.exception.detail)
        self.assertNotIn("persisted", raised.exception.detail)
        self.assertEqual(db["enrollments"].documents[0]["review_state"], "under_review")
        self.assertEqual(db["audit_logs"].documents, [])
        pending = db["enrollments"].documents[0]["audit_pending"]
        self.assertEqual(pending["action"], "enrollment.under_review")
        self.assertEqual(pending["actor_id"], admin.id)
        self.assertNotIn(PHONE, str(pending))
        self.assertNotIn(RECEIPT, str(pending))
        db["audit_logs"].insert_one = original
        recovered = _run(admin_transition_enrollment(
            str(ids["enrollment_id"]),
            EnrollmentTransitionRequest(workflow_state="under_review"),
            admin,
            enrollments,
            audit,
        ))
        self.assertEqual(recovered.review_state, "under_review")
        self.assertIsNone(db["enrollments"].documents[0].get("audit_pending"))
        self.assertEqual(len(db["audit_logs"].documents), 1)
        recorded = db["audit_logs"].documents[0]
        self.assertEqual(recorded["actor_id"], admin.id)
        self.assertEqual(recorded["previous_state"]["review_state"], None)
        self.assertEqual(recorded["new_state"]["review_state"], "under_review")
        self.assertNotIn(PHONE, str(recorded))
        with self.assertRaises(ConflictError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                admin,
                enrollments,
                audit,
            ))
        self.assertEqual(len(db["audit_logs"].documents), 1)

    def test_a_new_service_instance_recovers_a_stored_pending_marker(self) -> None:
        db, ids = self._world()
        admin = _account(ObjectId(), "admin")
        original = db["audit_logs"].insert_one

        async def fail_insert(document):
            raise RuntimeError("audit store unavailable")

        db["audit_logs"].insert_one = fail_insert
        with self.assertRaises(AuditPersistenceError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                admin,
                EnrollmentRepository(db),
                AuditService(AuditLogRepository(db)),
            ))
        self.assertEqual(db["enrollments"].documents[0]["review_state"], "under_review")
        self.assertEqual(db["audit_logs"].documents, [])
        db["audit_logs"].insert_one = original
        recovered = _run(admin_transition_enrollment(
            str(ids["enrollment_id"]),
            EnrollmentTransitionRequest(workflow_state="under_review"),
            admin,
            EnrollmentRepository(db),
            AuditService(AuditLogRepository(db)),
        ))
        self.assertEqual(recovered.review_state, "under_review")
        self.assertEqual(len(db["audit_logs"].documents), 1)
        self.assertIsNone(db["enrollments"].documents[0].get("audit_pending"))

    def test_snapshot_keeps_the_decision_and_redacts_private_profile_fields(self) -> None:
        recorded = snapshot({
            "review_state": "approved",
            "payment_status": "paid",
            "verified_by_admin": False,
            "phone_number": PHONE,
            "address": ADDRESS,
            "father_guardian_name": GUARDIAN,
            "emergency_contact_phone": PHONE,
            "payment_receipt_url": RECEIPT,
            "transaction_id": "gateway-secret",
            "audit_pending": {"operation_id": "hidden"},
        })
        self.assertNotIn("audit_pending", recorded)
        self.assertEqual(recorded["review_state"], "approved")
        self.assertEqual(recorded["payment_status"], "paid")
        self.assertEqual(recorded["phone_number"], "[redacted]")
        self.assertEqual(recorded["address"], "[redacted]")
        self.assertEqual(recorded["father_guardian_name"], "[redacted]")
        self.assertEqual(recorded["emergency_contact_phone"], "[redacted]")
        self.assertEqual(recorded["payment_receipt_url"], "[redacted]")
        self.assertEqual(recorded["transaction_id"], "[redacted]")

    def test_business_write_failure_does_not_record_history(self) -> None:
        db, ids = self._world()
        enrollments = EnrollmentRepository(db)

        async def fail_update(enrollment_id, data):
            del enrollment_id, data
            return None

        enrollments.update = fail_update
        with self.assertRaises(NotFoundError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                _account(ObjectId(), "admin"),
                enrollments,
                self._audit(db),
            ))
        self.assertIsNone(db["enrollments"].documents[0].get("review_state"))
        self.assertEqual(db["audit_logs"].documents, [])

    def test_missing_history_is_not_invented_without_a_pending_marker(self) -> None:
        db, ids = self._world()
        db["enrollments"].documents[0]["review_state"] = "under_review"
        with self.assertRaises(ConflictError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                _account(ObjectId(), "admin"),
                EnrollmentRepository(db),
                self._audit(db),
            ))
        self.assertEqual(db["audit_logs"].documents, [])

    def test_audit_rows_cannot_be_updated_or_purged(self) -> None:
        db, _ids = self._world()
        repo = AuditLogRepository(db)
        created = _run(repo.create({
            "actor_id": "actor",
            "actor_role": "admin",
            "action": "enrollment.under_review",
            "entity_type": "enrollment",
            "entity_id": "enrollment",
            "previous_state": {},
            "new_state": {},
            "context": {},
            "created_at": NOW,
            "operation_id": "op-1",
        }))
        self.assertIsNone(_run(repo.update(created.id, {"action": "tampered"})))
        self.assertFalse(_run(repo.purge_document(created.id)))
        self.assertEqual(db["audit_logs"].documents[0]["action"], "enrollment.under_review")

    def test_clearing_a_recorded_marker_does_not_insert_a_second_audit(self) -> None:
        db, ids = self._world()
        enrollments = EnrollmentRepository(db)
        original = enrollments.update

        async def fail_clear(enrollment_id, data):
            if data == {"audit_pending": None}:
                return None
            return await original(enrollment_id, data)

        enrollments.update = fail_clear
        admin = _account(ObjectId(), "admin")
        audit = self._audit(db)
        with self.assertRaises(AuditPersistenceError):
            _run(admin_transition_enrollment(
                str(ids["enrollment_id"]),
                EnrollmentTransitionRequest(workflow_state="under_review"),
                admin,
                enrollments,
                audit,
            ))
        self.assertEqual(len(db["audit_logs"].documents), 1)
        self.assertIsNotNone(db["enrollments"].documents[0].get("audit_pending"))
        enrollments.update = original
        recovered = _run(admin_transition_enrollment(
            str(ids["enrollment_id"]),
            EnrollmentTransitionRequest(workflow_state="under_review"),
            admin,
            enrollments,
            audit,
        ))
        self.assertEqual(recovered.review_state, "under_review")
        self.assertEqual(len(db["audit_logs"].documents), 1)
        self.assertIsNone(db["enrollments"].documents[0].get("audit_pending"))
