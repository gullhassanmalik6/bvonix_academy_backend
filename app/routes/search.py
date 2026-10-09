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
    """Search response. total is the matching record count, which can exceed len(results)."""
    query: str
    results: list[SearchResult]
    total: int
    skip: int = 0
    limit: int = 20


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
    skip: int = Query(default=0, ge=0),
) -> SearchResponse:
    """Global search. Each requested type contributes one page, and total is the sum of database counts."""
    search_types = [t.strip() for t in types.split(",") if t.strip()]
    requested_limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else 20
    page_limit = min(max(requested_limit, 1), 50)
    page_skip = max(skip, 0) if isinstance(skip, int) and not isinstance(skip, bool) else 0
    all_results: list[SearchResult] = []
    total = 0

    if "course" in search_types:
        course_query = text_clause(q, ("title", "description"))
        if not is_management(current_user.role):
            course_query["is_published"] = True
        courses, course_total = await course_repo.find_page(
            course_query,
            skip=page_skip,
            limit=page_limit,
            sort=[("title", 1)],
        )
        total += course_total
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
        users, user_total = await user_repo.find_page(
            text_clause(q, ("email", "full_name")),
            skip=page_skip,
            limit=page_limit,
            sort=[("full_name", 1)],
        )
        total += user_total
        for user in users:
            all_results.append(SearchResult(
                type="user",
                id=user.id,
                title=user.full_name or user.email,
                description=user.email,
                url=f"/admin/users/{user.id}",
            ))

    if "student" in search_types and is_management(current_user.role):
        students, student_total = await student_repo.list_page(q=q, skip=page_skip, limit=page_limit)
        total += student_total
        accounts = await user_repo.load_by_ids([student.user_id for student in students])
        for student in students:
            account = accounts.get(student.user_id)
            title = (account.full_name or account.email) if account is not None else student.id
            all_results.append(SearchResult(
                type="student",
                id=student.id,
                title=title,
                description=f"Student ID: {student.id}",
                url=f"/admin/students/{student.id}",
            ))

    return SearchResponse(
        query=q,
        results=all_results,
        total=total,
        skip=page_skip,
        limit=page_limit,
    )
