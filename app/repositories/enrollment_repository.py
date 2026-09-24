from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.enrollment import Enrollment
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class EnrollmentRepository(BaseRepository[Enrollment]):
    collection_name = "enrollments"

    async def ensure_indexes(self) -> None:
        # Unique enrollment per student-course combination
        await self.collection.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)], unique=True)
        # Indexes for filtering
        await self.collection.create_index([("student_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("status", ASCENDING)])
        await self.collection.create_index([("enrollment_card_number", ASCENDING)], unique=True, sparse=True)

    def _to_model(self, doc: dict[str, Any]) -> Enrollment:
        return Enrollment(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_date=doc.get("enrollment_date") or datetime.now(timezone.utc),
            status=doc.get("status", "pending"),
            payment_status=doc.get("payment_status", "pending"),
            payment_date=doc.get("payment_date"),
            completion_date=doc.get("completion_date"),
            progress_percentage=doc.get("progress_percentage", 0.0),
            class_type=doc.get("class_type", "online"),
            phone_number=doc.get("phone_number"),
            address=doc.get("address"),
            emergency_contact_name=doc.get("emergency_contact_name"),
            emergency_contact_phone=doc.get("emergency_contact_phone"),
            father_guardian_name=doc.get("father_guardian_name"),
            date_of_birth=doc.get("date_of_birth"),
            gender=doc.get("gender"),
            profile_image_url=doc.get("profile_image_url"),
            enrollment_card_number=doc.get("enrollment_card_number"),
            enrollment_card_url=doc.get("enrollment_card_url"),
            payment_receipt_url=doc.get("payment_receipt_url"),
            verified_by_admin=doc.get("verified_by_admin", False),
            verified_at=doc.get("verified_at"),
            verified_by=oid_str(doc["verified_by"]) if doc.get("verified_by") else None,
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_id(self, enrollment_id: str) -> Enrollment | None:
        """Get enrollment by ID."""
        try:
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"_id": enrollment_oid})
        return self._to_model(doc) if doc else None

    async def get_by_card_number(self, card_number: str) -> Enrollment | None:
        """Find enrollment by printed card number (QR verification)."""
        doc = await self.collection.find_one({"enrollment_card_number": card_number})
        return self._to_model(doc) if doc else None

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> Enrollment | None:
        """Get enrollment by student and course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"student_id": student_oid, "course_id": course_oid})
        return self._to_model(doc) if doc else None

    async def get_by_student(self, student_id: str) -> list[Enrollment]:
        """Get all enrollments for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        cursor = self.collection.find({"student_id": student_oid})
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_verified_by_student(self, student_id: str) -> list[Enrollment]:
        """Get all admin-verified enrollments for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        cursor = self.collection.find({
            "student_id": student_oid,
            "verified_by_admin": True,
        })
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def has_verified_enrollment(self, student_id: str) -> bool:
        """Check if student has at least one admin-verified enrollment."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return False
        count = await self.collection.count_documents({
            "student_id": student_oid,
            "verified_by_admin": True,
        })
        return count > 0

    async def get_by_course(self, course_id: str) -> list[Enrollment]:
        """Get all enrollments for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        cursor = self.collection.find({"course_id": course_oid})
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def create_enrollment(
        self,
        *,
        student_id: str,
        course_id: str,
        payment_status: str = "pending",
        class_type: str = "online",
        phone_number: str | None = None,
        address: str | None = None,
        emergency_contact_name: str | None = None,
        emergency_contact_phone: str | None = None,
        father_guardian_name: str | None = None,
        date_of_birth: str | None = None,
        gender: str | None = None,
        profile_image_url: str | None = None,
    ) -> Enrollment:
        now = datetime.now(timezone.utc)
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            raise ValueError("Invalid student_id or course_id")
        
        # Generate unique enrollment card number
        import secrets
        enrollment_card_number = f"ENR-{secrets.token_hex(8).upper()}"
        
        payload = {
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_date": now,
            "status": "pending",
            "payment_status": payment_status,
            "payment_date": now if payment_status == "paid" else None,
            "completion_date": None,
            "progress_percentage": 0.0,
            "class_type": class_type,
            "phone_number": phone_number,
            "address": address,
            "emergency_contact_name": emergency_contact_name,
            "emergency_contact_phone": emergency_contact_phone,
            "father_guardian_name": father_guardian_name,
            "date_of_birth": date_of_birth,
            "gender": gender,
            "profile_image_url": profile_image_url,
            "enrollment_card_number": enrollment_card_number,
            "enrollment_card_url": None,
            "payment_receipt_url": None,
            "verified_by_admin": False,
            "verified_at": None,
            "verified_by": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
