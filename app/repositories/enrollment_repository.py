from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.db.index_status import ensure_required_index
from app.models.enrollment import Enrollment
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.repositories.listing import sort_pairs, text_clause
from app.utils.helpers import oid_str

VERIFIED_ACCESS_STATUSES = ("active", "completed")

ENROLLMENT_SORTS = {
    "created_at": [("created_at", ASCENDING)],
    "-created_at": [("created_at", DESCENDING)],
    "enrollment_date": [("enrollment_date", ASCENDING)],
    "-enrollment_date": [("enrollment_date", DESCENDING)],
    "status": [("status", ASCENDING), ("created_at", DESCENDING)],
}


class EnrollmentRepository(BaseRepository[Enrollment]):
    collection_name = "enrollments"

    async def ensure_indexes(self) -> None:
        # Unique enrollment per student-course combination
        await ensure_required_index(
            self.collection, [("student_id", ASCENDING), ("course_id", ASCENDING)], unique=True
        )
        # Indexes for filtering
        await self.collection.create_index([("student_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("status", ASCENDING)])
        await self.collection.create_index([("review_state", ASCENDING)])
        await self.collection.create_index([("created_at", DESCENDING)])
        await self.collection.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
        await self.collection.create_index([("payment_status", ASCENDING), ("created_at", DESCENDING)])
        await self.collection.create_index([("verified_by_admin", ASCENDING), ("created_at", DESCENDING)])
        await self.collection.create_index([
            ("student_id", ASCENDING),
            ("verified_by_admin", ASCENDING),
            ("status", ASCENDING),
            ("enrollment_date", ASCENDING),
        ])
        await ensure_required_index(
            self.collection, [("enrollment_card_number", ASCENDING)], unique=True, sparse=True
        )

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
            review_state=doc.get("review_state"),
            audit_pending=doc.get("audit_pending") or None,
            fee_due_date=doc.get("fee_due_date"),
            access_exception=doc.get("access_exception") or None,
        )

    async def list_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        payment_status: str | None = None,
        verified: bool | None = None,
        q: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Enrollment], int]:
        """Filter, search, sort, and page enrollments in MongoDB."""
        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        if payment_status:
            query["payment_status"] = payment_status
        if verified is not None:
            query["verified_by_admin"] = verified
        if q and q.strip():
            query["$or"] = text_clause(
                q,
                ("enrollment_card_number", "phone_number", "class_type", "father_guardian_name"),
            )["$or"]
        return await self.find_page(
            query,
            skip=skip,
            limit=limit,
            sort=sort_pairs(sort, allowed=ENROLLMENT_SORTS, default="-created_at"),
        )

    async def get_by_id(self, enrollment_id: str) -> Enrollment | None:
        """Get enrollment by ID."""
        try:
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"_id": enrollment_oid})
        return self._to_model(doc) if doc else None

    async def find_by_stored_file(self, field: str, url: str) -> Enrollment | None:
        """Find the enrollment that stores this private file URL."""
        if field not in {"payment_receipt_url", "profile_image_url", "enrollment_card_url"}:
            return None
        if not url:
            return None
        doc = await self.collection.find_one({field: url})
        return self._to_model(doc) if doc else None

    async def delete(self, doc_id: str) -> bool:
        """Cancellation changes status. Ordinary delete must not archive or erase the row."""
        del doc_id
        return False

    async def get_by_card_number(self, card_number: str) -> Enrollment | None:
        """Find enrollment by printed card number (QR verification)."""
        doc = await self.collection.find_one({"enrollment_card_number": card_number})
        return self._to_model(doc) if doc else None

    async def registration_course_ids(self, student_id: str) -> list[str]:
        """Course ids for enrollments that are not cancelled.

        Pages of 100 keep each read bounded. Duplicate rows for one course
        contribute one id and are left in place.
        """
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        query = {"student_id": student_oid, "status": {"$ne": "cancelled"}}
        found: set[str] = set()
        skip = 0
        page_size = 100
        while True:
            docs = await self.collection.find(query).sort(
                [("_id", ASCENDING)]
            ).skip(skip).limit(page_size).to_list(length=page_size)
            if not docs:
                break
            for doc in docs:
                if doc.get("course_id") is not None:
                    found.add(oid_str(doc["course_id"]))
            if len(docs) < page_size:
                break
            skip += len(docs)
        return sorted(found)

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
        """Get every enrollment for a student, including historical statuses."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        return await self.collect(
            {"student_id": student_oid},
            sort=[("enrollment_date", ASCENDING)],
        )

    async def get_verified_by_student(self, student_id: str) -> list[Enrollment]:
        """Get every admin-verified active or completed enrollment for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        return await self.collect(
            {
                "student_id": student_oid,
                "verified_by_admin": True,
                "status": {"$in": ["active", "completed"]},
            },
            sort=[("enrollment_date", ASCENDING)],
        )

    async def list_current_for_student(self, student_id: str) -> list[Enrollment]:
        """Current dashboard rows: admin-verified enrollments that are still active."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        return await self.collect(
            {
                "student_id": student_oid,
                "verified_by_admin": True,
                "status": "active",
            },
            sort=[("enrollment_date", ASCENDING)],
        )

    async def page_for_student(
        self,
        student_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Enrollment], int]:
        """Page a student's enrollment history, including cancelled and completed rows."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return [], 0
        return await self.find_page(
            {"student_id": student_oid},
            skip=skip,
            limit=limit,
            sort=[("enrollment_date", ASCENDING)],
        )

    async def page_current_for_student(
        self,
        student_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Enrollment], int]:
        """Page current dashboard rows with the same filter as list_current_for_student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return [], 0
        return await self.find_page(
            {
                "student_id": student_oid,
                "verified_by_admin": True,
                "status": "active",
            },
            skip=skip,
            limit=limit,
            sort=[("enrollment_date", ASCENDING)],
        )

    def _verified_query(self, student_oid: ObjectId, course_oid: ObjectId | None = None) -> dict[str, Any]:
        """Same verified active/completed filter used by get_verified_by_student."""
        query: dict[str, Any] = {
            "student_id": student_oid,
            "verified_by_admin": True,
            "status": {"$in": list(VERIFIED_ACCESS_STATUSES)},
        }
        if course_oid is not None:
            query["course_id"] = course_oid
        return with_active(query)

    async def has_verified_enrollment(self, student_id: str) -> bool:
        """True when one eligible enrollment exists. Does not load the student's other rows."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return False
        found = await self.collection.find_one(self._verified_query(student_oid))
        return found is not None

    async def get_access_enrollment(self, student_id: str, course_id: str) -> Enrollment | None:
        """The one verified active or completed enrollment for this student and course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return None
        doc = await self.collection.find_one(self._verified_query(student_oid, course_oid))
        return self._to_model(doc) if doc else None

    async def get_owned_verified(self, student_id: str, enrollment_id: str) -> Enrollment | None:
        """One verified enrollment owned by this student."""
        try:
            student_oid = ObjectId(student_id)
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            return None
        query = self._verified_query(student_oid)
        query["_id"] = enrollment_oid
        doc = await self.collection.find_one(query)
        return self._to_model(doc) if doc else None

    async def page_verified(
        self,
        student_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Enrollment], int]:
        """Page verified active and completed enrollments. total matches that filter."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return [], 0
        return await self.find_page(
            self._verified_query(student_oid),
            skip=skip,
            limit=limit,
            sort=[("enrollment_date", ASCENDING)],
        )

    async def count_verified_statuses(self, student_id: str) -> dict[str, int]:
        """Count verified enrollments by status without building enrollment models."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return {"active": 0, "completed": 0}
        counts = {"active": 0, "completed": 0}
        pipeline = [
            {"$match": self._verified_query(student_oid)},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        async for doc in self.collection.aggregate(pipeline):
            status = doc.get("_id")
            if status in counts:
                counts[status] = int(doc.get("count") or 0)
        return counts

    async def verified_course_ids(self, student_id: str) -> list[str]:
        """Course ids for verified enrollments, read in pages and not turned into models.

        Calendar and upcoming sessions need this id set. The ids are the filter,
        so the list is complete, while each database page stays bounded.
        """
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        query = self._verified_query(student_oid)
        found: list[str] = []
        skip = 0
        page_size = 100
        while True:
            docs = await self.collection.find(query).sort(
                [("enrollment_date", ASCENDING), ("_id", ASCENDING)]
            ).skip(skip).limit(page_size).to_list(length=page_size)
            if not docs:
                break
            for doc in docs:
                if doc.get("course_id") is not None:
                    found.append(oid_str(doc["course_id"]))
            if len(docs) < page_size:
                break
            skip += len(docs)
        return found

    async def get_by_course(self, course_id: str) -> list[Enrollment]:
        """Get all enrollments for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        return await self.collect(
            {"course_id": course_oid},
            sort=[("enrollment_date", ASCENDING)],
        )

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
            "review_state": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
