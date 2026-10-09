"""
LMS (Learning Management System) routes for students.

Why: Separate LMS routes for student-facing features like enrollment,
results, attendance, and certificates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse

from app.core.auth import get_current_user
from app.core.enrollment_workflow import (
    RECEIPT_UPLOADED,
    assert_enrollment_transition,
    enrollment_transition_updates,
    workflow_state,
)
from app.core.dependencies import (
    get_announcement_service,
    get_require_verified_enrollment,
    get_student_portal,
    get_payment_repository,
    get_attendance_claim_service,
    get_assignment_service,
    get_attendance_correction_service,
    get_attendance_repository,
    get_attendance_service,
    get_calendar_event_service,
    get_certificate_repository,
    get_course_material_service,
    get_course_repository,
    get_enrollment_repository,
    get_forum_service,
    get_instructor_repository,
    get_live_session_service,
    get_payment_service,
    get_result_repository,
    get_scholarship_repository,
    get_scholarship_service,
    get_student_repository,
    get_user_repository,
    get_audit_service,
)
from app.models.user import User
from app.repositories.archival import record_is_active
from app.repositories.listing import clamp_limit, clamp_skip
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.certificate_repository import CertificateRepository
from app.repositories.scholarship_repository import ScholarshipRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.user_repository import UserRepository
from app.schemas.announcement import AnnouncementPublic
from app.schemas.assignment import AssignmentPublic, AssignmentSubmissionCreate, AssignmentSubmissionPublic
from app.schemas.calendar_event import CalendarEventPublic
from app.schemas.common import PaginatedResponse
from app.schemas.course_material import CourseMaterialPublic
from app.schemas.enrollment import EnrollmentCreate, EnrollmentPublic, PaymentReceiptUpload, enrollment_to_public
from app.schemas.forum import ForumPostCreate, ForumPostPublic, ForumVote
from app.schemas.live_session import LiveSessionPublic
from app.schemas.payment import PaymentPublic
from app.schemas.result import ResultPublic
from app.schemas.attendance import AbsenceReasonSubmit, AttendancePublic
from app.schemas.attendance_claim import AttendanceCheckIn, AttendanceClaimPublic, claim_to_public
from app.schemas.attendance_correction import (
    AttendanceCorrectionCreate,
    AttendanceCorrectionPublic,
    correction_to_public,
)
from app.schemas.certificate import CertificatePublic
from app.schemas.scholarship import ScholarshipPublic, ScholarshipStatus
from app.services.announcement_service import AnnouncementService
from app.services.assignment_service import AssignmentService
from app.services.attendance_correction_service import AttendanceCorrectionService
from app.services.attendance_service import AttendanceService
from app.services.calendar_event_service import CalendarEventService
from app.services.audit_service import AuditService
from app.services.course_material_service import CourseMaterialService
from app.services.forum_service import ForumService
from app.services.live_session_service import LiveSessionService
from app.services.payment_service import PaymentService
from app.services.scholarship_service import ScholarshipService
from app.utils.exceptions import NotFoundError, ConflictError, ForbiddenError, AppError
from app.utils.helpers import oid_str

async def _bind_fee_repositories(
    course_repo: CourseRepository = Depends(get_course_repository),
    payment_repo=Depends(get_payment_repository),
):
    from app.services.fee_access import fee_repositories

    token = fee_repositories.set((course_repo, payment_repo))
    try:
        yield
    finally:
        fee_repositories.reset(token)


router = APIRouter(dependencies=[Depends(_bind_fee_repositories)])


async def _course_is_current(course_repo: CourseRepository, course_id: str | None) -> bool:
    """Current learning views only include a course that operational lookup can see."""
    if not course_id:
        return False
    return await course_repo.get_by_id(course_id) is not None


# ==================== Enrollment ====================

@router.post("/enroll/{course_id}", response_model=EnrollmentPublic, status_code=status.HTTP_201_CREATED)
async def enroll_in_course(
    course_id: str,
    payload: EnrollmentCreate,
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
) -> EnrollmentPublic:
    """Enroll current user in a course with personal information."""
    from app.services.enrollment_registration import EnrollmentRegistration

    enrollment = await EnrollmentRegistration(
        enrollment_repo,
        student_repo,
        course_repo,
    ).enroll(current_user.id, course_id, payload)
    return enrollment_to_public(enrollment)


def _page(items: list, total: int, skip: int, limit: int) -> PaginatedResponse:
    return PaginatedResponse(items=items, total=total, skip=clamp_skip(skip), limit=clamp_limit(limit))


async def _course_access(student_id: str, course_id: str, provided, enrollment_repo: EnrollmentRepository):
    """One eligible enrollment for this course.

    A list is only accepted from direct tests that already selected the rows.
    The HTTP dependency passes None, which becomes a single find_one.
    Overdue locks apply when the request bound the fee repositories.
    """
    from app.services.fee_access import OVERDUE_DETAIL, fee_repositories, is_learning_restricted

    if isinstance(provided, list):
        enrollment = next((item for item in provided if getattr(item, "course_id", None) == course_id), None)
    else:
        enrollment = await enrollment_repo.get_access_enrollment(student_id, course_id)
    bound = fee_repositories.get()
    if enrollment is not None and bound is not None:
        course_repo, payment_repo = bound
        course = await course_repo.get_by_id(enrollment.course_id)
        payments = await payment_repo.for_enrollment(enrollment.id)
        price = course.price if course is not None else 0
        if is_learning_restricted(enrollment, payments, datetime.now(timezone.utc), price):
            raise ForbiddenError(OVERDUE_DETAIL)
    return enrollment


_GRADE_POINTS = {
    "A+": 4.0, "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0,
}


async def _performance_summaries(result_repo: ResultRepository, student_id: str):
    """Build GPA inputs from one aggregation.

    The database returns one row per eligible enrollment, one grade count, and
    at most ten recent results. Percentage, stored-grade fallback, highest
    percentage, and the later issued_date tie are applied in that aggregation.
    """
    raw = await result_repo.summarize_for_student(student_id)
    names = {
        oid_str(row["_id"]): row.get("recent_assessment")
        for row in raw.get("recent_names") or []
    }
    summaries: dict[str, dict] = {}
    for row in raw.get("by_enrollment") or []:
        enrollment_id = oid_str(row["_id"])
        summaries[enrollment_id] = {
            "sum": row.get("total_percentage") or 0.0,
            "count": row.get("count") or 0,
            "final_grade": row.get("final_grade"),
            "recent_assessment": names.get(enrollment_id),
        }
    grade_distribution = {
        row["_id"]: row.get("count") or 0
        for row in raw.get("distribution") or []
        if row.get("_id") is not None
    }
    recent = [
        SimpleNamespace(
            id=oid_str(row["_id"]),
            course_id=oid_str(row["course_id"]) if row.get("course_id") is not None else None,
            assessment_name=row.get("assessment_name"),
            assessment_type=row.get("assessment_type"),
            percentage=row.get("percentage") or 0.0,
            grade=row.get("resolved_grade"),
            issued_date=row.get("issued_date"),
        )
        for row in raw.get("recent") or []
    ]
    return summaries, grade_distribution, recent


def _result_public(result) -> ResultPublic:
    return ResultPublic(
        id=result.id,
        student_id=result.student_id,
        course_id=result.course_id,
        enrollment_id=result.enrollment_id,
        assessment_type=result.assessment_type,
        assessment_name=result.assessment_name,
        marks_obtained=result.marks_obtained,
        total_marks=result.total_marks,
        percentage=result.percentage,
        grade=result.grade,
        feedback=result.feedback,
        issued_by=result.issued_by,
        issued_date=result.issued_date,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )


@router.get("/enrollments", response_model=PaginatedResponse[EnrollmentPublic])
async def get_my_enrollments(
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> PaginatedResponse[EnrollmentPublic]:
    """Page the current user's enrollment history. The array is one page, and total is the full count."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        return _page([], 0, skip, limit)
    enrollments, total = await enrollment_repo.page_for_student(student.id, skip=skip, limit=limit)
    return _page([enrollment_to_public(e) for e in enrollments], total, skip, limit)


@router.get("/dashboard")
async def get_student_dashboard(
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    instructor_repo: InstructorRepository = Depends(get_instructor_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    material_service: CourseMaterialService = Depends(get_course_material_service),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> dict:
    """Current courses for the student. enrollments is one page; total is the full current count."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        return {"enrollments": [], "mentors": [], "total": 0, "skip": clamp_skip(skip), "limit": clamp_limit(limit)}

    enrollments, total = await enrollment_repo.page_current_for_student(student.id, skip=skip, limit=limit)
    current = [
        e for e in enrollments
        if e.verified_by_admin and getattr(e, "status", "active") == "active"
    ]
    courses = await course_repo.load_by_ids([e.course_id for e in current])
    instructors = await instructor_repo.load_by_ids(
        [course.instructor_id for course in courses.values() if course.instructor_id]
    )
    users = await user_repo.load_by_ids(
        [instructor.user_id for instructor in instructors.values() if getattr(instructor, "user_id", None)]
    )
    materials_by_course = await material_service.published_for_courses(list(courses))
    result = []
    mentors_map = {}
    seen_courses: set[str] = set()

    for e in current:
        if e.course_id in seen_courses:
            continue
        seen_courses.add(e.course_id)
        course = courses.get(e.course_id)
        if course is None:
            continue
        instructor_name = "Instructor not assigned"
        instructor_specialization = ""
        instructor = instructors.get(course.instructor_id) if course.instructor_id else None
        user = users.get(instructor.user_id) if instructor is not None and record_is_active(instructor) else None
        if instructor is not None and user is not None and record_is_active(user):
            instructor_name = user.full_name or user.email or "Instructor not assigned"
            instructor_specialization = instructor.specialization or ""
            if course.instructor_id not in mentors_map:
                mentors_map[course.instructor_id] = {
                    "id": course.instructor_id,
                    "name": instructor_name,
                    "specialization": instructor_specialization,
                    "user_id": instructor.user_id,
                    "course_id": e.course_id,
                    "course_title": course.title,
                    "enrollment_date": e.enrollment_date.isoformat() if e.enrollment_date else None,
                }

        materials = materials_by_course.get(e.course_id, [])
        seen_material_ids: set[str] = set()
        unique_materials = []
        for material in materials:
            if material.id in seen_material_ids:
                continue
            seen_material_ids.add(material.id)
            unique_materials.append(material)
        total_materials = len(unique_materials)
        progress = e.progress_percentage or 0
        watched = max(0, min(total_materials, round(progress / 100 * total_materials))) if total_materials else 0

        thumbnail_url = None
        video_materials = [m for m in unique_materials if m.material_type == "video" and m.content_url]
        if video_materials:
            first_video = sorted(video_materials, key=lambda m: m.order or 0)[0]
            url = (first_video.content_url or "").strip()
            if "youtu.be/" in url:
                m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{10,})", url)
                if m:
                    thumbnail_url = f"https://img.youtube.com/vi/{m.group(1)}/mqdefault.jpg"
            elif "youtube.com" in url:
                m = re.search(r"(?:v=|embed/)([a-zA-Z0-9_-]{10,})", url)
                if m:
                    thumbnail_url = f"https://img.youtube.com/vi/{m.group(1)}/mqdefault.jpg"

        result.append({
            "id": e.id,
            "course_id": e.course_id,
            "course_title": course.title,
            "instructor_id": course.instructor_id,
            "instructor_name": instructor_name,
            "instructor_specialization": instructor_specialization,
            "progress_percentage": progress,
            "watched_count": watched,
            "total_materials": total_materials,
            "thumbnail_url": thumbnail_url or getattr(course, "image_url", None),
            "image_url": getattr(course, "image_url", None),
            "enrollment_date": e.enrollment_date.isoformat() if e.enrollment_date else None,
        })

    return {
        "enrollments": result,
        "mentors": list(mentors_map.values()),
        "total": total,
        "skip": clamp_skip(skip),
        "limit": clamp_limit(limit),
    }


@router.post("/enrollments/{enrollment_id}/payment-receipt", response_model=EnrollmentPublic)
async def upload_payment_receipt(
    enrollment_id: str,
    payload: PaymentReceiptUpload,
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    audit: AuditService = Depends(get_audit_service),
    payment_repo=Depends(get_payment_repository),
) -> EnrollmentPublic:
    """Upload payment receipt URL for an enrollment."""
    # Get enrollment
    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment not found")
    
    # Verify enrollment belongs to current user
    student = await student_repo.get_by_user_id(current_user.id)
    if not student or enrollment.student_id != student.id:
        raise ForbiddenError("You can only upload receipts for your own enrollments")
    
    from app.services.audit_service import recover_pending_decision, commit_required_decision

    pending = enrollment.audit_pending if isinstance(enrollment.audit_pending, dict) else None

    async def clear_pending():
        return await enrollment_repo.update(enrollment.id, {"audit_pending": None})

    if pending:
        await recover_pending_decision(audit, enrollment, clear_pending)
        enrollment = await enrollment_repo.get_by_id(enrollment_id) or enrollment
    current_state = workflow_state(enrollment)
    if current_state == RECEIPT_UPLOADED and enrollment.payment_receipt_url == payload.receipt_url:
        return enrollment_to_public(enrollment)
    assert_enrollment_transition(
        current_user.role,
        current_state,
        RECEIPT_UPLOADED,
        owns_enrollment=True,
    )
    updates = enrollment_transition_updates(enrollment, RECEIPT_UPLOADED, actor_id=current_user.id)
    updates["payment_receipt_url"] = payload.receipt_url
    updated_enrollment = await commit_required_decision(
        audit,
        lambda data: enrollment_repo.update(enrollment_id, data),
        action="enrollment.receipt_uploaded",
        entity_type="enrollment",
        entity_id=enrollment.id,
        actor_id=current_user.id,
        actor_role=current_user.role,
        previous=enrollment,
        updates=updates,
    )
    if not updated_enrollment:
        raise NotFoundError("Failed to update enrollment")
    if payment_repo is not None and hasattr(payment_repo, "attach_receipt"):
        await payment_repo.attach_receipt(updated_enrollment.id, payload.receipt_url)
    return enrollment_to_public(updated_enrollment)


@router.get("/has-access", response_model=dict)
async def check_lms_access(
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
) -> dict:
    """Check if current user has LMS access (at least one admin-verified enrollment)."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        return {"has_access": False, "message": "Enroll in a course to get LMS access."}
    has_access = await enrollment_repo.has_verified_enrollment(student.id)
    return {
        "has_access": has_access,
        "message": "LMS access granted." if has_access else "Wait for admin payment verification to access LMS.",
    }


@router.get("/enrollments/{enrollment_id}/card")
async def download_enrollment_card(
    enrollment_id: str,
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Download enrollment card PDF — regenerated with latest student & enrollment data."""
    from datetime import datetime, timezone
    from pathlib import Path

    from app.services.enrollment_card_service import EnrollmentCardService

    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment:
        raise NotFoundError("Enrollment not found")

    student = await student_repo.get_by_user_id(current_user.id)
    if not student or enrollment.student_id != student.id:
        raise ForbiddenError("You can only download your own enrollment card")

    if not enrollment.verified_by_admin:
        raise ForbiddenError("Enrollment card is available after admin payment verification")

    course = await course_repo.get_including_archived(enrollment.course_id)
    if not course:
        raise NotFoundError("Course not found")

    student_user = await user_repo.get_by_id(current_user.id)
    if not student_user:
        raise NotFoundError("User not found")

    card_service = EnrollmentCardService()
    card_path, _ = card_service.generate_enrollment_card(
        enrollment=enrollment,
        student=student_user,
        course=course,
    )
    await enrollment_repo.update(
        enrollment_id,
        {"enrollment_card_url": card_path, "updated_at": datetime.now(timezone.utc)},
    )

    file_path = Path("." + card_path) if card_path.startswith("/") else Path(card_path)
    if not file_path.exists():
        raise NotFoundError("Enrollment card file not found")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=f"enrollment_card_{enrollment.enrollment_card_number or enrollment_id}.pdf",
    )


# ==================== Results ====================

@router.get("/results/{course_id}", response_model=PaginatedResponse[ResultPublic])
async def get_my_results(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    result_repo: ResultRepository = Depends(get_result_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[ResultPublic]:
    """Page results for the current user in one course they can access."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return _page([], 0, skip, limit)
    results, total = await result_repo.page_for_student(
        student.id, course_id=course_id, skip=skip, limit=limit
    )
    return _page([_result_public(result) for result in results], total, skip, limit)


@router.get("/results", response_model=PaginatedResponse[ResultPublic])
async def get_all_my_results(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    result_repo: ResultRepository = Depends(get_result_repository),
) -> PaginatedResponse[ResultPublic]:
    """Page every stored result for the current user, including historical rows."""
    student, _enrollments = verified_data
    results, total = await result_repo.page_for_student(student.id, skip=skip, limit=limit)
    return _page([_result_public(result) for result in results], total, skip, limit)


# ==================== Attendance ====================

@router.post("/attendance/check-in", status_code=status.HTTP_201_CREATED)
async def submit_attendance_check_in(
    payload: AttendanceCheckIn,
    current_user: User = Depends(get_current_user),
    student_repo: StudentRepository = Depends(get_student_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    claims=Depends(get_attendance_claim_service),
    payment_repo=Depends(get_payment_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
):
    """Record a check-in. It stays pending until an administrator approves it."""
    student = await student_repo.get_by_user_id(current_user.id)
    if student is None:
        raise ForbiddenError("A student profile is required to check in")
    enrollment = await enrollment_repo.get_access_enrollment(student.id, payload.course_id)
    if enrollment is None:
        raise ForbiddenError("You can only check in for a course you are enrolled in")
    course = await course_repo.get_by_id(payload.course_id)
    payments = await payment_repo.for_enrollment(enrollment.id)
    claim = await claims.submit_check_in(
        student_id=student.id,
        course_id=payload.course_id,
        enrollment=enrollment,
        payments=payments,
        total_fee=course.price if course is not None else 0,
    )
    return claim_to_public(claim)


@router.get("/attendance/claims", response_model=PaginatedResponse[AttendanceClaimPublic])
async def list_my_attendance_claims(
    course_id: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    student_repo: StudentRepository = Depends(get_student_repository),
    claims=Depends(get_attendance_claim_service),
) -> PaginatedResponse[AttendanceClaimPublic]:
    student = await student_repo.get_by_user_id(current_user.id)
    if student is None:
        return _page([], 0, skip, limit)
    rows, total = await claims._claims.page_for_student_course(student.id, course_id, skip=skip, limit=limit)
    return _page([claim_to_public(item) for item in rows], total, skip, limit)


@router.get("/attendance/corrections", response_model=PaginatedResponse[AttendanceCorrectionPublic])
async def list_my_attendance_corrections(
    course_id: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    student_repo: StudentRepository = Depends(get_student_repository),
    service: AttendanceCorrectionService = Depends(get_attendance_correction_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[AttendanceCorrectionPublic]:
    """List correction requests for the signed-in student."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        return PaginatedResponse(items=[], total=0, skip=skip, limit=limit)
    if course_id and await enrollment_repo.get_access_enrollment(student.id, course_id) is None:
        return PaginatedResponse(items=[], total=0, skip=skip, limit=limit)
    corrections, total = await service.list_corrections(
        skip=skip,
        limit=limit,
        student_id=student.id,
        course_id=course_id,
    )
    return PaginatedResponse(
        items=[correction_to_public(item) for item in corrections],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/attendance/{attendance_id}/corrections",
    response_model=AttendanceCorrectionPublic,
    status_code=status.HTTP_201_CREATED,
)
async def request_attendance_correction(
    attendance_id: str,
    payload: AttendanceCorrectionCreate,
    current_user: User = Depends(get_current_user),
    student_repo: StudentRepository = Depends(get_student_repository),
    service: AttendanceCorrectionService = Depends(get_attendance_correction_service),
    attendance_repo: AttendanceRepository = Depends(get_attendance_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> AttendanceCorrectionPublic:
    """Ask for a correction of the signed-in student's own attendance mark."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        raise ForbiddenError("A student profile is required to request an attendance correction")
    attendance = await attendance_repo.get_by_id(attendance_id)
    if (
        attendance is None
        or attendance.student_id != student.id
        or await enrollment_repo.get_access_enrollment(student.id, attendance.course_id) is None
    ):
        raise NotFoundError("Attendance not found")
    correction = await service.request_correction(
        attendance_id=attendance_id,
        student_id=student.id,
        requester_id=current_user.id,
        reason=payload.reason,
        requested_status=payload.requested_status,
    )
    return correction_to_public(correction)


@router.get("/attendance/{course_id}", response_model=PaginatedResponse[AttendancePublic])
async def get_my_attendance(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    attendance_repo: AttendanceRepository = Depends(get_attendance_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[AttendancePublic]:
    """Page attendance for a course the signed-in student can access."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student or await enrollment_repo.get_access_enrollment(student.id, course_id) is None:
        return _page([], 0, skip, limit)
    attendances, total = await attendance_repo.page_for_student_course(
        student.id, course_id, skip=skip, limit=limit
    )
    return _page([
        AttendancePublic(
            id=a.id,
            student_id=a.student_id,
            course_id=a.course_id,
            enrollment_id=a.enrollment_id,
            date=a.date,
            status=a.status,
            marked_by=a.marked_by,
            notes=a.notes,
            absence_reason=a.absence_reason,
            absence_reason_submitted_at=a.absence_reason_submitted_at,
            is_excused=a.is_excused,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in attendances
    ], total, skip, limit)


@router.get("/attendance/{course_id}/stats", response_model=dict)
async def get_attendance_stats(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    attendance_repo: AttendanceRepository = Depends(get_attendance_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> dict:
    """Attendance statistics for one course the student can access."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return {"present": 0, "absent": 0, "late": 0, "excused": 0, "total": 0, "percentage": 0.0}
    stats = await attendance_repo.get_attendance_stats(student.id, course_id)
    total = stats.get("total", 0)
    present = stats.get("present", 0)
    percentage = (present / total * 100) if total > 0 else 0.0
    stats["percentage"] = round(percentage, 2)
    return stats


@router.post("/attendance/{attendance_id}/submit-reason", response_model=AttendancePublic)
async def submit_absence_reason(
    attendance_id: str,
    payload: AbsenceReasonSubmit,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    attendance_service: AttendanceService = Depends(get_attendance_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> AttendancePublic:
    """Submit an absence reason for the student's own eligible course."""
    student, provided = verified_data
    attendance = await attendance_service.get_attendance(attendance_id)
    if (
        attendance.student_id != student.id
        or await _course_access(student.id, attendance.course_id, provided, enrollment_repo) is None
    ):
        raise NotFoundError("Attendance not found")
    attendance = await attendance_service.submit_absence_reason(attendance_id, payload.absence_reason)
    
    return AttendancePublic(
        id=attendance.id,
        student_id=attendance.student_id,
        course_id=attendance.course_id,
        enrollment_id=attendance.enrollment_id,
        date=attendance.date,
        status=attendance.status,
        marked_by=attendance.marked_by,
        notes=attendance.notes,
        absence_reason=attendance.absence_reason,
        absence_reason_submitted_at=attendance.absence_reason_submitted_at,
        is_excused=attendance.is_excused,
        created_at=attendance.created_at,
        updated_at=attendance.updated_at,
    )


# ==================== Certificates ====================

@router.get("/certificates", response_model=PaginatedResponse[CertificatePublic])
async def get_my_certificates(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    certificate_repo: CertificateRepository = Depends(get_certificate_repository),
) -> PaginatedResponse[CertificatePublic]:
    """Page certificates for the current user."""
    student, _ = verified_data
    certificates, total = await certificate_repo.page_for_student(student.id, skip=skip, limit=limit)
    return _page([
        CertificatePublic(
            id=c.id,
            student_id=c.student_id,
            course_id=c.course_id,
            enrollment_id=c.enrollment_id,
            certificate_number=c.certificate_number,
            issue_date=c.issue_date,
            completion_date=c.completion_date,
            grade=c.grade,
            issued_by=c.issued_by,
            certificate_url=c.certificate_url,
            is_verified=c.is_verified,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in certificates
    ], total, skip, limit)


@router.get("/certificates/{course_id}", response_model=CertificatePublic | None)
async def get_course_certificate(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    certificate_repo: CertificateRepository = Depends(get_certificate_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> CertificatePublic | None:
    """Get certificate for current user in a specific course. Requires admin-verified enrollment."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return None
    certificate = await certificate_repo.get_by_student_and_course(student.id, course_id)
    if not certificate:
        return None
    
    return CertificatePublic(
        id=certificate.id,
        student_id=certificate.student_id,
        course_id=certificate.course_id,
        enrollment_id=certificate.enrollment_id,
        certificate_number=certificate.certificate_number,
        issue_date=certificate.issue_date,
        completion_date=certificate.completion_date,
        grade=certificate.grade,
        issued_by=certificate.issued_by,
        certificate_url=certificate.certificate_url,
        is_verified=certificate.is_verified,
        created_at=certificate.created_at,
        updated_at=certificate.updated_at,
    )


# ==================== Scholarships ====================

@router.get("/scholarships", response_model=PaginatedResponse[ScholarshipStatus])
async def get_my_scholarships(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    scholarship_service: ScholarshipService = Depends(get_scholarship_service),
    course_repo: CourseRepository = Depends(get_course_repository),
) -> PaginatedResponse[ScholarshipStatus]:
    """Page scholarships for the current user. Course titles are loaded in one batch."""
    student, _ = verified_data
    scholarships, total = await scholarship_service.list_scholarships(
        skip=skip,
        limit=limit,
        student_id=student.id,
    )
    courses = await course_repo.load_by_ids(
        [item.course_id for item in scholarships if item.course_id],
        include_archived=True,
    )
    result = []
    for scholarship in scholarships:
        course = courses.get(scholarship.course_id) if scholarship.course_id else None
        course_title = course.title if course else None
        
        # Calculate days remaining
        days_remaining = None
        if scholarship.end_date:
            delta = scholarship.end_date - datetime.now(timezone.utc)
            days_remaining = max(0, delta.days)
        
        # Check if at risk (one absence away from termination)
        is_at_risk = (
            scholarship.status == "active" and
            scholarship.current_month_absences >= scholarship.max_absences_per_month - 1
        )
        
        result.append(
            ScholarshipStatus(
                id=scholarship.id,
                course_id=scholarship.course_id,
                course_title=course_title,
                scholarship_type=scholarship.scholarship_type,
                amount=scholarship.amount,
                status=scholarship.status,
                current_month_absences=scholarship.current_month_absences,
                max_absences_per_month=scholarship.max_absences_per_month,
                days_remaining=days_remaining,
                is_at_risk=is_at_risk,
            )
        )
    
    return _page(result, total, skip, limit)


@router.get("/scholarships/{course_id}", response_model=PaginatedResponse[ScholarshipPublic])
async def get_course_scholarships(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    scholarship_service: ScholarshipService = Depends(get_scholarship_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[ScholarshipPublic]:
    """Page scholarships for the current user in one course."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return _page([], 0, skip, limit)
    scholarships, total = await scholarship_service.page_student_course_scholarships(
        student.id, course_id, skip=skip, limit=limit
    )
    return _page([
        ScholarshipPublic(
            id=s.id,
            student_id=s.student_id,
            course_id=s.course_id,
            enrollment_id=s.enrollment_id,
            scholarship_type=s.scholarship_type,
            amount=s.amount,
            status=s.status,
            start_date=s.start_date,
            end_date=s.end_date,
            termination_reason=s.termination_reason,
            terminated_at=s.terminated_at,
            terminated_by=s.terminated_by,
            max_absences_per_month=s.max_absences_per_month,
            current_month_absences=s.current_month_absences,
            current_month_start=s.current_month_start,
            notes=s.notes,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in scholarships
    ], total, skip, limit)


@router.get("/scholarships/{scholarship_id}/details", response_model=ScholarshipPublic)
async def get_scholarship_details(
    scholarship_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    scholarship_service: ScholarshipService = Depends(get_scholarship_service),
) -> ScholarshipPublic:
    """Get detailed information about a specific scholarship. Requires admin-verified enrollment."""
    student, _ = verified_data
    
    scholarship = await scholarship_service.get_scholarship(scholarship_id)
    
    # Verify scholarship belongs to current user
    if scholarship.student_id != student.id:
        raise NotFoundError("Scholarship not found")
    
    return ScholarshipPublic(
        id=scholarship.id,
        student_id=scholarship.student_id,
        course_id=scholarship.course_id,
        enrollment_id=scholarship.enrollment_id,
        scholarship_type=scholarship.scholarship_type,
        amount=scholarship.amount,
        status=scholarship.status,
        start_date=scholarship.start_date,
        end_date=scholarship.end_date,
        termination_reason=scholarship.termination_reason,
        terminated_at=scholarship.terminated_at,
        terminated_by=scholarship.terminated_by,
        max_absences_per_month=scholarship.max_absences_per_month,
        current_month_absences=scholarship.current_month_absences,
        current_month_start=scholarship.current_month_start,
        notes=scholarship.notes,
        created_at=scholarship.created_at,
        updated_at=scholarship.updated_at,
    )


# ==================== Course Materials ====================

@router.get("/courses/{course_id}/materials", response_model=PaginatedResponse[CourseMaterialPublic])
async def get_course_materials(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    material_service: CourseMaterialService = Depends(get_course_material_service),
    course_repo: CourseRepository = Depends(get_course_repository),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[CourseMaterialPublic]:
    """Page published materials for a course."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return _page([], 0, skip, limit)
    if not await _course_is_current(course_repo, course_id):
        return _page([], 0, skip, limit)
    materials, total = await material_service.list_course_materials(
        course_id, skip=skip, limit=limit, published_only=True
    )
    return _page([
        CourseMaterialPublic(
            id=m.id,
            course_id=m.course_id,
            title=m.title,
            description=m.description,
            material_type=m.material_type,
            content_url=m.content_url,
            file_path=m.file_path,
            file_size=m.file_size,
            duration_minutes=m.duration_minutes,
            order=m.order,
            is_published=m.is_published,
            is_required=m.is_required,
            created_by=m.created_by,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in materials
    ], total, skip, limit)


# ==================== Assignments ====================

@router.get("/courses/{course_id}/assignments", response_model=PaginatedResponse[AssignmentPublic])
async def get_course_assignments(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    assignment_service: AssignmentService = Depends(get_assignment_service),
    course_repo: CourseRepository = Depends(get_course_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[AssignmentPublic]:
    """Page published assignments for a course."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return _page([], 0, skip, limit)
    if not await _course_is_current(course_repo, course_id):
        return _page([], 0, skip, limit)
    assignments, total = await assignment_service.list_course_assignments(
        course_id, skip=skip, limit=limit, published_only=True
    )
    return _page([
        AssignmentPublic(
            id=a.id,
            course_id=a.course_id,
            title=a.title,
            description=a.description,
            instructions=a.instructions,
            due_date=a.due_date,
            max_marks=a.max_marks,
            assignment_type=a.assignment_type,
            is_published=a.is_published,
            created_by=a.created_by,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in assignments
    ], total, skip, limit)


@router.get("/assignments/{assignment_id}/submission", response_model=AssignmentSubmissionPublic | None)
async def get_my_submission(
    assignment_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    assignment_service: AssignmentService = Depends(get_assignment_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> AssignmentSubmissionPublic | None:
    """Get current user's submission for an assignment. Requires admin-verified enrollment."""
    student, provided = verified_data
    assignment = await assignment_service.get_assignment(assignment_id)
    enrollment = await _course_access(student.id, assignment.course_id, provided, enrollment_repo)
    if not enrollment:
        return None
    
    submission = await assignment_service.get_submission(student.id, assignment_id)
    if not submission:
        return None
    
    return AssignmentSubmissionPublic(
        id=submission.id,
        assignment_id=submission.assignment_id,
        student_id=submission.student_id,
        course_id=submission.course_id,
        enrollment_id=submission.enrollment_id,
        submission_text=submission.submission_text,
        file_urls=submission.file_urls,
        submitted_at=submission.submitted_at,
        status=submission.status,
        marks_obtained=submission.marks_obtained,
        feedback=submission.feedback,
        graded_by=submission.graded_by,
        graded_at=submission.graded_at,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


@router.post("/assignments/{assignment_id}/submit", response_model=AssignmentSubmissionPublic, status_code=status.HTTP_201_CREATED)
async def submit_assignment(
    assignment_id: str,
    payload: AssignmentSubmissionCreate,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    assignment_service: AssignmentService = Depends(get_assignment_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> AssignmentSubmissionPublic:
    """Submit an assignment. Requires admin-verified enrollment."""
    student, provided = verified_data
    assignment = await assignment_service.get_assignment(assignment_id)
    enrollment = await _course_access(student.id, assignment.course_id, provided, enrollment_repo)
    if not enrollment:
        raise NotFoundError("Not enrolled in this course")
    
    submission = await assignment_service.submit_assignment(
        payload,
        student.id,
        assignment.course_id,
        enrollment.id,
    )
    
    return AssignmentSubmissionPublic(
        id=submission.id,
        assignment_id=submission.assignment_id,
        student_id=submission.student_id,
        course_id=submission.course_id,
        enrollment_id=submission.enrollment_id,
        submission_text=submission.submission_text,
        file_urls=submission.file_urls,
        submitted_at=submission.submitted_at,
        status=submission.status,
        marks_obtained=submission.marks_obtained,
        feedback=submission.feedback,
        graded_by=submission.graded_by,
        graded_at=submission.graded_at,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


# ==================== Live Sessions ====================

def _session_public(session) -> LiveSessionPublic:
    return LiveSessionPublic(
        id=session.id,
        course_id=session.course_id,
        title=session.title,
        description=session.description,
        session_type=session.session_type,
        start_time=session.start_time,
        end_time=session.end_time,
        meeting_link=session.meeting_link,
        location=session.location,
        instructor_id=session.instructor_id,
        max_participants=session.max_participants,
        recording_url=session.recording_url,
        is_recorded=session.is_recorded,
        status=session.status,
        created_by=session.created_by,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("/courses/{course_id}/sessions", response_model=PaginatedResponse[LiveSessionPublic])
async def get_course_sessions(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    session_service: LiveSessionService = Depends(get_live_session_service),
    course_repo: CourseRepository = Depends(get_course_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[LiveSessionPublic]:
    """Page live sessions for a course."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return _page([], 0, skip, limit)
    if not await _course_is_current(course_repo, course_id):
        return _page([], 0, skip, limit)
    sessions, total = await session_service.list_course_sessions(course_id, skip=skip, limit=limit)
    return _page([_session_public(session) for session in sessions], total, skip, limit)


@router.get("/sessions/upcoming", response_model=PaginatedResponse[LiveSessionPublic])
async def get_upcoming_sessions(
    course_id: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    session_service: LiveSessionService = Depends(get_live_session_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[LiveSessionPublic]:
    """Page upcoming sessions for the student's operational courses."""
    student, provided = verified_data
    if isinstance(provided, list):
        course_ids = [course_id] if course_id else [enrollment.course_id for enrollment in provided]
        allowed = {enrollment.course_id for enrollment in provided}
    else:
        allowed = set(await enrollment_repo.verified_course_ids(student.id))
        course_ids = [course_id] if course_id else list(allowed)
    if course_id and course_id not in allowed:
        return _page([], 0, skip, limit)
    sessions, total = await session_service.page_upcoming_for_courses(
        course_ids, skip=skip, limit=limit
    )
    return _page([_session_public(session) for session in sessions], total, skip, limit)


# ==================== Announcements ====================

@router.get("/announcements", response_model=PaginatedResponse[AnnouncementPublic])
async def get_announcements(
    course_id: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    announcement_service: AnnouncementService = Depends(get_announcement_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[AnnouncementPublic]:
    """Page published announcements. A course id requires access to that course."""
    student, provided = verified_data
    if course_id and await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return _page([], 0, skip, limit)
    announcements, total = await announcement_service.page_published(course_id, skip=skip, limit=limit)
    return _page([
        AnnouncementPublic(
            id=a.id,
            course_id=a.course_id,
            title=a.title,
            content=a.content,
            priority=a.priority,
            is_published=a.is_published,
            published_at=a.published_at,
            expires_at=a.expires_at,
            created_by=a.created_by,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in announcements
    ], total, skip, limit)


# ==================== Course Progress ====================

@router.get("/enrollments/{enrollment_id}/progress", response_model=dict)
async def get_course_progress(
    enrollment_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    material_service: CourseMaterialService = Depends(get_course_material_service),
    assignment_service: AssignmentService = Depends(get_assignment_service),
    course_repo: CourseRepository = Depends(get_course_repository),
) -> dict:
    """Get detailed course progress for an enrollment. Requires admin-verified enrollment."""
    student, _provided = verified_data
    enrollment = await enrollment_repo.get_owned_verified(student.id, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment not found")
    await _course_access(student.id, enrollment.course_id, [enrollment], enrollment_repo)

    if await _course_is_current(course_repo, enrollment.course_id):
        total_materials = await material_service.count_published(enrollment.course_id)
        total_assignments = await assignment_service.count_published(enrollment.course_id)
    else:
        total_materials = 0
        total_assignments = 0

    # Progress percentage stays the value stored on the enrollment.
    # Counts use the same published, active filter as the course content pages.
    progress_percentage = enrollment.progress_percentage
    total_items = total_materials + total_assignments
    completed_items = 0

    return {
        "enrollment_id": enrollment.id,
        "course_id": enrollment.course_id,
        "progress_percentage": progress_percentage,
        "total_materials": total_materials,
        "total_assignments": total_assignments,
        "total_items": total_items,
        "completed_items": completed_items,
        "status": enrollment.status,
        "enrollment_date": enrollment.enrollment_date,
        "completion_date": enrollment.completion_date,
    }


@router.patch("/enrollments/{enrollment_id}/progress", response_model=EnrollmentPublic)
async def update_course_progress(
    enrollment_id: str,
    progress_percentage: float,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> EnrollmentPublic:
    """Update course progress for an enrollment. Requires admin-verified enrollment."""
    student, _provided = verified_data
    enrollment = await enrollment_repo.get_owned_verified(student.id, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment not found")
    await _course_access(student.id, enrollment.course_id, [enrollment], enrollment_repo)

    # Validate progress percentage
    if progress_percentage < 0 or progress_percentage > 100:
        raise ValueError("Progress percentage must be between 0 and 100")
    
    # Update progress
    updated = await enrollment_repo.update(
        enrollment_id,
        {
            "progress_percentage": progress_percentage,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    
    if not updated:
        raise NotFoundError("Enrollment not found")
    
    # Update status to completed if progress is 100%
    if progress_percentage >= 100 and enrollment.status != "completed":
        await enrollment_repo.update(
            enrollment_id,
            {
                "status": "completed",
                "completion_date": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        updated = await enrollment_repo.get_by_id(enrollment_id)
    
    return enrollment_to_public(updated)


# ==================== Performance Dashboard ====================

@router.get("/performance/dashboard", response_model=dict)
async def get_performance_dashboard(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    result_repo: ResultRepository = Depends(get_result_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    attendance_repo: AttendanceRepository = Depends(get_attendance_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> dict:
    """Performance summary. course_performance and attendance_summary are one page of enrollments.

    overall_gpa, grade_distribution, and recent_results cover every verified enrollment.
    Attendance percentage is present divided by total marks, matching the course stats route.
    GPA and grade distribution come from one aggregation. Recent results are at most ten rows.
    """
    student, _provided = verified_data
    page_start = clamp_skip(skip)
    page_size = clamp_limit(limit)
    status_counts = await enrollment_repo.count_verified_statuses(student.id)
    page_enrollments, verified_total = await enrollment_repo.page_verified(
        student.id, skip=page_start, limit=page_size
    )
    summaries, grade_distribution, recent_results = await _performance_summaries(
        result_repo, student.id
    )

    courses = await course_repo.load_by_ids(
        [enrollment.course_id for enrollment in page_enrollments],
        include_archived=True,
    )
    attendance_by_course = await attendance_repo.stats_for_courses(
        student.id,
        [enrollment.course_id for enrollment in page_enrollments],
    )

    course_performance = []
    total_grade_points = 0.0
    total_courses_with_grades = 0
    for bucket in summaries.values():
        total_grade_points += _GRADE_POINTS.get(bucket["final_grade"], 0.0)
        total_courses_with_grades += 1
    for enrollment in page_enrollments:
        bucket = summaries.get(enrollment.id)
        if not bucket:
            continue
        course = courses.get(enrollment.course_id)
        course_avg = bucket["sum"] / bucket["count"]
        final_grade = bucket["final_grade"]
        course_performance.append({
            "course_id": enrollment.course_id,
            "course_title": course.title if course else "Unknown",
            "enrollment_status": enrollment.status,
            "progress_percentage": enrollment.progress_percentage,
            "average_percentage": round(course_avg, 2),
            "final_grade": final_grade,
            "grade_point": _GRADE_POINTS.get(final_grade, 0.0),
            "total_assessments": bucket["count"],
            "recent_assessment": bucket["recent_assessment"],
        })

    overall_gpa = (total_grade_points / total_courses_with_grades) if total_courses_with_grades > 0 else 0.0
    recent_results_data = [
        {
            "id": r.id,
            "course_id": r.course_id,
            "assessment_name": r.assessment_name,
            "assessment_type": r.assessment_type,
            "percentage": round(r.percentage, 2),
            "grade": r.grade,
            "issued_date": r.issued_date.isoformat(),
        }
        for r in recent_results
    ]
    
    attendance_summary = {}
    for enrollment in page_enrollments:
        course = courses.get(enrollment.course_id)
        stats = attendance_by_course.get(enrollment.course_id) or {
            "present": 0, "absent": 0, "late": 0, "excused": 0, "total": 0,
        }
        if course:
            attended = stats.get("total", 0)
            present = stats.get("present", 0)
            percentage = round((present / attended * 100) if attended else 0.0, 2)
            attendance_summary[enrollment.course_id] = {
                "course_title": course.title,
                "present": present,
                "absent": stats.get("absent", 0),
                "late": stats.get("late", 0),
                "excused": stats.get("excused", 0),
                "total": attended,
                "percentage": percentage,
            }
    
    return {
        "overall_gpa": round(overall_gpa, 2),
        "total_courses": verified_total,
        "completed_courses": status_counts.get("completed", 0),
        "active_courses": status_counts.get("active", 0),
        "course_performance": course_performance,
        "grade_distribution": grade_distribution,
        "recent_results": recent_results_data,
        "attendance_summary": attendance_summary,
        "skip": page_start,
        "limit": page_size,
    }


# ==================== Calendar Events ====================

@router.get("/calendar/events", response_model=PaginatedResponse[CalendarEventPublic])
async def get_my_calendar_events(
    start_date: str | None = Query(default=None, description="Start date (ISO format)"),
    end_date: str | None = Query(default=None, description="End date (ISO format)"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    calendar_service: CalendarEventService = Depends(get_calendar_event_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[CalendarEventPublic]:
    """Page calendar events for verified enrollments. Archived parent courses are omitted."""
    student, provided = verified_data
    if isinstance(provided, list):
        course_ids = [enrollment.course_id for enrollment in provided]
    else:
        course_ids = await enrollment_repo.verified_course_ids(student.id)
    start = datetime.fromisoformat(start_date.replace('Z', '+00:00')) if start_date else None
    end = datetime.fromisoformat(end_date.replace('Z', '+00:00')) if end_date else None
    events, total = await calendar_service.page_student_events(
        course_ids, start, end, skip=skip, limit=limit
    )
    return _page([
        CalendarEventPublic(
            id=e.id,
            course_id=e.course_id,
            event_type=e.event_type,
            title=e.title,
            description=e.description,
            start_time=e.start_time,
            end_time=e.end_time,
            location=e.location,
            meeting_link=e.meeting_link,
            related_entity_type=e.related_entity_type,
            related_entity_id=e.related_entity_id,
            is_all_day=e.is_all_day,
            created_by=e.created_by,
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in events
    ], total, skip, limit)


# ==================== Payments ====================

def _payment_public(payment, *, receipt_url: str | None = None, verification_status: str | None = None, course_title: str | None = None) -> PaymentPublic:
    linked = payment.receipt_url or receipt_url
    return PaymentPublic(
        id=payment.id,
        student_id=payment.student_id,
        course_id=payment.course_id,
        enrollment_id=payment.enrollment_id,
        amount=payment.amount,
        currency=payment.currency,
        payment_method=payment.payment_method,
        payment_status=payment.payment_status,
        transaction_id=payment.transaction_id,
        invoice_number=payment.invoice_number,
        invoice_url=payment.invoice_url,
        payment_date=payment.payment_date,
        due_date=payment.due_date,
        scholarship_discount=payment.scholarship_discount,
        notes=payment.notes,
        created_by=payment.created_by,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        receipt_url=linked,
        receipt_available=bool(linked),
        verification_status=verification_status,
        course_title=course_title,
    )


@router.get("/payments", response_model=PaginatedResponse[PaymentPublic])
async def get_my_payments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_student_portal()),
    payment_service: PaymentService = Depends(get_payment_service),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
) -> PaginatedResponse[PaymentPublic]:
    """Page the current student's ledger payments, including linked receipts."""
    student, _ = verified_data
    if student is None:
        return _page([], 0, skip, limit)
    payments, total = await payment_service.list_payments(skip, limit, student_id=student.id)
    enrollments = {}
    courses = {}
    if isinstance(enrollment_repo, EnrollmentRepository):
        owned, _count = await enrollment_repo.page_for_student(student.id, skip=0, limit=100)
        enrollments = {item.id: item for item in owned}
    if isinstance(course_repo, CourseRepository):
        courses = await course_repo.load_by_ids([item.course_id for item in payments if item.course_id])
    items = []
    for payment in payments:
        enrollment = enrollments.get(payment.enrollment_id or "")
        course = courses.get(payment.course_id or "")
        items.append(_payment_public(
            payment,
            receipt_url=getattr(enrollment, "payment_receipt_url", None) if enrollment else None,
            verification_status=workflow_state(enrollment) if enrollment else None,
            course_title=course.title if course is not None else None,
        ))
    return _page(items, total, skip, limit)


@router.get("/fee-history")
async def get_fee_history(
    portal: tuple = Depends(get_student_portal()),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    payment_repo=Depends(get_payment_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    payment_service: PaymentService = Depends(get_payment_service),
) -> dict:
    """Fee obligations and ledger payments. Available before learning access is granted."""
    from app.services.fee_access import fee_summary

    student, _ = portal
    if student is None:
        return {"payments": [], "obligations": []}
    payments, _total = await payment_service.list_payments(0, 100, student_id=student.id)
    enrollments, _count = await enrollment_repo.page_for_student(student.id, skip=0, limit=100)
    courses = await course_repo.load_by_ids([item.course_id for item in enrollments])
    repaired = []
    for enrollment in enrollments:
        current = await payment_service.reconcile_enrollment(
            enrollment.id,
            courses=course_repo,
            enrollments=enrollment_repo,
            actor_id=student.id,
            actor_role="user",
        )
        repaired.append(current or enrollment)
    enrollments = repaired
    by_enrollment = {item.id: item for item in enrollments}
    now = datetime.now(timezone.utc)
    history = []
    for payment in payments:
        enrollment = by_enrollment.get(payment.enrollment_id or "")
        course = courses.get(payment.course_id or "")
        history.append(_payment_public(
            payment,
            receipt_url=getattr(enrollment, "payment_receipt_url", None) if enrollment else None,
            verification_status=workflow_state(enrollment) if enrollment else None,
            course_title=course.title if course is not None else None,
        ).model_dump())
    obligations = []
    for enrollment in enrollments:
        course = courses.get(enrollment.course_id)
        rows = await payment_repo.for_enrollment(enrollment.id)
        obligations.append(fee_summary(
            enrollment,
            rows,
            now,
            course.price if course is not None else 0,
            course.title if course is not None else None,
        ))
    return {"payments": history, "obligations": obligations}


# ==================== Forum ====================

def _forum_public(post, author_name: str | None, reply_count: int) -> ForumPostPublic:
    return ForumPostPublic(
        id=post.id,
        course_id=post.course_id,
        parent_post_id=post.parent_post_id,
        author_id=post.author_id,
        author_name=author_name,
        title=post.title,
        content=post.content,
        post_type=post.post_type,
        is_resolved=post.is_resolved,
        is_pinned=post.is_pinned,
        upvotes=post.upvotes,
        downvotes=post.downvotes,
        views=post.views,
        reply_count=reply_count,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


@router.get("/courses/{course_id}/forum", response_model=PaginatedResponse[ForumPostPublic])
async def get_forum_posts(
    course_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[ForumPostPublic]:
    """Page forum posts. Authors and reply counts are loaded in batches."""
    student, provided = verified_data
    if await _course_access(student.id, course_id, provided, enrollment_repo) is None:
        return _page([], 0, skip, limit)
    posts, total = await forum_service.page_course_posts(
        course_id, skip=skip, limit=limit, top_level_only=True
    )
    authors = await user_repo.load_by_ids([post.author_id for post in posts])
    counts = await forum_service.reply_counts([post.id for post in posts])
    return _page(
        [
            _forum_public(
                post,
                authors[post.author_id].full_name if post.author_id in authors else None,
                counts.get(post.id, 0),
            )
            for post in posts
        ],
        total,
        skip,
        limit,
    )


@router.get("/forum/posts/{post_id}", response_model=ForumPostPublic)
async def get_forum_post(
    post_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> ForumPostPublic:
    """Get a forum post with replies. Requires admin-verified enrollment for this course."""
    student, provided = verified_data
    post = await forum_service.get_post(post_id, operational=True)
    if await _course_access(student.id, post.course_id, provided, enrollment_repo) is None:
        raise NotFoundError("Forum post not found")
    author = await user_repo.get_by_id(post.author_id)
    counts = await forum_service.reply_counts([post.id])
    return _forum_public(post, author.full_name if author else None, counts.get(post.id, 0))


@router.get("/forum/posts/{post_id}/replies", response_model=PaginatedResponse[ForumPostPublic])
async def get_forum_replies(
    post_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> PaginatedResponse[ForumPostPublic]:
    """Page replies. Authors and nested reply counts are loaded in batches."""
    student, provided = verified_data
    parent_post = await forum_service.get_post(post_id, operational=True)
    if await _course_access(student.id, parent_post.course_id, provided, enrollment_repo) is None:
        raise NotFoundError("Forum post not found")
    replies, total = await forum_service.page_replies(post_id, skip=skip, limit=limit)
    authors = await user_repo.load_by_ids([reply.author_id for reply in replies])
    counts = await forum_service.reply_counts([reply.id for reply in replies])
    return _page(
        [
            _forum_public(
                reply,
                authors[reply.author_id].full_name if reply.author_id in authors else None,
                counts.get(reply.id, 0),
            )
            for reply in replies
        ],
        total,
        skip,
        limit,
    )


@router.post("/forum/posts", response_model=ForumPostPublic, status_code=status.HTTP_201_CREATED)
async def create_forum_post(
    payload: ForumPostCreate,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> ForumPostPublic:
    """Create a new forum post. Requires admin-verified enrollment for this course."""
    student, provided = verified_data
    if await _course_access(student.id, payload.course_id, provided, enrollment_repo) is None:
        raise ForbiddenError("Not enrolled in this course")
    post = await forum_service.create_post(payload, student.user_id)
    author = await user_repo.get_by_id(post.author_id)
    counts = await forum_service.reply_counts([post.id])
    return _forum_public(post, author.full_name if author else None, counts.get(post.id, 0))


@router.post("/forum/posts/{post_id}/vote", response_model=ForumPostPublic)
async def vote_forum_post(
    post_id: str,
    payload: ForumVote,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
) -> ForumPostPublic:
    """Vote on a forum post. Requires admin-verified enrollment for this course."""
    student, provided = verified_data
    existing_post = await forum_service.get_post(post_id, operational=True)
    if await _course_access(student.id, existing_post.course_id, provided, enrollment_repo) is None:
        raise NotFoundError("Forum post not found")
    post = await forum_service.vote_post(post_id, payload)
    author = await user_repo.get_by_id(post.author_id)
    counts = await forum_service.reply_counts([post.id])
    return _forum_public(post, author.full_name if author else None, counts.get(post.id, 0))
