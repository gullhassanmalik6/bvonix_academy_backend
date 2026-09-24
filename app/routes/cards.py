"""
Student enrollment card generation API.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.admin import get_admin_user
from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.dependencies import (
    get_course_repository,
    get_enrollment_repository,
    get_student_repository,
    get_user_repository,
)
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.student_card import (
    StudentCardBulkGenerateRequest,
    StudentCardDataInput,
    StudentCardGenerateRequest,
)
from app.services.enrollment_card_service import (
    EnrollmentCardData,
    EnrollmentCardService,
    build_card_data,
    card_data_from_input,
)
from app.services.pdf_generator import generate_card_pdf_bytes, render_card_html
from app.utils.exceptions import ForbiddenError, NotFoundError

router = APIRouter()


@router.post("/generate-student-card")
async def generate_student_card(
    payload: StudentCardGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Generate a single print-ready enrollment card PDF from JSON student data.
    Authenticated users (admin recommended for arbitrary payloads).
    """
    data = card_data_from_input(payload.data)
    pdf_bytes = await _generate_pdf(data)
    filename = f"student_card_{_safe_filename(payload.data.student_id)}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/generate-student-cards/bulk")
async def generate_student_cards_bulk(
    payload: StudentCardBulkGenerateRequest,
    admin: User = Depends(get_admin_user),
) -> StreamingResponse:
    """Generate multiple card PDFs packaged in a ZIP (admin only)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, item in enumerate(payload.students):
            data = card_data_from_input(item.data)
            pdf_bytes = await _generate_pdf(data)
            name = item.filename or f"card_{_safe_filename(item.data.student_id or str(i))}.pdf"
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            zf.writestr(name, pdf_bytes)
    buf.seek(0)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="enrollment_cards_{stamp}.zip"'},
    )


@router.get("/preview/{enrollment_id}")
async def get_card_preview_data(
    enrollment_id: str,
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> dict:
    """Return JSON card fields for React print preview."""
    enrollment, student_user, course = await _resolve_enrollment_context(
        enrollment_id,
        current_user,
        enrollment_repo,
        student_repo,
        course_repo,
        user_repo,
        allow_admin=True,
    )
    data = build_card_data(enrollment, student_user, course)
    preview = _card_data_to_preview_dict(data)
    preview["profileImageUrl"] = enrollment.profile_image_url or preview.get("profileImageUrl")
    return preview


@router.get("/enrollments/{enrollment_id}/download")
async def download_card_by_enrollment(
    enrollment_id: str,
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> StreamingResponse:
    """Download card PDF for an enrollment (student own or admin)."""
    enrollment, student_user, course = await _resolve_enrollment_context(
        enrollment_id, current_user, enrollment_repo, student_repo, course_repo, user_repo,
        allow_admin=True,
    )
    service = EnrollmentCardService()
    _, pdf_bytes = service.generate_enrollment_card(enrollment, student_user, course)
    filename = f"enrollment_card_{enrollment.enrollment_card_number or enrollment_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/render-html/{enrollment_id}")
async def render_card_html_preview(
    enrollment_id: str,
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> StreamingResponse:
    """Browser preview of exact PDF HTML (matches downloaded card)."""
    enrollment, student_user, course = await _resolve_enrollment_context(
        enrollment_id,
        current_user,
        enrollment_repo,
        student_repo,
        course_repo,
        user_repo,
        allow_admin=True,
    )
    data = build_card_data(enrollment, student_user, course)
    html = render_card_html(data)
    return StreamingResponse(io.BytesIO(html.encode("utf-8")), media_type="text/html")


@router.post("/generate-student-card/html")
async def preview_card_html(
    payload: StudentCardGenerateRequest,
    admin: User = Depends(get_admin_user),
) -> StreamingResponse:
    """Debug/preview: return rendered HTML for card layout."""
    data = card_data_from_input(payload.data)
    html = render_card_html(data)
    return StreamingResponse(io.BytesIO(html.encode("utf-8")), media_type="text/html")


async def _generate_pdf(data: EnrollmentCardData) -> bytes:
    import asyncio

    return await asyncio.to_thread(generate_card_pdf_bytes, data)


async def _resolve_enrollment_context(
    enrollment_id: str,
    current_user: User,
    enrollment_repo: EnrollmentRepository,
    student_repo: StudentRepository,
    course_repo: CourseRepository,
    user_repo: UserRepository,
    allow_admin: bool = False,
):
    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment not found")

    is_admin = current_user.role == "admin"
    if is_admin and allow_admin:
        pass
    else:
        student = await student_repo.get_by_user_id(current_user.id)
        if not student or enrollment.student_id != student.id:
            raise ForbiddenError("Access denied")

    if not enrollment.verified_by_admin and not is_admin:
        raise ForbiddenError("Card available after admin verification")

    course = await course_repo.get_by_id(enrollment.course_id)
    if not course:
        raise NotFoundError("Course not found")

    enrolled_student = await student_repo.get_by_id(enrollment.student_id)
    if not enrolled_student:
        raise NotFoundError("Student not found")

    student_user = await user_repo.get_by_id(enrolled_student.user_id)
    if not student_user:
        raise NotFoundError("User not found")

    return enrollment, student_user, course


def _safe_filename(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value)[:80]


def _card_data_to_preview_dict(data: EnrollmentCardData) -> dict:
    settings = get_settings()
    origin = settings.allowed_origins_list()[0] if settings.allowed_origins_list() else ""
    return {
        "academyName": data.academy_name,
        "studentName": data.student_name,
        "studentId": data.student_id,
        "fatherName": data.father_guardian_name,
        "course": data.course_name,
        "batch": data.batch,
        "enrollmentDate": data.enrollment_date,
        "validUntil": data.validity,
        "dateOfBirth": data.date_of_birth,
        "gender": data.gender,
        "phone": data.phone,
        "email": data.email,
        "campus": data.campus,
        "address": data.address,
        "profileImageUrl": (
            f"/{data.profile_image_path}".replace("//", "/")
            if data.profile_image_path
            else None
        ),
        "verifyUrl": data.qr_text,
        "website": data.website,
        "supportEmail": data.support_email,
        "supportPhone": data.support_phone,
        "authorizedSignatureName": _load_signature_name(),
        "origin": origin,
    }


def _load_signature_name() -> str:
    import json
    from pathlib import Path

    theme_file = Path(__file__).resolve().parent.parent / "data" / "card_theme.json"
    if theme_file.is_file():
        try:
            theme = json.loads(theme_file.read_text(encoding="utf-8"))
            return (theme.get("academy") or {}).get("authorized_signature_name") or "Gul Hassan"
        except Exception:
            pass
    return "Gul Hassan"
