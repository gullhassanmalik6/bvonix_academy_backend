"""
LMS (Learning Management System) routes for students.

Why: Separate LMS routes for student-facing features like enrollment,
results, attendance, and certificates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse

from app.core.auth import get_current_user
from app.core.dependencies import (
    get_announcement_service,
    get_require_verified_enrollment,
    get_assignment_service,
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
)
from app.models.user import User
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
from app.schemas.certificate import CertificatePublic
from app.schemas.scholarship import ScholarshipPublic, ScholarshipStatus
from app.services.announcement_service import AnnouncementService
from app.services.assignment_service import AssignmentService
from app.services.attendance_service import AttendanceService
from app.services.calendar_event_service import CalendarEventService
from app.services.course_material_service import CourseMaterialService
from app.services.forum_service import ForumService
from app.services.live_session_service import LiveSessionService
from app.services.payment_service import PaymentService
from app.services.scholarship_service import ScholarshipService
from app.utils.exceptions import NotFoundError, ConflictError, ForbiddenError, AppError
from app.utils.helpers import oid_str

router = APIRouter()


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
    # Get or create student profile
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        # Create student profile if doesn't exist
        student = await student_repo.create_student(
            user_id=current_user.id,
            enrollment_date=datetime.now(timezone.utc),
        )
    
    # Check if course exists
    course = await course_repo.get_by_id(course_id)
    if not course:
        raise NotFoundError("Course not found")
    
    # Check if already enrolled
    existing = await enrollment_repo.get_by_student_and_course(student.id, course_id)
    if existing:
        raise ConflictError("Already enrolled in this course")
    
    # Create enrollment with personal information
    enrollment = await enrollment_repo.create_enrollment(
        student_id=student.id,
        course_id=course_id,
        payment_status=payload.payment_status,
        class_type=payload.class_type,
        phone_number=payload.phone_number,
        address=payload.address,
        emergency_contact_name=payload.emergency_contact_name,
        emergency_contact_phone=payload.emergency_contact_phone,
        father_guardian_name=payload.father_guardian_name,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        profile_image_url=payload.profile_image_url,
    )
    
    # Also add to student's enrolled_courses
    await student_repo.enroll_in_course(student.id, course_id)
    
    return enrollment_to_public(enrollment)


@router.get("/enrollments", response_model=list[EnrollmentPublic])
async def get_my_enrollments(
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
) -> list[EnrollmentPublic]:
    """Get all enrollments for current user."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        return []
    
    enrollments = await enrollment_repo.get_by_student(student.id)
    return [enrollment_to_public(e) for e in enrollments]


@router.get("/dashboard")
async def get_student_dashboard(
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    instructor_repo: InstructorRepository = Depends(get_instructor_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    material_service: CourseMaterialService = Depends(get_course_material_service),
) -> dict:
    """Get enriched dashboard data for enrolled student: enrollments with course, instructor name, materials count."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        return {"enrollments": [], "mentors": []}

    enrollments = await enrollment_repo.get_by_student(student.id)
    result = []
    instructor_ids_seen = set()
    mentors_map = {}

    for e in enrollments:
        if not e.verified_by_admin:
            continue
        course = await course_repo.get_by_id(e.course_id)
        if not course:
            continue
        instructor_name = "Instructor"
        instructor_specialization = ""
        if course.instructor_id:
            instructor = await instructor_repo.get_by_id(course.instructor_id)
            if instructor:
                user = await user_repo.get_by_id(instructor.user_id)
                instructor_name = user.full_name or user.email if user else "Instructor"
                instructor_specialization = instructor.specialization or ""
                if course.instructor_id not in instructor_ids_seen:
                    instructor_ids_seen.add(course.instructor_id)
                    mentors_map[course.instructor_id] = {
                        "id": course.instructor_id,
                        "name": instructor_name,
                        "specialization": instructor_specialization,
                        "user_id": instructor.user_id,
                        "course_id": e.course_id,
                        "course_title": course.title,
                        "enrollment_date": e.enrollment_date.isoformat() if e.enrollment_date else None,
                    }

        materials = await material_service.get_course_materials(e.course_id, published_only=True)
        total_materials = len(materials)
        progress = e.progress_percentage or 0
        watched = max(0, min(total_materials, round(progress / 100 * total_materials))) if total_materials else 0

        # First video thumbnail for Continue Watching cards (YouTube only)
        thumbnail_url = None
        video_materials = [m for m in materials if m.material_type == "video" and m.content_url]
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
            "thumbnail_url": thumbnail_url,
            "enrollment_date": e.enrollment_date.isoformat() if e.enrollment_date else None,
        })

    return {"enrollments": result, "mentors": list(mentors_map.values())}


@router.post("/enrollments/{enrollment_id}/payment-receipt", response_model=EnrollmentPublic)
async def upload_payment_receipt(
    enrollment_id: str,
    payload: PaymentReceiptUpload,
    current_user: User = Depends(get_current_user),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
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
    
    # Update enrollment with receipt URL
    receipt_url = payload.receipt_url
    
    # Update enrollment
    updated_enrollment = await enrollment_repo.update(
        enrollment_id,
        {
            "payment_receipt_url": receipt_url,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    
    if not updated_enrollment:
        raise NotFoundError("Failed to update enrollment")
    
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

    course = await course_repo.get_by_id(enrollment.course_id)
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

@router.get("/results/{course_id}", response_model=list[ResultPublic])
async def get_my_results(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    result_repo: ResultRepository = Depends(get_result_repository),
) -> list[ResultPublic]:
    """Get all results for current user in a course. Requires admin-verified enrollment."""
    student, verified_enrollments = verified_data
    
    results = await result_repo.get_by_student_and_course(student.id, course_id)
    return [
        ResultPublic(
            id=r.id,
            student_id=r.student_id,
            course_id=r.course_id,
            enrollment_id=r.enrollment_id,
            assessment_type=r.assessment_type,
            assessment_name=r.assessment_name,
            marks_obtained=r.marks_obtained,
            total_marks=r.total_marks,
            percentage=r.percentage,
            grade=r.grade,
            feedback=r.feedback,
            issued_by=r.issued_by,
            issued_date=r.issued_date,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in results
    ]


@router.get("/results", response_model=dict[str, list[ResultPublic]])
async def get_all_my_results(
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    result_repo: ResultRepository = Depends(get_result_repository),
) -> dict[str, list[ResultPublic]]:
    """Get all results for current user, grouped by course. Requires admin-verified enrollment."""
    student, enrollments = verified_data
    all_results = {}
    
    for enrollment in enrollments:
        results = await result_repo.get_by_enrollment(enrollment.id)
        all_results[enrollment.course_id] = [
            ResultPublic(
                id=r.id,
                student_id=r.student_id,
                course_id=r.course_id,
                enrollment_id=r.enrollment_id,
                assessment_type=r.assessment_type,
                assessment_name=r.assessment_name,
                marks_obtained=r.marks_obtained,
                total_marks=r.total_marks,
                percentage=r.percentage,
                grade=r.grade,
                feedback=r.feedback,
                issued_by=r.issued_by,
                issued_date=r.issued_date,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in results
        ]
    
    return all_results


# ==================== Attendance ====================

@router.get("/attendance/{course_id}", response_model=list[AttendancePublic])
async def get_my_attendance(
    course_id: str,
    current_user: User = Depends(get_current_user),
    attendance_repo: AttendanceRepository = Depends(get_attendance_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
) -> list[AttendancePublic]:
    """Get all attendance records for current user in a course."""
    student = await student_repo.get_by_user_id(current_user.id)
    if not student:
        return []
    
    attendances = await attendance_repo.get_by_student_and_course(student.id, course_id)
    return [
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
    ]


@router.get("/attendance/{course_id}/stats", response_model=dict)
async def get_attendance_stats(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    attendance_repo: AttendanceRepository = Depends(get_attendance_repository),
) -> dict:
    """Get attendance statistics for current user in a course. Requires admin-verified enrollment."""
    student, _ = verified_data
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
) -> AttendancePublic:
    """Submit absence reason for an attendance record. Requires admin-verified enrollment."""
    student, _ = verified_data
    
    attendance = await attendance_service.submit_absence_reason(attendance_id, payload.absence_reason)
    
    # Verify attendance belongs to current user
    if attendance.student_id != student.id:
        raise NotFoundError("Attendance not found")
    
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

@router.get("/certificates", response_model=list[CertificatePublic])
async def get_my_certificates(
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    certificate_repo: CertificateRepository = Depends(get_certificate_repository),
) -> list[CertificatePublic]:
    """Get all certificates for current user. Requires admin-verified enrollment."""
    student, _ = verified_data
    
    certificates = await certificate_repo.get_by_student(student.id)
    return [
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
    ]


@router.get("/certificates/{course_id}", response_model=CertificatePublic | None)
async def get_course_certificate(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    certificate_repo: CertificateRepository = Depends(get_certificate_repository),
) -> CertificatePublic | None:
    """Get certificate for current user in a specific course. Requires admin-verified enrollment."""
    student, verified_enrollments = verified_data
    if not any(e.course_id == course_id for e in verified_enrollments):
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

@router.get("/scholarships", response_model=list[ScholarshipStatus])
async def get_my_scholarships(
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    scholarship_service: ScholarshipService = Depends(get_scholarship_service),
    course_repo: CourseRepository = Depends(get_course_repository),
) -> list[ScholarshipStatus]:
    """Get all scholarships for current user with status information. Requires admin-verified enrollment."""
    student, _ = verified_data
    
    scholarships = await scholarship_service.get_student_scholarships(student.id)
    
    result = []
    for scholarship in scholarships:
        course_title = None
        if scholarship.course_id:
            course = await course_repo.get_by_id(scholarship.course_id)
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
    
    return result


@router.get("/scholarships/{course_id}", response_model=list[ScholarshipPublic])
async def get_course_scholarships(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    scholarship_service: ScholarshipService = Depends(get_scholarship_service),
) -> list[ScholarshipPublic]:
    """Get scholarships for current user in a specific course. Requires admin-verified enrollment."""
    student, verified_enrollments = verified_data
    if not any(e.course_id == course_id for e in verified_enrollments):
        return []
    
    scholarships = await scholarship_service.get_student_course_scholarships(student.id, course_id)
    return [
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
    ]


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

@router.get("/courses/{course_id}/materials", response_model=list[CourseMaterialPublic])
async def get_course_materials(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    material_service: CourseMaterialService = Depends(get_course_material_service),
) -> list[CourseMaterialPublic]:
    """Get all published materials for a course. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    if not any(e.course_id == course_id for e in verified_enrollments):
        return []
    materials = await material_service.get_course_materials(course_id, published_only=True)
    return [
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
    ]


# ==================== Assignments ====================

@router.get("/courses/{course_id}/assignments", response_model=list[AssignmentPublic])
async def get_course_assignments(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    assignment_service: AssignmentService = Depends(get_assignment_service),
) -> list[AssignmentPublic]:
    """Get all published assignments for a course. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    if not any(e.course_id == course_id for e in verified_enrollments):
        return []
    assignments = await assignment_service.get_course_assignments(course_id, published_only=True)
    return [
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
    ]


@router.get("/assignments/{assignment_id}/submission", response_model=AssignmentSubmissionPublic | None)
async def get_my_submission(
    assignment_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    assignment_service: AssignmentService = Depends(get_assignment_service),
) -> AssignmentSubmissionPublic | None:
    """Get current user's submission for an assignment. Requires admin-verified enrollment."""
    student, verified_enrollments = verified_data
    assignment = await assignment_service.get_assignment(assignment_id)
    enrollment = next((e for e in verified_enrollments if e.course_id == assignment.course_id), None)
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
) -> AssignmentSubmissionPublic:
    """Submit an assignment. Requires admin-verified enrollment."""
    student, verified_enrollments = verified_data
    assignment = await assignment_service.get_assignment(assignment_id)
    enrollment = next((e for e in verified_enrollments if e.course_id == assignment.course_id), None)
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

@router.get("/courses/{course_id}/sessions", response_model=list[LiveSessionPublic])
async def get_course_sessions(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    session_service: LiveSessionService = Depends(get_live_session_service),
) -> list[LiveSessionPublic]:
    """Get all live sessions for a course. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    if not any(e.course_id == course_id for e in verified_enrollments):
        return []
    sessions = await session_service.get_course_sessions(course_id)
    return [
        LiveSessionPublic(
            id=s.id,
            course_id=s.course_id,
            title=s.title,
            description=s.description,
            session_type=s.session_type,
            start_time=s.start_time,
            end_time=s.end_time,
            meeting_link=s.meeting_link,
            location=s.location,
            instructor_id=s.instructor_id,
            max_participants=s.max_participants,
            recording_url=s.recording_url,
            is_recorded=s.is_recorded,
            status=s.status,
            created_by=s.created_by,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get("/sessions/upcoming", response_model=list[LiveSessionPublic])
async def get_upcoming_sessions(
    course_id: str | None = Query(default=None),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    session_service: LiveSessionService = Depends(get_live_session_service),
) -> list[LiveSessionPublic]:
    """Get upcoming live sessions. Requires admin-verified enrollment."""
    sessions = await session_service.get_upcoming_sessions(course_id)
    return [
        LiveSessionPublic(
            id=s.id,
            course_id=s.course_id,
            title=s.title,
            description=s.description,
            session_type=s.session_type,
            start_time=s.start_time,
            end_time=s.end_time,
            meeting_link=s.meeting_link,
            location=s.location,
            instructor_id=s.instructor_id,
            max_participants=s.max_participants,
            recording_url=s.recording_url,
            is_recorded=s.is_recorded,
            status=s.status,
            created_by=s.created_by,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


# ==================== Announcements ====================

@router.get("/announcements", response_model=list[AnnouncementPublic])
async def get_announcements(
    course_id: str | None = Query(default=None),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    announcement_service: AnnouncementService = Depends(get_announcement_service),
) -> list[AnnouncementPublic]:
    """Get announcements (course-specific or system-wide). Requires admin-verified enrollment."""
    announcements = await announcement_service.get_course_announcements(course_id, published_only=True)
    return [
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
    ]


# ==================== Course Progress ====================

@router.get("/enrollments/{enrollment_id}/progress", response_model=dict)
async def get_course_progress(
    enrollment_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    material_service: CourseMaterialService = Depends(get_course_material_service),
    assignment_service: AssignmentService = Depends(get_assignment_service),
) -> dict:
    """Get detailed course progress for an enrollment. Requires admin-verified enrollment."""
    student, verified_enrollments = verified_data
    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment or enrollment.student_id != student.id:
        raise NotFoundError("Enrollment not found")
    if not any(e.id == enrollment_id for e in verified_enrollments):
        raise NotFoundError("Enrollment not found")
    
    # Get course materials and assignments
    materials = await material_service.get_course_materials(enrollment.course_id, published_only=True)
    assignments = await assignment_service.get_course_assignments(enrollment.course_id, published_only=True)
    
    # Calculate progress based on materials and assignments
    total_items = len(materials) + len(assignments)
    completed_items = 0
    
    # For now, progress is based on enrollment progress_percentage
    # In future, can track individual material/assignment completion
    progress_percentage = enrollment.progress_percentage
    
    return {
        "enrollment_id": enrollment.id,
        "course_id": enrollment.course_id,
        "progress_percentage": progress_percentage,
        "total_materials": len(materials),
        "total_assignments": len(assignments),
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
    student, verified_enrollments = verified_data
    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if not enrollment or enrollment.student_id != student.id:
        raise NotFoundError("Enrollment not found")
    if not any(e.id == enrollment_id for e in verified_enrollments):
        raise NotFoundError("Enrollment not found")
    
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
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    result_repo: ResultRepository = Depends(get_result_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
    attendance_repo: AttendanceRepository = Depends(get_attendance_repository),
) -> dict:
    """Get comprehensive performance dashboard for current user. Requires admin-verified enrollment."""
    student, enrollments = verified_data
    
    # Get all results
    all_results = []
    course_performance = []
    grade_points = {"A+": 4.0, "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
                    "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0}
    
    total_grade_points = 0.0
    total_courses_with_grades = 0
    grade_distribution = {}
    
    for enrollment in enrollments:
        course = await course_repo.get_by_id(enrollment.course_id)
        course_results = await result_repo.get_by_enrollment(enrollment.id)
        all_results.extend(course_results)
        
        # Calculate course average
        if course_results:
            course_avg = sum(r.percentage for r in course_results) / len(course_results)
            # Get final grade (use the highest assessment or average)
            final_grade = max(course_results, key=lambda r: r.percentage).grade
            grade_point = grade_points.get(final_grade, 0.0)
            total_grade_points += grade_point
            total_courses_with_grades += 1
            
            # Count grades
            for result in course_results:
                grade = result.grade
                grade_distribution[grade] = grade_distribution.get(grade, 0) + 1
            
            course_performance.append({
                "course_id": enrollment.course_id,
                "course_title": course.title if course else "Unknown",
                "enrollment_status": enrollment.status,
                "progress_percentage": enrollment.progress_percentage,
                "average_percentage": round(course_avg, 2),
                "final_grade": final_grade,
                "grade_point": grade_point,
                "total_assessments": len(course_results),
                "recent_assessment": max(course_results, key=lambda r: r.issued_date).assessment_name if course_results else None,
            })
    
    # Calculate overall GPA
    overall_gpa = (total_grade_points / total_courses_with_grades) if total_courses_with_grades > 0 else 0.0
    
    # Get recent results (last 10)
    recent_results = sorted(all_results, key=lambda r: r.issued_date, reverse=True)[:10]
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
    
    # Get attendance summary
    attendance_summary = {}
    for enrollment in enrollments:
        stats = await attendance_repo.get_attendance_stats(student.id, enrollment.course_id)
        course = await course_repo.get_by_id(enrollment.course_id)
        if course:
            attendance_summary[enrollment.course_id] = {
                "course_title": course.title,
                "present": stats.get("present", 0),
                "absent": stats.get("absent", 0),
                "late": stats.get("late", 0),
                "excused": stats.get("excused", 0),
                "total": stats.get("total", 0),
                "percentage": stats.get("percentage", 0.0),
            }
    
    return {
        "overall_gpa": round(overall_gpa, 2),
        "total_courses": len(enrollments),
        "completed_courses": len([e for e in enrollments if e.status == "completed"]),
        "active_courses": len([e for e in enrollments if e.status == "active"]),
        "course_performance": course_performance,
        "grade_distribution": grade_distribution,
        "recent_results": recent_results_data,
        "attendance_summary": attendance_summary,
    }


# ==================== Calendar Events ====================

@router.get("/calendar/events", response_model=list[CalendarEventPublic])
async def get_my_calendar_events(
    start_date: str | None = Query(default=None, description="Start date (ISO format)"),
    end_date: str | None = Query(default=None, description="End date (ISO format)"),
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    calendar_service: CalendarEventService = Depends(get_calendar_event_service),
) -> list[CalendarEventPublic]:
    """Get calendar events for current user's enrolled courses. Requires admin-verified enrollment."""
    student, enrollments = verified_data
    course_ids = [e.course_id for e in enrollments]
    
    start = datetime.fromisoformat(start_date.replace('Z', '+00:00')) if start_date else None
    end = datetime.fromisoformat(end_date.replace('Z', '+00:00')) if end_date else None
    
    events = await calendar_service.get_student_events(course_ids, start, end)
    
    return [
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
    ]


# ==================== Payments ====================

@router.get("/payments", response_model=list[PaymentPublic])
async def get_my_payments(
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    payment_service: PaymentService = Depends(get_payment_service),
) -> list[PaymentPublic]:
    """Get all payments for current user. Requires admin-verified enrollment."""
    student, _ = verified_data
    
    payments = await payment_service.get_student_payments(student.id)
    return [
        PaymentPublic(
            id=p.id,
            student_id=p.student_id,
            course_id=p.course_id,
            enrollment_id=p.enrollment_id,
            amount=p.amount,
            currency=p.currency,
            payment_method=p.payment_method,
            payment_status=p.payment_status,
            transaction_id=p.transaction_id,
            invoice_number=p.invoice_number,
            invoice_url=p.invoice_url,
            payment_date=p.payment_date,
            due_date=p.due_date,
            scholarship_discount=p.scholarship_discount,
            notes=p.notes,
            created_by=p.created_by,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in payments
    ]


# ==================== Forum ====================

@router.get("/courses/{course_id}/forum", response_model=list[ForumPostPublic])
async def get_forum_posts(
    course_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
) -> list[ForumPostPublic]:
    """Get forum posts for a course. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    if not any(e.course_id == course_id for e in verified_enrollments):
        return []
    posts = await forum_service.get_course_posts(course_id, top_level_only=True)
    
    result = []
    for post in posts:
        # Get author name
        author = await user_repo.get_by_id(post.author_id)
        author_name = author.full_name if author else None
        
        # Get reply count
        replies = await forum_service.get_replies(post.id)
        
        result.append(
            ForumPostPublic(
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
                reply_count=len(replies),
                created_at=post.created_at,
                updated_at=post.updated_at,
            )
        )
    
    return result


@router.get("/forum/posts/{post_id}", response_model=ForumPostPublic)
async def get_forum_post(
    post_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
) -> ForumPostPublic:
    """Get a forum post with replies. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    post = await forum_service.get_post(post_id)
    if not any(e.course_id == post.course_id for e in verified_enrollments):
        raise NotFoundError("Forum post not found")
    author = await user_repo.get_by_id(post.author_id)
    replies = await forum_service.get_replies(post.id)
    
    return ForumPostPublic(
        id=post.id,
        course_id=post.course_id,
        parent_post_id=post.parent_post_id,
        author_id=post.author_id,
        author_name=author.full_name if author else None,
        title=post.title,
        content=post.content,
        post_type=post.post_type,
        is_resolved=post.is_resolved,
        is_pinned=post.is_pinned,
        upvotes=post.upvotes,
        downvotes=post.downvotes,
        views=post.views,
        reply_count=len(replies),
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


@router.get("/forum/posts/{post_id}/replies", response_model=list[ForumPostPublic])
async def get_forum_replies(
    post_id: str,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
) -> list[ForumPostPublic]:
    """Get replies to a forum post. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    parent_post = await forum_service.get_post(post_id)
    if not any(e.course_id == parent_post.course_id for e in verified_enrollments):
        raise NotFoundError("Forum post not found")
    replies = await forum_service.get_replies(post_id)
    
    result = []
    for reply in replies:
        author = await user_repo.get_by_id(reply.author_id)
        reply_replies = await forum_service.get_replies(reply.id)
        
        result.append(
            ForumPostPublic(
                id=reply.id,
                course_id=reply.course_id,
                parent_post_id=reply.parent_post_id,
                author_id=reply.author_id,
                author_name=author.full_name if author else None,
                title=reply.title,
                content=reply.content,
                post_type=reply.post_type,
                is_resolved=reply.is_resolved,
                is_pinned=reply.is_pinned,
                upvotes=reply.upvotes,
                downvotes=reply.downvotes,
                views=reply.views,
                reply_count=len(reply_replies),
                created_at=reply.created_at,
                updated_at=reply.updated_at,
            )
        )
    
    return result


@router.post("/forum/posts", response_model=ForumPostPublic, status_code=status.HTTP_201_CREATED)
async def create_forum_post(
    payload: ForumPostCreate,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
) -> ForumPostPublic:
    """Create a new forum post. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    if not any(e.course_id == payload.course_id for e in verified_enrollments):
        raise ForbiddenError("Not enrolled in this course")
    post = await forum_service.create_post(payload, student.user_id)
    author = await user_repo.get_by_id(post.author_id)
    replies = await forum_service.get_replies(post.id)
    
    return ForumPostPublic(
        id=post.id,
        course_id=post.course_id,
        parent_post_id=post.parent_post_id,
        author_id=post.author_id,
        author_name=author.full_name if author else None,
        title=post.title,
        content=post.content,
        post_type=post.post_type,
        is_resolved=post.is_resolved,
        is_pinned=post.is_pinned,
        upvotes=post.upvotes,
        downvotes=post.downvotes,
        views=post.views,
        reply_count=len(replies),
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


@router.post("/forum/posts/{post_id}/vote", response_model=ForumPostPublic)
async def vote_forum_post(
    post_id: str,
    payload: ForumVote,
    verified_data: tuple = Depends(get_require_verified_enrollment()),
    forum_service: ForumService = Depends(get_forum_service),
    user_repo: UserRepository = Depends(get_user_repository),
) -> ForumPostPublic:
    """Vote on a forum post. Requires admin-verified enrollment for this course."""
    student, verified_enrollments = verified_data
    existing_post = await forum_service.get_post(post_id)
    if not any(e.course_id == existing_post.course_id for e in verified_enrollments):
        raise NotFoundError("Forum post not found")
    post = await forum_service.vote_post(post_id, payload)
    author = await user_repo.get_by_id(post.author_id)
    replies = await forum_service.get_replies(post.id)
    
    return ForumPostPublic(
        id=post.id,
        course_id=post.course_id,
        parent_post_id=post.parent_post_id,
        author_id=post.author_id,
        author_name=author.full_name if author else None,
        title=post.title,
        content=post.content,
        post_type=post.post_type,
        is_resolved=post.is_resolved,
        is_pinned=post.is_pinned,
        upvotes=post.upvotes,
        downvotes=post.downvotes,
        views=post.views,
        reply_count=len(replies),
        created_at=post.created_at,
        updated_at=post.updated_at,
    )
