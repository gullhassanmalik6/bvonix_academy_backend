from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class EnrollmentCreate(APIModel):
    # Note: student_id and course_id come from path/auth, not body
    payment_status: str = Field(default="pending", pattern="^(pending|paid|refunded)$")
    # Personal information
    class_type: str = Field(pattern="^(physical|online)$")
    phone_number: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)
    father_guardian_name: str | None = Field(default=None, max_length=120)
    date_of_birth: str | None = Field(default=None, max_length=20, description="ISO date YYYY-MM-DD")
    gender: str | None = Field(default=None, max_length=30)
    profile_image_url: str | None = Field(default=None)  # Profile image URL (uploaded separately)


class PaymentReceiptUpload(APIModel):
    receipt_url: str = Field(..., description="URL of the uploaded payment receipt")


class EnrollmentCardForm(APIModel):
    """Prefill data for admin enrollment card form (student + enrollment + course)."""
    enrollment_id: str
    student_id: str
    student_full_name: str | None = None
    student_email: str = ""
    phone_number: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    father_guardian_name: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    profile_image_url: str | None = None
    enrollment_card_number: str | None = None
    course_id: str = ""
    course_title: str = ""
    class_type: str = "online"
    enrollment_date: datetime | None = None
    verified_at: datetime | None = None
    enrollment_card_url: str | None = None
    verified_by_admin: bool = False


class EnrollmentCardFormUpdate(APIModel):
    """Admin can add or edit student info required for the enrollment card."""
    student_full_name: str | None = Field(default=None, max_length=120)
    phone_number: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)
    father_guardian_name: str | None = Field(default=None, max_length=120)
    date_of_birth: str | None = Field(default=None, max_length=20)
    gender: str | None = Field(default=None, max_length=30)
    profile_image_url: str | None = Field(default=None)


class EnrollmentUpdate(APIModel):
    status: str | None = Field(default=None, pattern="^(pending|active|completed|cancelled)$")
    payment_status: str | None = Field(default=None, pattern="^(pending|paid|refunded)$")
    payment_date: datetime | None = None
    completion_date: datetime | None = None
    progress_percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    # Personal information updates
    phone_number: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)
    father_guardian_name: str | None = Field(default=None, max_length=120)
    date_of_birth: str | None = Field(default=None, max_length=20)
    gender: str | None = Field(default=None, max_length=30)
    profile_image_url: str | None = Field(default=None)
    # Payment receipt
    payment_receipt_url: str | None = Field(default=None)
    # Admin verification
    verified_by_admin: bool | None = None
    verified_at: datetime | None = None
    verified_by: str | None = None
    enrollment_card_url: str | None = None


class EnrollmentPublic(APIModel):
    id: str
    student_id: str
    course_id: str
    enrollment_date: datetime
    status: str
    payment_status: str
    payment_date: datetime | None = None
    completion_date: datetime | None = None
    progress_percentage: float
    # Personal information
    class_type: str
    phone_number: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    father_guardian_name: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    # Enrollment card
    profile_image_url: str | None = None
    enrollment_card_number: str | None = None
    enrollment_card_url: str | None = None
    payment_receipt_url: str | None = None
    verified_by_admin: bool
    verified_at: datetime | None = None
    verified_by: str | None = None
    created_at: datetime
    updated_at: datetime


def enrollment_to_public(enrollment) -> EnrollmentPublic:
    """Map domain Enrollment to API response."""
    return EnrollmentPublic(
        id=enrollment.id,
        student_id=enrollment.student_id,
        course_id=enrollment.course_id,
        enrollment_date=enrollment.enrollment_date,
        status=enrollment.status,
        payment_status=enrollment.payment_status,
        payment_date=enrollment.payment_date,
        completion_date=enrollment.completion_date,
        progress_percentage=enrollment.progress_percentage,
        class_type=enrollment.class_type,
        phone_number=enrollment.phone_number,
        address=enrollment.address,
        emergency_contact_name=enrollment.emergency_contact_name,
        emergency_contact_phone=enrollment.emergency_contact_phone,
        father_guardian_name=enrollment.father_guardian_name,
        date_of_birth=enrollment.date_of_birth,
        gender=enrollment.gender,
        profile_image_url=enrollment.profile_image_url,
        enrollment_card_number=enrollment.enrollment_card_number,
        enrollment_card_url=enrollment.enrollment_card_url,
        payment_receipt_url=enrollment.payment_receipt_url,
        verified_by_admin=enrollment.verified_by_admin,
        verified_at=enrollment.verified_at,
        verified_by=enrollment.verified_by,
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )
