from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.db.index_status import ensure_required_index
from app.models.attendance_claim import AttendanceClaim
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class AttendanceClaimRepository(BaseRepository[AttendanceClaim]):
    collection_name = "attendance_claims"

    async def ensure_indexes(self) -> None:
        await ensure_required_index(
            self.collection,
            [("student_id", ASCENDING), ("course_id", ASCENDING), ("session_date", ASCENDING)],
            unique=True,
        )
        await self.collection.create_index([("course_id", ASCENDING), ("session_date", ASCENDING), ("status", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> AttendanceClaim:
        return AttendanceClaim(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_id=oid_str(doc["enrollment_id"]),
            session_date=doc.get("session_date") or datetime.now(timezone.utc),
            status=doc.get("status", "pending_verification"),
            submitted_at=doc.get("submitted_at") or datetime.now(timezone.utc),
            reviewed_by=oid_str(doc["reviewed_by"]) if doc.get("reviewed_by") else None,
            reviewed_at=doc.get("reviewed_at"),
            review_reason=doc.get("review_reason"),
            attendance_id=oid_str(doc["attendance_id"]) if doc.get("attendance_id") else None,
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_id(self, claim_id: str) -> AttendanceClaim | None:
        doc = await self.find_document_by_id(claim_id)
        return self._to_model(doc) if doc else None

    async def find_for_session(self, student_id: str, course_id: str, session_date: datetime) -> AttendanceClaim | None:
        try:
            query = {
                "student_id": ObjectId(student_id),
                "course_id": ObjectId(course_id),
                "session_date": session_date,
            }
        except Exception:
            return None
        doc = await self.collection.find_one(query)
        return self._to_model(doc) if doc else None

    async def page_for_student_course(
        self,
        student_id: str,
        course_id: str | None,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[AttendanceClaim], int]:
        try:
            query: dict[str, Any] = {"student_id": ObjectId(student_id)}
            if course_id:
                query["course_id"] = ObjectId(course_id)
        except Exception:
            return [], 0
        return await self.find_page(query, skip=skip, limit=limit, sort=[("session_date", DESCENDING)])

    async def list_for_course_date(self, course_id: str, session_date: datetime) -> list[AttendanceClaim]:
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        return await self.collect(
            {"course_id": course_oid, "session_date": session_date},
            sort=[("submitted_at", ASCENDING)],
        )

    async def create_claim(
        self,
        *,
        student_id: str,
        course_id: str,
        enrollment_id: str,
        session_date: datetime,
        submitted_at: datetime,
    ) -> AttendanceClaim:
        now = datetime.now(timezone.utc)
        payload = {
            "student_id": ObjectId(student_id),
            "course_id": ObjectId(course_id),
            "enrollment_id": ObjectId(enrollment_id),
            "session_date": session_date,
            "status": "pending_verification",
            "submitted_at": submitted_at,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_reason": None,
            "attendance_id": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
