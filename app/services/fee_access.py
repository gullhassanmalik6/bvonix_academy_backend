"""Outstanding balances and overdue learning locks.

Enrollment payment_status and ledger payment_status stay separate.
An access exception does not change either status.
"""

from __future__ import annotations

import contextvars
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

fee_repositories: contextvars.ContextVar[tuple | None] = contextvars.ContextVar(
    "fee_repositories",
    default=None,
)

from app.core.enrollment_workflow import APPROVED, RECEIPT_UPLOADED, UNDER_REVIEW, workflow_state
from app.core.money import money

CONFIRMED_STATUS = "completed"
PENDING_STATUS = "pending"
OVERDUE_DETAIL = (
    "This course is locked because the fee is overdue. "
    "Open Payments to review the balance or ask an administrator for an access exception."
)
_AWAITING_REVIEW = {RECEIPT_UPLOADED, UNDER_REVIEW, APPROVED}


def normalize_fee_due_date(value: datetime | None, *, now: datetime | None = None) -> datetime | None:
    """Accept an administrator's due date, or none. A missing date stays missing."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        from app.utils.exceptions import ConflictError
        raise ConflictError("Fee due date must be a date and time")
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    aware = aware.astimezone(timezone.utc)
    current = now or datetime.now(timezone.utc)
    earliest = datetime(2000, 1, 1, tzinfo=timezone.utc)
    latest = current + timedelta(days=365 * 15)
    if aware < earliest or aware > latest:
        from app.utils.exceptions import ConflictError
        raise ConflictError("Fee due date is outside the allowed range")
    return aware


def _aware(value: datetime | None) -> datetime | None:
    if value is None or not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def confirmed_total(payments: list[Any]) -> Decimal:
    """Sum only confirmed ledger payments. Pending, failed, and refunded do not count."""
    total = Decimal("0.00")
    for payment in payments:
        if getattr(payment, "payment_status", None) == CONFIRMED_STATUS:
            total += money(getattr(payment, "amount", 0))
    return total


def outstanding_balance(total_fee, payments: list[Any]) -> Decimal:
    remaining = money(total_fee) - confirmed_total(payments)
    if remaining < 0:
        return Decimal("0.00")
    return remaining


def pending_covers_balance(total_fee, payments: list[Any]) -> bool:
    """A pending verification suspends the lock only when it covers what is still owed."""
    due = outstanding_balance(total_fee, payments)
    if due <= 0:
        return False
    pending = Decimal("0.00")
    for payment in payments:
        if getattr(payment, "payment_status", None) == PENDING_STATUS:
            pending += money(getattr(payment, "amount", 0))
    return pending >= due


def exception_is_active(enrollment: Any, now: datetime) -> bool:
    raw = getattr(enrollment, "access_exception", None)
    if not isinstance(raw, dict) or not raw.get("reason"):
        return False
    expires = _aware(raw.get("expires_at"))
    if expires is None:
        return True
    return expires > now


def receipt_is_awaiting_review(enrollment: Any) -> bool:
    return workflow_state(enrollment) in _AWAITING_REVIEW


def is_learning_restricted(enrollment: Any, payments: list[Any], now: datetime, total_fee) -> bool:
    """True when the due date has passed, a balance remains, and no exception applies.

    A missing due date does not restrict anyone. A pending payment restricts only
    when it does not cover the outstanding balance. A receipt still awaiting
    review does not lock the course.
    """
    due = _aware(getattr(enrollment, "fee_due_date", None))
    if due is None or now <= due:
        return False
    if outstanding_balance(total_fee, payments) <= 0:
        return False
    if exception_is_active(enrollment, now):
        return False
    if pending_covers_balance(total_fee, payments):
        return False
    if receipt_is_awaiting_review(enrollment):
        return False
    return True


def fee_summary(enrollment: Any, payments: list[Any], now: datetime, total_fee, course_title: str | None = None) -> dict:
    paid = confirmed_total(payments)
    balance = outstanding_balance(total_fee, payments)
    restricted = is_learning_restricted(enrollment, payments, now, total_fee)
    exception = getattr(enrollment, "access_exception", None)
    receipt = getattr(enrollment, "payment_receipt_url", None)
    return {
        "enrollment_id": enrollment.id,
        "course_id": enrollment.course_id,
        "course_title": course_title,
        "total_fee": float(money(total_fee)),
        "amount_paid": float(paid),
        "outstanding_balance": float(balance),
        "fee_due_date": getattr(enrollment, "fee_due_date", None),
        "payment_status": getattr(enrollment, "payment_status", None),
        "verification_status": workflow_state(enrollment),
        "verified_by_admin": bool(getattr(enrollment, "verified_by_admin", False)),
        "verified_at": getattr(enrollment, "verified_at", None),
        "verified_by": getattr(enrollment, "verified_by", None),
        "receipt_url": receipt,
        "receipt_available": bool(receipt),
        "fee_covered": balance <= 0,
        "access_restricted": restricted,
        "access_exception": exception if isinstance(exception, dict) else None,
    }
