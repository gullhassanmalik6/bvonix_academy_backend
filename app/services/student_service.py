"""
Student service - business logic for student management.

Why: Service layer encapsulates business logic and orchestrates
repository operations, keeping routes clean and testable.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.models.student import Student
from app.repositories.student_repository import StudentRepository
from app.schemas.student import StudentCreate, StudentUpdate
from app.utils.exceptions import ConflictError, NotFoundError


class StudentService:
    def __init__(self, student_repo: StudentRepository) -> None:
        self._students = student_repo

    async def get_student(self, student_id: str) -> Student:
        """Get a student by ID."""
        student = await self._students.get_by_id(student_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def get_student_by_user_id(self, user_id: str) -> Student:
        """Get a student by user_id."""
        student = await self._students.get_by_user_id(user_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def list_students(self, skip: int = 0, limit: int = 100) -> tuple[list[Student], int]:
        """List all students with pagination."""
        students = await self._students.list(skip=skip, limit=limit)
        total = await self._students.count()
        return students, total

    async def create_student(self, payload: StudentCreate) -> Student:
        """Create a new student."""
        try:
            return await self._students.create_student(
                user_id=payload.user_id,
                enrollment_date=payload.enrollment_date,
            )
        except ValueError as e:
            raise NotFoundError(str(e)) from e
        except DuplicateKeyError as e:
            raise ConflictError("Student already exists for this user") from e

    async def update_student(self, student_id: str, payload: StudentUpdate) -> Student:
        """Update a student."""
        student = await self.get_student(student_id)
        
        update_data: dict[str, any] = {}
        if payload.enrolled_courses is not None:
            from bson import ObjectId
            try:
                update_data["enrolled_courses"] = [ObjectId(cid) for cid in payload.enrolled_courses]
            except Exception:
                raise NotFoundError("Invalid course IDs")
        if payload.is_active is not None:
            update_data["is_active"] = payload.is_active
        
        if not update_data:
            return student
        
        from datetime import datetime, timezone
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        updated_student = await self._students.update(student_id, update_data)
        if updated_student is None:
            raise NotFoundError("Student not found")
        return updated_student

    async def enroll_in_course(self, student_id: str, course_id: str) -> Student:
        """Enroll a student in a course."""
        student = await self.get_student(student_id)
        # Verify course exists
        from app.repositories.course_repository import CourseRepository
        from app.db.mongodb import mongodb
        course_repo = CourseRepository(mongodb.db)
        course = await course_repo.get_by_id(course_id)
        if course is None:
            raise NotFoundError("Course not found")
        
        updated_student = await self._students.enroll_in_course(student_id, course_id)
        if updated_student is None:
            raise NotFoundError("Student not found")
        return updated_student

    async def unenroll_from_course(self, student_id: str, course_id: str) -> Student:
        """Unenroll a student from a course."""
        student = await self.get_student(student_id)
        updated_student = await self._students.unenroll_from_course(student_id, course_id)
        if updated_student is None:
            raise NotFoundError("Student not found")
        return updated_student

    async def delete_student(self, student_id: str) -> None:
        """Delete a student."""
        student = await self.get_student(student_id)
        await self._students.delete(student_id)
