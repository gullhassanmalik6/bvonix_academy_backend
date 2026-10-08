"""
Search routes for global search functionality.

Why: Centralized search endpoint that searches across multiple entities
provides a unified search experience.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from typing import Literal

from app.core.auth import get_current_user
from app.core.permissions import is_management
from app.repositories.archival import record_is_active
from app.repositories.listing import text_clause
from app.core.dependencies import (
    get_course_repository,
    get_student_repository,
    get_user_repository,
)
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import APIModel


class SearchResult(APIModel):
    """Search result item."""
    type: Literal["course", "student", "user", "material"]
    id: str
    title: str
    description: str | None = None
    url: str | None = None


class SearchResponse(APIModel):
    """Search response."""
    query: str
    results: list[SearchResult]
    total: int


router = APIRouter()


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    types: str = Query(default="course,student,user", description="Comma-separated types to search"),
    limit: int = Query(default=20, ge=1, le=50, description="Maximum results per type"),
    course_repo: CourseRepository = Depends(get_course_repository),
    student_repo: StudentRepository = Depends(get_student_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """Global search across courses, students, users, and materials."""
    search_types = [t.strip() for t in types.split(",")]
    all_results: list[SearchResult] = []
    
    # Search courses in the database, then keep at most `limit` hits.
    if "course" in search_types:
        courses, _total = await course_repo.find_page(
            text_clause(q, ("title", "description")),
            skip=0,
            limit=limit,
            sort=[("title", 1)],
        )
        for course in courses:
            all_results.append(SearchResult(
                type="course",
                id=course.id,
                title=course.title,
                description=course.description,
                url=f"/courses/{course.id}",
            ))
    
    # Student and user records are management data.
    if "user" in search_types and is_management(current_user.role):
        users, _total = await user_repo.find_page(
            text_clause(q, ("email", "full_name")),
            skip=0,
            limit=limit,
            sort=[("full_name", 1)],
        )
        for user in users:
            if not record_is_active(user):
                continue
            all_results.append(SearchResult(
                type="user",
                id=user.id,
                title=user.full_name or user.email,
                description=user.email,
                url=f"/admin/users/{user.id}",
            ))

    if "student" in search_types and is_management(current_user.role):
        matched_users, _total = await user_repo.find_page(
            text_clause(q, ("email", "full_name")),
            skip=0,
            limit=limit,
            sort=[("full_name", 1)],
        )
        profiles = await student_repo.find_active_by_user_ids([user.id for user in matched_users])
        names = {user.id: user for user in matched_users if record_is_active(user)}
        for student in profiles:
            if not record_is_active(student):
                continue
            account = names.get(student.user_id)
            if account is None:
                continue
            all_results.append(SearchResult(
                type="student",
                id=student.id,
                title=account.full_name or account.email,
                description=f"Student ID: {student.id}",
                url=f"/admin/students/{student.id}",
            ))
            if len([item for item in all_results if item.type == "student"]) >= limit:
                break
    
    # Limit total results
    all_results = all_results[:limit * len(search_types)]
    
    return SearchResponse(
        query=q,
        results=all_results,
        total=len(all_results),
    )
