"""
Public routes that do not require authentication.

Why: Marketing pages (course catalog, course detail) must work for anonymous visitors.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import (
    get_assignment_repository,
    get_course_material_repository,
    get_course_repository,
    get_course_service,
    get_enrollment_repository,
    get_instructor_repository,
    get_student_repository,
    get_user_repository,
)
from app.repositories.assignment_repository import AssignmentRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginatedResponse
from app.schemas.course import CourseDecisionPublic, CoursePublic
from app.schemas.student_card import StudentCardVerifyResponse
from app.services.course_decision import build_course_decision
from app.services.course_service import CourseService
from app.utils.exceptions import NotFoundError

router = APIRouter()


@router.get("/courses", response_model=PaginatedResponse[CoursePublic])
async def list_public_courses(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: CourseService = Depends(get_course_service),
) -> PaginatedResponse[CoursePublic]:
    """List published courses (no auth required)."""
    courses, total = await service.list_published_courses(skip=skip, limit=limit)
    return PaginatedResponse(
        items=[
            CoursePublic(
                id=c.id,
                title=c.title,
                description=c.description,
                instructor_id=c.instructor_id,
                duration_hours=c.duration_hours,
                price=c.price,
                is_published=c.is_published,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in courses
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/courses/{course_id}", response_model=CoursePublic)
async def get_public_course(
    course_id: str,
    service: CourseService = Depends(get_course_service),
) -> CoursePublic:
    """Get a published course by ID (no auth required)."""
    course = await service.get_course(course_id)
    if not course.is_published:
        from app.utils.exceptions import NotFoundError
        raise NotFoundError("Course not found")
    return CoursePublic(
        id=course.id,
        title=course.title,
        description=course.description,
        instructor_id=course.instructor_id,
        duration_hours=course.duration_hours,
        price=course.price,
        is_published=course.is_published,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.get("/courses/{course_id}/decision", response_model=CourseDecisionPublic)
async def get_public_course_decision(
    course_id: str,
    service: CourseService = Depends(get_course_service),
    instructors: InstructorRepository = Depends(get_instructor_repository),
    users: UserRepository = Depends(get_user_repository),
    materials: CourseMaterialRepository = Depends(get_course_material_repository),
    assignments: AssignmentRepository = Depends(get_assignment_repository),
) -> CourseDecisionPublic:
    """Published lesson titles, practical work, and instructor name. No file URLs."""
    course = await service.get_course(course_id)
    return await build_course_decision(
        course,
        instructors=instructors,
        users=users,
        materials=materials,
        assignments=assignments,
    )


@router.get("/verify/{card_number}", response_model=StudentCardVerifyResponse)
async def verify_enrollment_card(
    card_number: str,
    enrollment_repo: EnrollmentRepository = Depends(get_enrollment_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    course_repo: CourseRepository = Depends(get_course_repository),
) -> StudentCardVerifyResponse:
    """Public QR verification — no authentication required."""
    enrollment = await enrollment_repo.get_by_card_number(card_number)
    if not enrollment:
        return StudentCardVerifyResponse(
            valid=False,
            card_number=card_number,
            message="Card not found or invalid.",
        )

    student = await student_repo.get_by_id(enrollment.student_id)
    student_user = await user_repo.get_by_id(student.user_id) if student else None
    course = await course_repo.get_by_id(enrollment.course_id)

    ref_date = enrollment.enrollment_date
    batch = f"Batch – {ref_date.strftime('%B %Y')}" if ref_date else None
    enroll_str = ref_date.strftime("%d %B %Y") if ref_date else None

    if not enrollment.verified_by_admin:
        return StudentCardVerifyResponse(
            valid=False,
            card_number=card_number,
            student_name=student_user.full_name if student_user else None,
            course_name=course.title if course else None,
            batch=batch,
            enrollment_date=enroll_str,
            verified_by_admin=False,
            message="Enrollment pending admin verification.",
        )

    return StudentCardVerifyResponse(
        valid=True,
        card_number=card_number,
        student_name=student_user.full_name if student_user else None,
        course_name=course.title if course else None,
        batch=batch,
        enrollment_date=enroll_str,
        verified_by_admin=True,
        message="Card verified successfully.",
    )
