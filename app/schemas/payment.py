from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class PaymentCreate(APIModel):
    student_id: str
    course_id: str | None = None
    enrollment_id: str | None = None
    amount: float = Field(..., ge=0)
    currency: str = Field(default="PKR", pattern="^(PKR|USD|EUR)$")
    payment_method: str = Field(pattern="^(cash|bank_transfer|card|online)$")
    due_date: datetime | None = None
    scholarship_discount: float = Field(default=0.0, ge=0)
    notes: str | None = Field(default=None, max_length=500)
    payment_date: datetime | None = None
    record_as_received: bool = False
    client_request_id: str | None = Field(default=None, max_length=80)


class PaymentUpdate(APIModel):
    payment_status: str | None = Field(default=None, pattern="^(pending|completed|failed|refunded)$")
    transaction_id: str | None = None
    invoice_number: str | None = None
    invoice_url: str | None = None
    payment_date: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)


class PaymentPublic(APIModel):
    id: str
    student_id: str
    course_id: str | None
    enrollment_id: str | None
    amount: float
    currency: str
    payment_method: str
    payment_status: str
    transaction_id: str | None
    invoice_number: str | None
    invoice_url: str | None
    payment_date: datetime | None
    due_date: datetime | None
    scholarship_discount: float
    notes: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    receipt_url: str | None = None
    receipt_available: bool = False
    verification_status: str | None = None
    course_title: str | None = None
