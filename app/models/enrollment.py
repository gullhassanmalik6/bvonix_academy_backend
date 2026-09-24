from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Enrollment:
    """
    Domain model for course enrollment.
    
    Tracks student enrollment in courses with status, payment, and dates.
    Includes personal information for enrollment card generation.
    """

    id: str
    student_id: str  # Reference to Student
    course_id: str  # Reference to Course
    enrollment_date: datetime
    status: str  # "pending", "active", "completed", "cancelled"
    payment_status: str  # "pending", "paid", "refunded"
    payment_date: datetime | None
    completion_date: datetime | None
    progress_percentage: float  # 0-100
    # Personal information for enrollment
    class_type: str  # "physical" or "online"
    phone_number: str | None
    address: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    father_guardian_name: str | None
    date_of_birth: str | None
    gender: str | None
    # Enrollment card fields
    profile_image_url: str | None  # Passport size profile image for enrollment card
    enrollment_card_number: str | None  # Unique card number
    enrollment_card_url: str | None  # URL to generated card PDF
    # Payment receipt
    payment_receipt_url: str | None  # URL to uploaded payment receipt
    verified_by_admin: bool  # Whether admin has verified payment
    verified_at: datetime | None
    verified_by: str | None  # Admin user ID who verified
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
