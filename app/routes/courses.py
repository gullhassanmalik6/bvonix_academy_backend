"""
Course management routes.

Why: Separate routes file for course CRUD operations keeps
the codebase organized and follows single responsibility principle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.auth import get_current_user
from app.core.dependencies import get_course_repository, get_course_service
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.schemas.common import PaginatedResponse
from app.schemas.course import CourseCreate, CoursePublic, CourseUpdate
from app.services.course_service import CourseService

router = APIRouter()


@router.get("", response_model=PaginatedResponse[CoursePublic])
async def list_courses(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    published_only: bool = Query(default=False),
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[CoursePublic]:
    """List all courses (paginated)."""
    if published_only:
        courses, total = await service.list_published_courses(skip=skip, limit=limit)
    else:
        courses, total = await service.list_courses(skip=skip, limit=limit)
    
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


@router.get("/{course_id}", response_model=CoursePublic)
async def get_course(
    course_id: str,
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
) -> CoursePublic:
    """Get a course by ID."""
    course = await service.get_course(course_id)
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


@router.get("/instructor/{instructor_id}/courses", response_model=list[CoursePublic])
async def get_courses_by_instructor(
    instructor_id: str,
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
) -> list[CoursePublic]:
    """Get all courses by an instructor."""
    courses = await service.get_courses_by_instructor(instructor_id)
    return [
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
    ]


@router.post("", response_model=CoursePublic, status_code=status.HTTP_201_CREATED)
async def create_course(
    payload: CourseCreate,
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
) -> CoursePublic:
    """Create a new course."""
    course = await service.create_course(payload)
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


@router.patch("/{course_id}", response_model=CoursePublic)
async def update_course(
    course_id: str,
    payload: CourseUpdate,
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
) -> CoursePublic:
    """Update a course."""
    course = await service.update_course(course_id, payload)
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


@router.delete("/{course_id}")
async def delete_course(
    course_id: str,
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a course."""
    await service.delete_course(course_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
