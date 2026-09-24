from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.result import Result
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


def calculate_grade(percentage: float) -> str:
    """Calculate grade based on percentage."""
    if percentage >= 97:
        return "A+"
    elif percentage >= 93:
        return "A"
    elif percentage >= 90:
        return "A-"
    elif percentage >= 87:
        return "B+"
    elif percentage >= 83:
        return "B"
    elif percentage >= 80:
        return "B-"
    elif percentage >= 77:
        return "C+"
    elif percentage >= 73:
        return "C"
    elif percentage >= 70:
        return "C-"
    elif percentage >= 67:
        return "D+"
    elif percentage >= 63:
        return "D"
    elif percentage >= 60:
        return "D-"
    else:
        return "F"


class ResultRepository(BaseRepository[Result]):
    collection_name = "results"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
        await self.collection.create_index([("enrollment_id", ASCENDING)])
        await self.collection.create_index([("assessment_type", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Result:
        percentage = (doc.get("marks_obtained", 0) / doc.get("total_marks", 1)) * 100
        return Result(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_id=oid_str(doc["enrollment_id"]),
            assessment_type=doc.get("assessment_type", "assignment"),
            assessment_name=doc.get("assessment_name", ""),
            marks_obtained=doc.get("marks_obtained", 0.0),
            total_marks=doc.get("total_marks", 100.0),
            percentage=percentage,
            grade=doc.get("grade") or calculate_grade(percentage),
            feedback=doc.get("feedback"),
            issued_by=oid_str(doc["issued_by"]),
            issued_date=doc.get("issued_date") or datetime.now(timezone.utc),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> list[Result]:
        """Get all results for a student in a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        cursor = self.collection.find({"student_id": student_oid, "course_id": course_oid})
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_by_enrollment(self, enrollment_id: str) -> list[Result]:
        """Get all results for an enrollment."""
        try:
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            return []
        cursor = self.collection.find({"enrollment_id": enrollment_oid})
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def create_result(
        self,
        *,
        student_id: str,
        course_id: str,
        enrollment_id: str,
        assessment_type: str,
        assessment_name: str,
        marks_obtained: float,
        total_marks: float,
        feedback: str | None = None,
        issued_by: str,
    ) -> Result:
        now = datetime.now(timezone.utc)
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
            enrollment_oid = ObjectId(enrollment_id)
            issued_by_oid = ObjectId(issued_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        percentage = (marks_obtained / total_marks) * 100
        grade = calculate_grade(percentage)
        
        payload = {
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_id": enrollment_oid,
            "assessment_type": assessment_type,
            "assessment_name": assessment_name,
            "marks_obtained": marks_obtained,
            "total_marks": total_marks,
            "percentage": percentage,
            "grade": grade,
            "feedback": feedback,
            "issued_by": issued_by_oid,
            "issued_date": now,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
