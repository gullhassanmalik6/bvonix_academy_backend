"""Enrollment and payment transitions on top of the stored fields.

Existing documents keep status, payment_status, verified_by_admin, and
payment_receipt_url. review_state is optional and only set for review steps
that those fields cannot express. Missing review_state is derived.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.permissions import can_approve_payments, is_management
from app.utils.exceptions import ConflictError, ForbiddenError

PENDING = "pending"
RECEIPT_UPLOADED = "receipt_uploaded"
UNDER_REVIEW = "under_review"
APPROVED = "approved"
ACTIVE = "active"
REJECTED = "rejected"
RESUBMISSION_REQUIRED = "resubmission_required"
REFUNDED = "refunded"
CANCELLED = "cancelled"
COMPLETED = "completed"

ENROLLMENT_TRANSITIONS: dict[str, set[str]] = {
    PENDING: {RECEIPT_UPLOADED, CANCELLED},
    RECEIPT_UPLOADED: {UNDER_REVIEW, ACTIVE, RECEIPT_UPLOADED, CANCELLED},
    UNDER_REVIEW: {APPROVED, REJECTED, RESUBMISSION_REQUIRED, ACTIVE, CANCELLED},
    APPROVED: {ACTIVE, REFUNDED, CANCELLED},
    RESUBMISSION_REQUIRED: {RECEIPT_UPLOADED, CANCELLED},
    REJECTED: {RESUBMISSION_REQUIRED, CANCELLED},
    ACTIVE: {CANCELLED, REFUNDED, COMPLETED},
    COMPLETED: {CANCELLED},
    REFUNDED: {CANCELLED},
    CANCELLED: set(),
}

STUDENT_TRANSITIONS = {
    (PENDING, RECEIPT_UPLOADED),
    (RESUBMISSION_REQUIRED, RECEIPT_UPLOADED),
    (RECEIPT_UPLOADED, RECEIPT_UPLOADED),
}

PAYMENT_ADMIN_TRANSITIONS = {
    (RECEIPT_UPLOADED, UNDER_REVIEW),
    (RECEIPT_UPLOADED, ACTIVE),
    (UNDER_REVIEW, APPROVED),
    (UNDER_REVIEW, REJECTED),
    (UNDER_REVIEW, RESUBMISSION_REQUIRED),
    (UNDER_REVIEW, ACTIVE),
    (APPROVED, ACTIVE),
    (APPROVED, REFUNDED),
    (REJECTED, RESUBMISSION_REQUIRED),
    (ACTIVE, REFUNDED),
}

PAYMENT_PENDING = "pending"
PAYMENT_COMPLETED = "completed"
PAYMENT_FAILED = "failed"
PAYMENT_REFUNDED = "refunded"

PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    PAYMENT_PENDING: {PAYMENT_COMPLETED, PAYMENT_FAILED},
    PAYMENT_COMPLETED: {PAYMENT_REFUNDED},
    PAYMENT_FAILED: set(),
    PAYMENT_REFUNDED: set(),
}


def workflow_state(enrollment: Any) -> str:
    """Derive the lifecycle state. Old records do not need review_state."""
    status = getattr(enrollment, "status", None) or PENDING
    payment_status = getattr(enrollment, "payment_status", None) or PENDING
    review_state = getattr(enrollment, "review_state", None)
    if status == CANCELLED or review_state == CANCELLED:
        return CANCELLED
    if payment_status == "refunded" or review_state == REFUNDED:
        return REFUNDED
    if status == COMPLETED:
        return COMPLETED
    if review_state in {UNDER_REVIEW, REJECTED, RESUBMISSION_REQUIRED, APPROVED}:
        return review_state
    if getattr(enrollment, "verified_by_admin", False) and status == ACTIVE:
        return ACTIVE
    if getattr(enrollment, "verified_by_admin", False):
        return APPROVED
    if getattr(enrollment, "payment_receipt_url", None):
        return RECEIPT_UPLOADED
    return PENDING


def assert_enrollment_transition(actor_role: str, current: str, target: str, *, owns_enrollment: bool) -> None:
    allowed = ENROLLMENT_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ConflictError(f"Cannot change enrollment from {current} to {target}")
    pair = (current, target)
    if pair in STUDENT_TRANSITIONS and owns_enrollment and actor_role == "user":
        return
    if pair in PAYMENT_ADMIN_TRANSITIONS and can_approve_payments(actor_role):
        return
    if target == CANCELLED and is_management(actor_role):
        return
    if target == COMPLETED and is_management(actor_role):
        return
    if actor_role == "user":
        raise ForbiddenError("You cannot change this enrollment state")
    raise ForbiddenError("You cannot perform this enrollment change")


def enrollment_transition_updates(enrollment: Any, target: str, *, actor_id: str | None, now: datetime | None = None) -> dict[str, Any]:
    """Field updates that store the target state without renaming paid to completed."""
    moment = now or datetime.now(timezone.utc)
    updates: dict[str, Any] = {"review_state": None, "updated_at": moment}
    if target == RECEIPT_UPLOADED:
        updates["status"] = PENDING
        updates["verified_by_admin"] = False
    elif target == UNDER_REVIEW:
        updates["review_state"] = UNDER_REVIEW
    elif target == APPROVED:
        updates["review_state"] = APPROVED
        updates["payment_status"] = "paid"
        updates["payment_date"] = getattr(enrollment, "payment_date", None) or moment
        updates["verified_by_admin"] = False
        updates["status"] = PENDING
    elif target == ACTIVE:
        updates["status"] = ACTIVE
        updates["payment_status"] = "paid"
        updates["payment_date"] = getattr(enrollment, "payment_date", None) or moment
        updates["verified_by_admin"] = True
        updates["verified_at"] = moment
        updates["verified_by"] = actor_id
    elif target == REJECTED:
        updates["review_state"] = REJECTED
        updates["verified_by_admin"] = False
    elif target == RESUBMISSION_REQUIRED:
        updates["review_state"] = RESUBMISSION_REQUIRED
        updates["verified_by_admin"] = False
    elif target == REFUNDED:
        updates["payment_status"] = "refunded"
        updates["review_state"] = REFUNDED
    elif target == CANCELLED:
        updates["status"] = CANCELLED
        updates["review_state"] = CANCELLED
    elif target == COMPLETED:
        updates["status"] = COMPLETED
        updates["completion_date"] = getattr(enrollment, "completion_date", None) or moment
    return updates


def assert_payment_transition(current: str, target: str) -> None:
    if current == target:
        return
    allowed = PAYMENT_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ConflictError(f"Cannot change payment from {current} to {target}")
