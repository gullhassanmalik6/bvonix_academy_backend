"""
Instructor management routes.

Why: Separate routes file for instructor CRUD operations keeps
the codebase organized and follows single responsibility principle.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.admin import get_admin_user
from app.core.auth import get_current_user
from app.core.dependencies import get_instructor_repository, get_instructor_service
from app.core.permissions import is_admin
from app.utils.exceptions import ForbiddenError
from app.models.user import User
from app.repositories.instructor_repository import InstructorRepository
from app.schemas.common import PaginatedResponse
from app.schemas.instructor import InstructorCreate, InstructorPublic, InstructorUpdate
from app.services.instructor_service import InstructorService

router = APIRouter()


@router.get("", response_model=PaginatedResponse[InstructorPublic])
async def list_instructors(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    service: InstructorService = Depends(get_instructor_service),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[InstructorPublic]:
    """List all instructors (paginated)."""
    instructors, total = await service.list_instructors(skip=skip, limit=limit)
    
    return PaginatedResponse(
        items=[
            InstructorPublic(
                id=i.id,
                user_id=i.user_id,
                bio=i.bio,
                specialization=i.specialization,
                years_of_experience=i.years_of_experience,
                is_active=i.is_active,
                created_at=i.created_at,
                updated_at=i.updated_at,
            )
            for i in instructors
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{instructor_id}", response_model=InstructorPublic)
async def get_instructor(
    instructor_id: str,
    service: InstructorService = Depends(get_instructor_service),
    current_user: User = Depends(get_current_user),
) -> InstructorPublic:
    """Get an instructor by ID."""
    instructor = await service.get_instructor(instructor_id)
    return InstructorPublic(
        id=instructor.id,
        user_id=instructor.user_id,
        bio=instructor.bio,
        specialization=instructor.specialization,
        years_of_experience=instructor.years_of_experience,
        is_active=instructor.is_active,
        created_at=instructor.created_at,
        updated_at=instructor.updated_at,
    )


@router.get("/user/{user_id}", response_model=InstructorPublic)
async def get_instructor_by_user_id(
    user_id: str,
    service: InstructorService = Depends(get_instructor_service),
    current_user: User = Depends(get_current_user),
) -> InstructorPublic:
    """Get an instructor by user_id."""
    instructor = await service.get_instructor_by_user_id(user_id)
    return InstructorPublic(
        id=instructor.id,
        user_id=instructor.user_id,
        bio=instructor.bio,
        specialization=instructor.specialization,
        years_of_experience=instructor.years_of_experience,
        is_active=instructor.is_active,
        created_at=instructor.created_at,
        updated_at=instructor.updated_at,
    )


@router.post("", response_model=InstructorPublic, status_code=status.HTTP_201_CREATED)
async def create_instructor(
    payload: InstructorCreate,
    service: InstructorService = Depends(get_instructor_service),
    current_user: User = Depends(get_admin_user),
) -> InstructorPublic:
    """Create a new instructor."""
    instructor = await service.create_instructor(payload)
    return InstructorPublic(
        id=instructor.id,
        user_id=instructor.user_id,
        bio=instructor.bio,
        specialization=instructor.specialization,
        years_of_experience=instructor.years_of_experience,
        is_active=instructor.is_active,
        created_at=instructor.created_at,
        updated_at=instructor.updated_at,
    )


@router.patch("/{instructor_id}", response_model=InstructorPublic)
async def update_instructor(
    instructor_id: str,
    payload: InstructorUpdate,
    service: InstructorService = Depends(get_instructor_service),
    current_user: User = Depends(get_current_user),
) -> InstructorPublic:
    """Update an instructor. Instructors can edit only their own profile."""
    existing = await service.get_instructor(instructor_id)
    if existing.user_id != current_user.id and not is_admin(current_user.role):
        raise ForbiddenError("You can only update your own instructor profile")
    if existing.user_id == current_user.id and not is_admin(current_user.role):
        if payload.is_active is not None:
            raise ForbiddenError("You cannot change instructor activation")
    instructor = await service.update_instructor(instructor_id, payload)
    return InstructorPublic(
        id=instructor.id,
        user_id=instructor.user_id,
        bio=instructor.bio,
        specialization=instructor.specialization,
        years_of_experience=instructor.years_of_experience,
        is_active=instructor.is_active,
        created_at=instructor.created_at,
        updated_at=instructor.updated_at,
    )


@router.delete("/{instructor_id}")
async def delete_instructor(
    instructor_id: str,
    service: InstructorService = Depends(get_instructor_service),
    current_user: User = Depends(get_admin_user),
) -> Response:
    """Delete an instructor."""
    await service.delete_instructor(
        instructor_id,
        archived_by=current_user.id,
        actor_role=current_user.role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
