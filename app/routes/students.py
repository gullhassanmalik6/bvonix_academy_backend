"""
Student management routes.

Why: Separate routes file for student CRUD operations keeps
the codebase organized and follows single responsibility principle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.auth import get_current_user
from app.core.dependencies import get_student_repository, get_student_service
from app.models.user import User
from app.repositories.student_repository import StudentRepository
from app.schemas.common import PaginatedResponse
from app.schemas.student import StudentCreate, StudentPublic, StudentUpdate
from app.services.student_service import StudentService

router = APIRouter()


@router.get("", response_model=PaginatedResponse[StudentPublic])
async def list_students(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[StudentPublic]:
    """List all students (paginated)."""
    students, total = await service.list_students(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[
            StudentPublic(
                id=s.id,
                user_id=s.user_id,
                enrollment_date=s.enrollment_date,
                enrolled_courses=s.enrolled_courses,
                is_active=s.is_active,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in students
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{student_id}", response_model=StudentPublic)
async def get_student(
    student_id: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> StudentPublic:
    """Get a student by ID."""
    student = await service.get_student(student_id)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.get("/user/{user_id}", response_model=StudentPublic)
async def get_student_by_user_id(
    user_id: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> StudentPublic:
    """Get a student by user_id."""
    student = await service.get_student_by_user_id(user_id)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.post("", response_model=StudentPublic, status_code=status.HTTP_201_CREATED)
async def create_student(
    payload: StudentCreate,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> StudentPublic:
    """Create a new student."""
    student = await service.create_student(payload)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.patch("/{student_id}", response_model=StudentPublic)
async def update_student(
    student_id: str,
    payload: StudentUpdate,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> StudentPublic:
    """Update a student."""
    student = await service.update_student(student_id, payload)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.post("/{student_id}/enroll/{course_id}", response_model=StudentPublic)
async def enroll_in_course(
    student_id: str,
    course_id: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> StudentPublic:
    """Enroll a student in a course."""
    student = await service.enroll_in_course(student_id, course_id)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.post("/{student_id}/unenroll/{course_id}", response_model=StudentPublic)
async def unenroll_from_course(
    student_id: str,
    course_id: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> StudentPublic:
    """Unenroll a student from a course."""
    student = await service.unenroll_from_course(student_id, course_id)
    return StudentPublic(
        id=student.id,
        user_id=student.user_id,
        enrollment_date=student.enrollment_date,
        enrolled_courses=student.enrolled_courses,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


@router.delete("/{student_id}")
async def delete_student(
    student_id: str,
    service: StudentService = Depends(get_student_service),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a student."""
    await service.delete_student(student_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
