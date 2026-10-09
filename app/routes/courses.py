"""
Course management routes.

Why: Separate routes file for course CRUD operations keeps
the codebase organized and follows single responsibility principle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.admin import get_management_user
from app.core.auth import get_current_user
from app.core.dependencies import get_course_repository, get_course_service, get_instructor_repository
from app.core.permissions import can_manage_course, is_management
from app.repositories.instructor_repository import InstructorRepository
from app.utils.exceptions import ForbiddenError, NotFoundError
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.schemas.common import PaginatedResponse
from app.schemas.course import CourseCreate, CoursePublic, CourseUpdate
from app.services.course_service import CourseService

router = APIRouter()


def _course_public(course) -> CoursePublic:
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


async def _can_see_drafts(current_user: User, instructor_id: str, instructors: InstructorRepository) -> bool:
    """Management sees every draft. An instructor sees drafts only for their own profile."""
    if is_management(current_user.role):
        return True
    profile = await instructors.get_by_user_id(current_user.id)
    profile_id = profile.id if profile is not None else None
    return can_manage_course(current_user.role, profile_id, instructor_id)


@router.get("", response_model=PaginatedResponse[CoursePublic])
async def list_courses(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    published_only: bool = Query(default=False),
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[CoursePublic]:
    """Page courses. Students and other non-management accounts see published courses."""
    if published_only or not is_management(current_user.role):
        courses, total = await service.list_published_courses(skip=skip, limit=limit)
    else:
        courses, total = await service.list_courses(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[_course_public(course) for course in courses],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{course_id}", response_model=CoursePublic)
async def get_course(
    course_id: str,
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
    instructors: InstructorRepository = Depends(get_instructor_repository),
) -> CoursePublic:
    """Get a course by ID. Unpublished courses stay hidden from other accounts."""
    course = await service.get_course(course_id)
    if not course.is_published and not await _can_see_drafts(current_user, course.instructor_id, instructors):
        raise NotFoundError("Course not found")
    return _course_public(course)


@router.get("/instructor/{instructor_id}/courses", response_model=PaginatedResponse[CoursePublic])
async def get_courses_by_instructor(
    instructor_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: CourseService = Depends(get_course_service),
    current_user: User = Depends(get_current_user),
    instructors: InstructorRepository = Depends(get_instructor_repository),
) -> PaginatedResponse[CoursePublic]:
    """Page courses taught by an instructor. Another account sees published courses only."""
    published_only = not await _can_see_drafts(current_user, instructor_id, instructors)
    courses, total = await service.page_courses_by_instructor(
        instructor_id,
        skip=skip,
        limit=limit,
        published_only=published_only,
    )
    return PaginatedResponse(
        items=[_course_public(course) for course in courses],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=CoursePublic, status_code=status.HTTP_201_CREATED)
async def create_course(
    payload: CourseCreate,
    service: CourseService = Depends(get_course_service),
    instructors: InstructorRepository = Depends(get_instructor_repository),
    current_user: User = Depends(get_management_user),
) -> CoursePublic:
    """Create a new course. Management only, and the instructor must exist."""
    course = await service.create_course(payload, instructors=instructors)
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
    instructors: InstructorRepository = Depends(get_instructor_repository),
    current_user: User = Depends(get_current_user),
) -> CoursePublic:
    """Update a course. Assigned instructors edit content. Management publishes and reassigns."""
    existing = await service.get_course(course_id)
    profile = await instructors.get_by_user_id(current_user.id)
    profile_id = profile.id if profile is not None else None
    if not can_manage_course(current_user.role, profile_id, existing.instructor_id):
        raise ForbiddenError("You can only manage courses assigned to you")
    course = await service.update_course(
        course_id,
        payload,
        actor_role=current_user.role,
        instructors=instructors,
    )
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
    current_user: User = Depends(get_management_user),
) -> Response:
    """Delete a course."""
    await service.delete_course(
        course_id,
        archived_by=current_user.id,
        actor_role=current_user.role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
