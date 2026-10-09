from __future__ import annotations

import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.enrollment_workflow import assert_payment_transition
from app.core.money import money
from app.core.permissions import can_approve_payments
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate, PaymentUpdate
from app.models.payment import Payment
from app.services.archive_actions import archive_record, load_for_maintenance, purge_record
from app.services.audit_service import (
    AuditService,
    commit_required_decision,
    recover_pending_decision,
    write_audit,
)
from app.services.fee_access import outstanding_balance
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, payment_repo: PaymentRepository, *, audit: AuditService | None = None) -> None:
        self._payments = payment_repo
        self._audit = audit

    async def create_payment(
        self,
        payload: PaymentCreate,
        created_by: str | None = None,
        *,
        actor_role: str,
        courses=None,
        enrollments=None,
    ) -> Payment:
        """Create a ledger payment.

        created_by is the authenticated administrator. Cash recorded as received
        is stored as completed and does not require a receipt. The enrollment
        payment flag becomes paid only when confirmed payments cover the fee.
        A pending or partial payment leaves that flag unchanged.
        """
        if not can_approve_payments(actor_role):
            raise ForbiddenError("You cannot approve or manage payments")
        if money(payload.amount) <= 0:
            raise ConflictError("Payment amount must be greater than zero")
        if payload.client_request_id:
            existing = await self._payments.find_by_client_request(payload.client_request_id)
            if existing is not None:
                await self._reflect_enrollment_coverage(
                    existing,
                    courses=courses,
                    enrollments=enrollments,
                    actor_id=created_by,
                    actor_role=actor_role,
                )
                return existing
        if payload.enrollment_id and courses is not None and enrollments is not None:
            enrollment = await enrollments.get_by_id(payload.enrollment_id)
            course = await courses.get_by_id(enrollment.course_id) if enrollment is not None else None
            if enrollment is None or course is None:
                raise NotFoundError("Enrollment not found")
            if payload.student_id != enrollment.student_id:
                raise ConflictError("The payment student does not match the enrollment")
            prior = await self._payments.for_enrollment(enrollment.id)
            remaining = outstanding_balance(course.price, prior)
            if money(payload.amount) > remaining:
                raise ConflictError("Payment amount exceeds the outstanding balance")
        received = bool(payload.record_as_received)
        if received and payload.payment_method != "cash":
            raise ConflictError("Only a cash payment can be recorded as received without a receipt")
        status = "completed" if received else "pending"
        paid_at = payload.payment_date or Payment.now_utc() if received else payload.payment_date
        try:
            payment = await self._payments.create_payment(
                student_id=payload.student_id,
                course_id=payload.course_id,
                enrollment_id=payload.enrollment_id,
                amount=float(money(payload.amount)),
                currency=payload.currency,
                payment_method=payload.payment_method,
                due_date=payload.due_date,
                scholarship_discount=payload.scholarship_discount,
                notes=payload.notes,
                created_by=created_by,
                payment_status=status,
                payment_date=paid_at,
                client_request_id=payload.client_request_id,
            )
        except DuplicateKeyError:
            if payload.client_request_id:
                existing = await self._payments.find_by_client_request(payload.client_request_id)
                if existing is not None:
                    await self._reflect_enrollment_coverage(
                        existing,
                        courses=courses,
                        enrollments=enrollments,
                        actor_id=created_by,
                        actor_role=actor_role,
                    )
                    return existing
            raise ConflictError("This payment was already recorded") from None
        await write_audit(
            self._audit,
            action="payment.create",
            entity_type="payment",
            entity_id=payment.id,
            current=payment,
            actor_id=created_by,
            actor_role=actor_role,
        )
        await self._reflect_enrollment_coverage(
            payment,
            courses=courses,
            enrollments=enrollments,
            actor_id=created_by,
            actor_role=actor_role,
        )
        return payment

    async def get_payment(self, payment_id: str) -> Payment:
        """Get payment by ID."""
        payment = await self._payments.get_by_id(payment_id)
        if not payment:
            raise NotFoundError("Payment not found")
        return payment

    async def get_student_payments(self, student_id: str) -> list[Payment]:
        """Get all payments for a student."""
        return await self._payments.get_by_student(student_id)

    async def list_payments(
        self,
        skip: int = 0,
        limit: int = 100,
        student_id: str | None = None,
        course_id: str | None = None,
        payment_status: str | None = None,
        q: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Payment], int]:
        """List payments with filters applied in MongoDB."""
        return await self._payments.list_page(
            skip=skip,
            limit=limit,
            student_id=student_id,
            course_id=course_id,
            payment_status=payment_status,
            q=q,
            sort=sort,
        )

    async def update_payment(
        self,
        payment_id: str,
        payload: PaymentUpdate,
        *,
        actor_role: str,
        actor_id: str | None = None,
        courses=None,
        enrollments=None,
    ) -> Payment:
        """Update one ledger payment. Verification stays a separate enrollment action."""
        if not can_approve_payments(actor_role):
            raise ForbiddenError("You cannot approve or manage payments")
        payment = await self.get_payment(payment_id)
        if self._audit is not None and isinstance(payment.audit_pending, dict):
            async def clear_pending():
                return await self._payments.update(payment.id, {"audit_pending": None})

            await recover_pending_decision(self._audit, payment, clear_pending)
            payment = await self.get_payment(payment_id)

        update_data: dict[str, any] = {}
        status_changed = (
            payload.payment_status is not None
            and payload.payment_status != payment.payment_status
        )
        if status_changed:
            assert_payment_transition(payment.payment_status, payload.payment_status)
            update_data["payment_status"] = payload.payment_status
        if payload.transaction_id is not None:
            update_data["transaction_id"] = payload.transaction_id
        if payload.invoice_number is not None:
            update_data["invoice_number"] = payload.invoice_number
        if payload.invoice_url is not None:
            update_data["invoice_url"] = payload.invoice_url
        if payload.payment_date is not None:
            update_data["payment_date"] = payload.payment_date
        if payload.notes is not None:
            update_data["notes"] = payload.notes
        if not update_data:
            return payment

        update_data["updated_at"] = datetime.now(timezone.utc)
        action = "payment.update"
        if status_changed and payload.payment_status == "completed":
            action = "payment.approve"
        elif status_changed and payload.payment_status == "failed":
            action = "payment.reject"
        elif status_changed and payload.payment_status == "refunded":
            action = "payment.refund"
        if self._audit is not None:
            updated = await commit_required_decision(
                self._audit,
                lambda data: self._payments.update(payment_id, data),
                action=action,
                entity_type="payment",
                entity_id=payment.id,
                actor_id=actor_id,
                actor_role=actor_role,
                previous=payment,
                updates=update_data,
            )
        else:
            updated = await self._payments.update(payment_id, update_data)
        if not updated:
            raise NotFoundError("Payment not found")
        if status_changed and payload.payment_status in {"completed", "failed", "refunded"}:
            await self._reflect_enrollment_coverage(
                updated,
                courses=courses,
                enrollments=enrollments,
                actor_id=actor_id,
                actor_role=actor_role,
            )
        return updated

    async def _reflect_enrollment_coverage(
        self,
        payment: Payment,
        *,
        courses,
        enrollments,
        actor_id: str | None,
        actor_role: str,
    ) -> None:
        """Align the enrollment payment flag with confirmed ledger coverage.

        Pending, failed, and refunded ledger rows do not reduce the balance.
        A ledger refund reopens that balance. It does not delete the payment
        and it does not run the enrollment refund transition. A verified
        enrollment stays paid because verification is a separate decision and
        can exist with no completed ledger row. An unverified enrollment that
        became paid only because cash covered the fee returns to pending when
        the confirmed balance is positive again. A refunded enrollment is not
        rewritten. The enrollment write changes only the payment flag and date.
        If that write fails, the ledger row stays and a later reconcile retries.
        """
        if payment.enrollment_id is None or courses is None or enrollments is None:
            return
        if not hasattr(enrollments, "update") or not hasattr(enrollments, "get_by_id"):
            return
        enrollment = await enrollments.get_by_id(payment.enrollment_id)
        if enrollment is None:
            return
        course = await courses.get_by_id(enrollment.course_id) if hasattr(courses, "get_by_id") else None
        if course is None:
            return
        rows = await self._payments.for_enrollment(enrollment.id)
        balance = outstanding_balance(course.price, rows)
        status = getattr(enrollment, "payment_status", None)
        now = datetime.now(timezone.utc)
        if balance <= 0 and status == "pending":
            updates = {"payment_status": "paid", "updated_at": now}
            if not getattr(enrollment, "payment_date", None):
                updates["payment_date"] = payment.payment_date or now
            await self._store_enrollment_flag(
                enrollments,
                enrollment,
                updates,
                action="enrollment.fee_covered",
                actor_id=actor_id,
                actor_role=actor_role,
            )
            return
        if balance > 0 and status == "paid" and not getattr(enrollment, "verified_by_admin", False):
            await self._store_enrollment_flag(
                enrollments,
                enrollment,
                {"payment_status": "pending", "updated_at": now},
                action="enrollment.fee_uncovered",
                actor_id=actor_id,
                actor_role=actor_role,
            )

    async def reconcile_enrollment(
        self,
        enrollment_id: str | None,
        *,
        courses,
        enrollments,
        actor_id: str | None,
        actor_role: str,
    ):
        """Repair a coverage flag after a ledger write whose enrollment update did not finish."""
        if not enrollment_id or not hasattr(self._payments, "for_enrollment"):
            return None
        rows = await self._payments.for_enrollment(enrollment_id)
        completed = [row for row in rows if getattr(row, "payment_status", None) == "completed"]
        probe = completed[-1] if completed else type("Probe", (), {
            "enrollment_id": enrollment_id,
            "payment_date": None,
            "payment_status": "pending",
        })()
        await self._reflect_enrollment_coverage(
            probe,
            courses=courses,
            enrollments=enrollments,
            actor_id=actor_id,
            actor_role=actor_role,
        )
        if hasattr(enrollments, "get_by_id"):
            return await enrollments.get_by_id(enrollment_id)
        return None

    async def _store_enrollment_flag(
        self,
        enrollments,
        enrollment,
        updates: dict,
        *,
        action: str,
        actor_id: str | None,
        actor_role: str,
    ) -> None:
        try:
            updated = await enrollments.update(enrollment.id, updates)
            await write_audit(
                self._audit,
                action=action,
                entity_type="enrollment",
                entity_id=enrollment.id,
                actor_id=actor_id,
                actor_role=actor_role,
                previous=enrollment,
                current=updated,
            )
        except (ConflictError, ForbiddenError, NotFoundError, AssertionError):
            raise
        except Exception:
            logger.warning("Enrollment payment flag was not saved for %s; the ledger row was kept", enrollment.id)

    async def delete_payment(
        self,
        payment_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive a payment. The row stays for audit."""
        if not can_approve_payments(actor_role):
            raise ForbiddenError("You cannot approve or manage payments")
        payment = await self.get_payment(payment_id)
        await archive_record(
            self._payments,
            payment,
            archived_by=archived_by,
            deactivate=False,
            audit=self._audit,
            action="payment.delete",
            entity_type="payment",
            not_found="Payment not found",
        )

    async def purge_payment(self, payment_id: str, *, actor_role: str, actor_id: str) -> None:
        """Permanently remove a payment. Super admin only."""
        payment = await load_for_maintenance(self._payments, payment_id, not_found="Payment not found")
        await purge_record(
            self._payments,
            payment,
            actor_role=actor_role,
            actor_id=actor_id,
            audit=self._audit,
            entity_type="payment",
            not_found="Payment not found",
        )
