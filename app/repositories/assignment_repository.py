from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.assignment import Assignment, AssignmentSubmission
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class AssignmentRepository(BaseRepository[Assignment]):
    collection_name = "assignments"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING), ("due_date", ASCENDING)])
        await self.collection.create_index([("is_published", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Assignment:
        return Assignment(
            id=oid_str(doc["_id"]),
            course_id=oid_str(doc["course_id"]),
            title=doc.get("title", ""),
            description=doc.get("description", ""),
            instructions=doc.get("instructions"),
            due_date=doc.get("due_date"),
            max_marks=doc.get("max_marks", 100.0),
            assignment_type=doc.get("assignment_type", "homework"),
            is_published=doc.get("is_published", True),
            created_by=oid_str(doc["created_by"]),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def list_page(
        self,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        published_only: bool = False,
    ) -> tuple[list[Assignment], int]:
        try:
            query: dict[str, Any] = {"course_id": ObjectId(course_id)}
        except Exception:
            return [], 0
        if published_only:
            query["is_published"] = True
        return await self.find_page(query, skip=skip, limit=limit, sort=[("due_date", ASCENDING)])

    async def get_by_course(self, course_id: str, published_only: bool = True) -> list[Assignment]:
        """Get all assignments for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        filter_dict: dict[str, Any] = {"course_id": course_oid}
        if published_only:
            filter_dict["is_published"] = True
        
        cursor = self.collection.find(filter_dict).sort("due_date", ASCENDING)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def create_assignment(
        self,
        *,
        course_id: str,
        title: str,
        description: str,
        instructions: str | None,
        due_date: datetime | None,
        max_marks: float,
        assignment_type: str,
        is_published: bool,
        created_by: str,
    ) -> Assignment:
        now = datetime.now(timezone.utc)
        try:
            course_oid = ObjectId(course_id)
            created_by_oid = ObjectId(created_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        payload = {
            "course_id": course_oid,
            "title": title,
            "description": description,
            "instructions": instructions,
            "due_date": due_date,
            "max_marks": max_marks,
            "assignment_type": assignment_type,
            "is_published": is_published,
            "created_by": created_by_oid,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)


class AssignmentSubmissionRepository(BaseRepository[AssignmentSubmission]):
    collection_name = "assignment_submissions"

    async def ensure_indexes(self) -> None:
        # Unique submission per student-assignment
        await self.collection.create_index(
            [("assignment_id", ASCENDING), ("student_id", ASCENDING)],
            unique=True
        )
        await self.collection.create_index([("assignment_id", ASCENDING)])
        await self.collection.create_index([("student_id", ASCENDING)])
        await self.collection.create_index([("status", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> AssignmentSubmission:
        return AssignmentSubmission(
            id=oid_str(doc["_id"]),
            assignment_id=oid_str(doc["assignment_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_id=oid_str(doc["enrollment_id"]),
            submission_text=doc.get("submission_text"),
            file_urls=doc.get("file_urls", []),
            submitted_at=doc.get("submitted_at") or datetime.now(timezone.utc),
            status=doc.get("status", "pending"),
            marks_obtained=doc.get("marks_obtained"),
            feedback=doc.get("feedback"),
            graded_by=oid_str(doc["graded_by"]) if doc.get("graded_by") else None,
            graded_at=doc.get("graded_at"),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_assignment(self, assignment_id: str) -> list[AssignmentSubmission]:
        """Get all submissions for an assignment."""
        try:
            assignment_oid = ObjectId(assignment_id)
        except Exception:
            return []
        
        cursor = self.collection.find({"assignment_id": assignment_oid}).sort("submitted_at", -1)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_by_student_and_assignment(
        self,
        student_id: str,
        assignment_id: str,
    ) -> AssignmentSubmission | None:
        """Get student's submission for an assignment."""
        try:
            student_oid = ObjectId(student_id)
            assignment_oid = ObjectId(assignment_id)
        except Exception:
            return None
        
        doc = await self.collection.find_one({
            "student_id": student_oid,
            "assignment_id": assignment_oid,
        })
        return self._to_model(doc) if doc else None

    async def create_submission(
        self,
        *,
        assignment_id: str,
        student_id: str,
        course_id: str,
        enrollment_id: str,
        submission_text: str | None,
        file_urls: list[str],
    ) -> AssignmentSubmission:
        now = datetime.now(timezone.utc)
        try:
            assignment_oid = ObjectId(assignment_id)
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            raise ValueError("Invalid IDs")
        
        # Check if already submitted
        existing = await self.get_by_student_and_assignment(student_id, assignment_id)
        if existing:
            # Update existing submission
            update_data = {
                "submission_text": submission_text,
                "file_urls": file_urls,
                "submitted_at": now,
                "status": "resubmitted" if existing.status == "graded" else "submitted",
                "updated_at": now,
            }
            result = await self.collection.find_one_and_update(
                {"_id": ObjectId(existing.id)},
                {"$set": update_data},
                return_document=True,
            )
            return self._to_model(result) if result else existing
        
        payload = {
            "assignment_id": assignment_oid,
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_id": enrollment_oid,
            "submission_text": submission_text,
            "file_urls": file_urls,
            "submitted_at": now,
            "status": "submitted",
            "marks_obtained": None,
            "feedback": None,
            "graded_by": None,
            "graded_at": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
