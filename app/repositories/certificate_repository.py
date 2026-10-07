from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.certificate import Certificate
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


def generate_certificate_number() -> str:
    """Generate a unique certificate number."""
    prefix = "BVX"
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))
    return f"{prefix}-{random_part}"


class CertificateRepository(BaseRepository[Certificate]):
    collection_name = "certificates"

    async def ensure_indexes(self) -> None:
        # Unique certificate number
        await self.collection.create_index([("certificate_number", ASCENDING)], unique=True)
        # Unique certificate per student-course
        await self.collection.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)], unique=True)
        await self.collection.create_index([("enrollment_id", ASCENDING)])
        await self.collection.create_index([("is_verified", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Certificate:
        return Certificate(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_id=oid_str(doc["enrollment_id"]),
            certificate_number=doc.get("certificate_number", ""),
            issue_date=doc.get("issue_date") or datetime.now(timezone.utc),
            completion_date=doc.get("completion_date") or datetime.now(timezone.utc),
            grade=doc.get("grade"),
            issued_by=oid_str(doc["issued_by"]),
            certificate_url=doc.get("certificate_url"),
            is_verified=doc.get("is_verified", False),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def count_issued(self) -> int:
        return await self.collection.count_documents({})

    async def get_by_student(self, student_id: str) -> list[Certificate]:
        """Get all certificates for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        cursor = self.collection.find({"student_id": student_oid}).sort("issue_date", -1)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> Certificate | None:
        """Get certificate for a student in a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"student_id": student_oid, "course_id": course_oid})
        return self._to_model(doc) if doc else None

    async def get_by_certificate_number(self, certificate_number: str) -> Certificate | None:
        """Get certificate by certificate number."""
        doc = await self.collection.find_one({"certificate_number": certificate_number})
        return self._to_model(doc) if doc else None

    async def create_certificate(
        self,
        *,
        student_id: str,
        course_id: str,
        enrollment_id: str,
        completion_date: datetime,
        grade: str | None = None,
        issued_by: str,
        certificate_url: str | None = None,
    ) -> Certificate:
        now = datetime.now(timezone.utc)
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
            enrollment_oid = ObjectId(enrollment_id)
            issued_by_oid = ObjectId(issued_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        # Generate unique certificate number
        certificate_number = generate_certificate_number()
        # Ensure uniqueness
        while await self.get_by_certificate_number(certificate_number):
            certificate_number = generate_certificate_number()
        
        payload = {
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_id": enrollment_oid,
            "certificate_number": certificate_number,
            "issue_date": now,
            "completion_date": completion_date,
            "grade": grade,
            "issued_by": issued_by_oid,
            "certificate_url": certificate_url,
            "is_verified": True,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
