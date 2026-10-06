from __future__ import annotations

from datetime import datetime, timezone

from app.core.enrollment_workflow import assert_payment_transition
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate, PaymentUpdate
from app.models.payment import Payment
from app.services.audit_service import AuditService, write_audit
from app.utils.exceptions import NotFoundError


class PaymentService:
    def __init__(self, payment_repo: PaymentRepository, *, audit: AuditService | None = None) -> None:
        self._payments = payment_repo
        self._audit = audit

    async def create_payment(
        self,
        payload: PaymentCreate,
        created_by: str | None = None,
    ) -> Payment:
        """Create a new payment record."""
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
    ) -> tuple[list[Payment], int]:
        """List payments with optional filters."""
        all_payments = await self._payments.list(skip=0, limit=10000)
        
        # Apply filters
        if student_id:
            all_payments = [p for p in all_payments if p.student_id == student_id]
        if course_id:
            all_payments = [p for p in all_payments if p.course_id == course_id]
        
        total = len(all_payments)
        paginated = all_payments[skip:skip + limit]
        return paginated, total

    async def update_payment(
        self,
        payment_id: str,
        payload: PaymentUpdate,
    ) -> Payment:
        """Update a payment."""
        payment = await self.get_payment(payment_id)
        
        update_data: dict[str, any] = {}
        if payload.payment_status is not None:
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
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated = await self._payments.update(payment_id, update_data)
        if not updated:
            raise NotFoundError("Payment not found")
        action = "payment.update"
        if payload.payment_status == "completed":
            action = "payment.approve"
        elif payload.payment_status == "failed":
            action = "payment.reject"
        elif payload.payment_status == "refunded":
            action = "payment.refund"
        await write_audit(
            self._audit,
            action=action,
            entity_type="payment",
            entity_id=updated.id,
            previous=payment,
            current=updated,
        )
        return updated

    async def delete_payment(self, payment_id: str) -> None:
        """Delete a payment."""
        payment = await self.get_payment(payment_id)
        deleted = await self._payments.delete(payment_id)
        if not deleted:
            raise NotFoundError("Payment not found")
