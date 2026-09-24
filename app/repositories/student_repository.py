from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.student import Student
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class StudentRepository(BaseRepository[Student]):
    collection_name = "students"

    async def ensure_indexes(self) -> None:
        # Unique user_id - one student per user
        await self.collection.create_index([("user_id", ASCENDING)], unique=True)
        # Index on is_active for filtering
        await self.collection.create_index([("is_active", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Student:
        return Student(
            id=oid_str(doc["_id"]),
            user_id=oid_str(doc["user_id"]),
            enrollment_date=doc.get("enrollment_date") or datetime.now(timezone.utc),
            enrolled_courses=[oid_str(cid) for cid in doc.get("enrolled_courses", [])],
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_id(self, student_id: str) -> Student | None:
        try:
            oid = ObjectId(student_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"_id": oid})
        return self._to_model(doc) if doc else None

    async def get_by_user_id(self, user_id: str) -> Student | None:
        """Get student by user_id."""
        try:
            user_oid = ObjectId(user_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"user_id": user_oid})
        return self._to_model(doc) if doc else None

    async def create_student(
        self,
        *,
        user_id: str,
        enrollment_date: datetime | None = None,
    ) -> Student:
        now = datetime.now(timezone.utc)
        try:
            user_oid = ObjectId(user_id)
        except Exception:
            raise ValueError("Invalid user_id")
        
        payload = {
            "user_id": user_oid,
            "enrollment_date": enrollment_date or now,
            "enrolled_courses": [],
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    async def enroll_in_course(self, student_id: str, course_id: str) -> Student | None:
        """Enroll a student in a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            {"_id": student_oid},
            {
                "$addToSet": {"enrolled_courses": course_oid},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def unenroll_from_course(self, student_id: str, course_id: str) -> Student | None:
        """Unenroll a student from a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            {"_id": student_oid},
            {
                "$pull": {"enrolled_courses": course_oid},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            return_document=True,
        )
        return self._to_model(result) if result else None
