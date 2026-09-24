from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Payment:
    """
    Domain model for payment transactions.
    
    Tracks course payments, invoices, and refunds.
    """

    id: str
    student_id: str  # Reference to Student
    course_id: str | None  # None for general payments
    enrollment_id: str | None  # Reference to Enrollment
    amount: float
    currency: str  # "PKR", "USD", etc.
    payment_method: str  # "cash", "bank_transfer", "card", "online"
    payment_status: str  # "pending", "completed", "failed", "refunded"
    transaction_id: str | None  # External payment gateway transaction ID
    invoice_number: str | None
    invoice_url: str | None
    payment_date: datetime | None
    due_date: datetime | None
    scholarship_discount: float  # Discount amount from scholarship
    notes: str | None
    created_by: str | None  # Admin user_id if manual entry
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
