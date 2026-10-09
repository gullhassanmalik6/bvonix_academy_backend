from __future__ import annotations

from datetime import datetime, timezone

from app.core.enrollment_workflow import assert_payment_transition
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
from app.utils.exceptions import ForbiddenError, NotFoundError


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
    ) -> Payment:
        """Create a ledger payment. This does not change the enrollment."""
        if not can_approve_payments(actor_role):
            raise ForbiddenError("You cannot approve or manage payments")
        payment = await self._payments.create_payment(
            student_id=payload.student_id,
            course_id=payload.course_id,
            enrollment_id=payload.enrollment_id,
            amount=payload.amount,
            currency=payload.currency,
            payment_method=payload.payment_method,
            due_date=payload.due_date,
            scholarship_discount=payload.scholarship_discount,
            notes=payload.notes,
            created_by=created_by,
        )
        await write_audit(
            self._audit,
            action="payment.create",
            entity_type="payment",
            entity_id=payment.id,
            current=payment,
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
    ) -> Payment:
        """Update one ledger payment. Enrollment verification is a separate record."""
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
        return updated

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
