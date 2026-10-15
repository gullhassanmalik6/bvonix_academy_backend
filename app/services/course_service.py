"""
Course service - business logic for course management.

Why: Service layer encapsulates business logic and orchestrates
repository operations, keeping routes clean and testable.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.core.permissions import assert_can_purge, is_management
from app.repositories.instructor_repository import InstructorRepository
from app.models.course import Course
from app.repositories.course_repository import CourseRepository
from app.schemas.course import CourseCreate, CourseUpdate
from app.services.archive_actions import archive_record, load_for_maintenance, purge_record
from app.services.audit_service import AuditService
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError


async def require_active_course(courses: CourseRepository | None, course_id: str | None) -> None:
    """Block new dependent records when the parent course is missing or archived."""
    if courses is None or not course_id:
        return
    course = await courses.get_by_id(course_id)
    if course is None:
        raise NotFoundError("Course not found")


async def course_is_operational(courses: CourseRepository | None, course_id: str | None) -> bool:
    """Operational lists omit a course that active lookup cannot see."""
    if courses is None or not course_id:
        return True
    return await courses.get_by_id(course_id) is not None


class CourseService:
    def __init__(self, course_repo: CourseRepository, *, audit: AuditService | None = None) -> None:
        self._courses = course_repo
        self._audit = audit

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

    async def page_courses_by_instructor(
        self,
        instructor_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        published_only: bool = False,
    ) -> tuple[list[Course], int]:
        return await self._courses.page_by_instructor(
            instructor_id,
            skip=skip,
            limit=limit,
            published_only=published_only,
        )

    async def create_course(
        self,
        payload: CourseCreate,
        *,
        instructors: InstructorRepository | None = None,
    ) -> Course:
        """Create a new course. The instructor id must refer to a stored instructor profile."""
        if instructors is not None and await instructors.get_by_id(payload.instructor_id) is None:
            raise NotFoundError("Instructor not found")
        image_url = getattr(payload, "image_url", None)
        if image_url is not None and not str(image_url).startswith("/uploads/course_images/"):
            raise ConflictError("Course image must be stored by the academy upload")
        try:
            return await self._courses.create_course(
                title=payload.title,
                description=payload.description,
                instructor_id=payload.instructor_id,
                duration_hours=payload.duration_hours,
                price=payload.price,
                is_published=payload.is_published,
                image_url=image_url,
            )
        except ValueError as e:
            raise NotFoundError(str(e)) from e
        except DuplicateKeyError as e:
            raise ConflictError("Course already exists") from e

    async def update_course(
        self,
        course_id: str,
        payload: CourseUpdate,
        *,
        actor_role: str | None = None,
        instructors: InstructorRepository | None = None,
    ) -> Course:
        """Update a course.

        Title, description, duration, and price stay available to the assigned
        instructor. Reassignment and publication require a management role, and
        a new instructor id must match an active instructor profile.
        """
        course = await self.get_course(course_id)
        reassigning = payload.instructor_id is not None and payload.instructor_id != course.instructor_id
        publishing = payload.is_published is not None and payload.is_published != course.is_published
        if reassigning and not is_management(actor_role or ""):
            raise ForbiddenError("You cannot reassign this course")
        if publishing and not is_management(actor_role or ""):
            raise ForbiddenError("You cannot change course publication")
        if reassigning:
            if instructors is None or await instructors.get_by_id(payload.instructor_id) is None:
                raise NotFoundError("Instructor not found")

        update_data = {}
        if payload.title is not None:
            update_data["title"] = payload.title
        if payload.description is not None:
            update_data["description"] = payload.description
        if reassigning:
            from bson import ObjectId
            try:
                update_data["instructor_id"] = ObjectId(payload.instructor_id)
            except Exception:
                raise NotFoundError("Instructor not found")
        if payload.duration_hours is not None:
            update_data["duration_hours"] = payload.duration_hours
        if payload.price is not None:
            update_data["price"] = payload.price
        if publishing:
            update_data["is_published"] = payload.is_published
        if payload.clear_image:
            update_data["image_url"] = None
        elif payload.image_url is not None:
            if not str(payload.image_url).startswith("/uploads/course_images/"):
                raise ConflictError("Course image must be stored by the academy upload")
            update_data["image_url"] = payload.image_url
        
        if not update_data:
            return course
        
        from datetime import datetime, timezone
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated_course = await self._courses.update(course_id, update_data)
        if updated_course is None:
            raise NotFoundError("Course not found")
        return updated_course

    async def delete_course(
        self,
        course_id: str,
        *,
        archived_by: str | None,
        actor_role: str,
    ) -> None:
        """Archive a course. Enrollments and other history stay in place."""
        if not is_management(actor_role):
            raise ForbiddenError("Management access required")
        course = await self.get_course(course_id)
        await archive_record(
            self._courses,
            course,
            archived_by=archived_by,
            deactivate=False,
            audit=self._audit,
            action="course.delete",
            entity_type="course",
            not_found="Course not found",
        )

    async def purge_course(self, course_id: str, *, actor_role: str, actor_id: str) -> None:
        """Permanently remove a course. Super admin only. Not exposed on HTTP routes."""
        assert_can_purge(actor_role)
        course = await load_for_maintenance(self._courses, course_id, not_found="Course not found")
        await purge_record(
            self._courses,
            course,
            actor_role=actor_role,
            actor_id=actor_id,
            audit=self._audit,
            entity_type="course",
            not_found="Course not found",
        )
