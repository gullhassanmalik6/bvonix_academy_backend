"""Valid and invalid enrollment and payment transitions."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.enrollment_workflow import (
    assert_enrollment_transition,
    assert_payment_transition,
    enrollment_transition_updates,
    workflow_state,
)
from app.models.payment import Payment
from app.schemas.payment import PaymentUpdate
from app.services.payment_service import PaymentService
from app.utils.exceptions import ConflictError, ForbiddenError


def _enrollment(**overrides):
    values = {
        "status": "pending",
        "payment_status": "pending",
        "payment_receipt_url": None,
        "verified_by_admin": False,
        "review_state": None,
        "payment_date": None,
        "completion_date": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _payment(status: str = "pending") -> Payment:
    now = datetime.now(timezone.utc)
    return Payment(
        id="pay-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_id="enroll-1",
        amount=100.0,
        currency="PKR",
        payment_method="bank_transfer",
        payment_status=status,
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


class _Payments:
    def __init__(self, payment: Payment) -> None:
        self.payment = payment

    async def get_by_id(self, payment_id: str) -> Payment | None:
        return self.payment

    async def update(self, payment_id: str, data: dict) -> Payment:
        self.payment = replace(self.payment, **data)
        return self.payment


class EnrollmentWorkflowTests(unittest.TestCase):
    def test_existing_records_derive_without_a_review_state(self) -> None:
        self.assertEqual(workflow_state(_enrollment()), "pending")
        self.assertEqual(
            workflow_state(_enrollment(payment_receipt_url="/uploads/receipt.pdf")),
            "receipt_uploaded",
        )
        self.assertEqual(
            workflow_state(_enrollment(status="active", payment_status="paid", verified_by_admin=True)),
            "active",
        )
        self.assertEqual(workflow_state(_enrollment(status="cancelled")), "cancelled")
        self.assertEqual(workflow_state(_enrollment(payment_status="refunded")), "refunded")
        self.assertEqual(workflow_state(_enrollment(status="completed")), "completed")

    def test_student_can_upload_a_receipt_and_cannot_approve(self) -> None:
        assert_enrollment_transition("user", "pending", "receipt_uploaded", owns_enrollment=True)
        with self.assertRaises(ForbiddenError) as raised:
            assert_enrollment_transition("user", "receipt_uploaded", "active", owns_enrollment=True)
        self.assertEqual(raised.exception.status_code, 403)

    def test_invalid_enrollment_jump_is_rejected(self) -> None:
        with self.assertRaises(ConflictError) as raised:
            assert_enrollment_transition("admin", "pending", "active", owns_enrollment=False)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("pending", str(raised.exception.detail))
        self.assertIn("active", str(raised.exception.detail))

    def test_admin_review_path_reaches_active_and_keeps_paid(self) -> None:
        enrollment = _enrollment(payment_receipt_url="/uploads/receipt.pdf")
        assert_enrollment_transition("admin", "receipt_uploaded", "under_review", owns_enrollment=False)
        enrollment.review_state = "under_review"
        assert_enrollment_transition("admin", "under_review", "approved", owns_enrollment=False)
        enrollment.review_state = "approved"
        assert_enrollment_transition("admin", "approved", "active", owns_enrollment=False)
        updates = enrollment_transition_updates(enrollment, "active", actor_id="admin-1")
        self.assertEqual(updates["status"], "active")
        self.assertEqual(updates["payment_status"], "paid")
        self.assertTrue(updates["verified_by_admin"])
        self.assertIsNone(updates["review_state"])

    def test_existing_verify_still_allows_receipt_uploaded_to_active(self) -> None:
        assert_enrollment_transition("admin", "receipt_uploaded", "active", owns_enrollment=False)
        with self.assertRaises(ForbiddenError):
            assert_enrollment_transition("academic_manager", "receipt_uploaded", "active", owns_enrollment=False)

    def test_payment_approval_and_invalid_refund_are_controlled(self) -> None:
        assert_payment_transition("pending", "completed")
        assert_payment_transition("completed", "refunded")
        with self.assertRaises(ConflictError) as raised:
            assert_payment_transition("pending", "refunded")
        self.assertEqual(raised.exception.status_code, 409)

        service = PaymentService(_Payments(_payment("completed")))
        with self.assertRaises(ConflictError):
            asyncio.run(service.update_payment("pay-1", PaymentUpdate(payment_status="pending")))


if __name__ == "__main__":
    unittest.main()
