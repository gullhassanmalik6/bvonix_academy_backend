"""
Course service - business logic for course management.

Why: Service layer encapsulates business logic and orchestrates
repository operations, keeping routes clean and testable.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.models.course import Course
from app.repositories.course_repository import CourseRepository
from app.schemas.course import CourseCreate, CourseUpdate
from app.utils.exceptions import ConflictError, NotFoundError


class CourseService:
    def __init__(self, course_repo: CourseRepository) -> None:
        self._courses = course_repo

    async def get_course(self, course_id: str) -> Course:
        """Get a course by ID."""
        course = await self._courses.get_by_id(course_id)
        if course is None:
            raise NotFoundError("Course not found")
        return course

    async def list_courses(self, skip: int = 0, limit: int = 100) -> tuple[list[Course], int]:
        """List all courses with pagination."""
        courses = await self._courses.list(skip=skip, limit=limit)
        total = await self._courses.count()
        return courses, total

    async def list_published_courses(self, skip: int = 0, limit: int = 100) -> tuple[list[Course], int]:
        """List published courses with pagination."""
        courses = await self._courses.get_published(skip=skip, limit=limit)
        total = await self._courses.count({"is_published": True})
        return courses, total

    async def get_courses_by_instructor(self, instructor_id: str) -> list[Course]:
        """Get all courses by an instructor."""
        return await self._courses.get_by_instructor(instructor_id)

    async def create_course(self, payload: CourseCreate) -> Course:
        """Create a new course."""
        try:
            return await self._courses.create_course(
                title=payload.title,
                description=payload.description,
                instructor_id=payload.instructor_id,
                duration_hours=payload.duration_hours,
                price=payload.price,
                is_published=payload.is_published,
            )
        except ValueError as e:
            raise NotFoundError(str(e)) from e
        except DuplicateKeyError as e:
            raise ConflictError("Course already exists") from e

    async def update_course(self, course_id: str, payload: CourseUpdate) -> Course:
        """Update a course."""
        course = await self.get_course(course_id)
        
        update_data: dict[str, any] = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.description is not None:
            update_data["description"] = payload.description
        if payload.instructor_id is not None:
            from bson import ObjectId
            try:
                update_data["instructor_id"] = ObjectId(payload.instructor_id)
            except Exception:
                raise NotFoundError("Invalid instructor_id")
        if payload.duration_hours is not None:
            update_data["duration_hours"] = payload.duration_hours
        if payload.price is not None:
            update_data["price"] = payload.price
        if payload.is_published is not None:
            update_data["is_published"] = payload.is_published
        
        if not update_data:
            return course
        
        from datetime import datetime, timezone
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated_course = await self._courses.update(course_id, update_data)
        if updated_course is None:
            raise NotFoundError("Course not found")
        return updated_course

    async def delete_course(self, course_id: str) -> None:
        """Delete a course."""
        course = await self.get_course(course_id)
        await self._courses.delete(course_id)
