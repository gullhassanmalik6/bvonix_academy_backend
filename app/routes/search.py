"""
Search routes for global search functionality.

Why: Centralized search endpoint that searches across multiple entities
provides a unified search experience.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from typing import Literal

from app.core.auth import get_current_user
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
    
    query_lower = q.lower()
    
    # Search courses
    if "course" in search_types:
        courses = await course_repo.list(skip=0, limit=limit * 2)
        for course in courses:
            if (query_lower in course.title.lower() or 
                (course.description and query_lower in course.description.lower())):
                all_results.append(SearchResult(
                    type="course",
                    id=course.id,
                    title=course.title,
                    description=course.description,
                    url=f"/courses/{course.id}",
                ))
                if len([r for r in all_results if r.type == "course"]) >= limit:
                    break
    
    # Search students
    if "student" in search_types:
        students = await student_repo.list(skip=0, limit=limit * 2)
        for student in students:
            # Get user info for student
            user = await user_repo.get_by_id(student.user_id)
            if user and query_lower in (user.full_name or "").lower():
                all_results.append(SearchResult(
                    type="student",
                    id=student.id,
                    title=user.full_name or user.email,
                    description=f"Student ID: {student.id}",
                    url=f"/admin/students/{student.id}",
                ))
                if len([r for r in all_results if r.type == "student"]) >= limit:
                    break
    
    # Search users
    if "user" in search_types:
        users = await user_repo.list(skip=0, limit=limit * 2)
        for user in users:
            if (query_lower in user.email.lower() or 
                (user.full_name and query_lower in user.full_name.lower())):
                all_results.append(SearchResult(
                    type="user",
                    id=user.id,
                    title=user.full_name or user.email,
                    description=user.email,
                    url=f"/admin/users/{user.id}",
                ))
                if len([r for r in all_results if r.type == "user"]) >= limit:
                    break
    
    # Limit total results
    all_results = all_results[:limit * len(search_types)]
    
    return SearchResponse(
        query=q,
        results=all_results,
        total=len(all_results),
    )
