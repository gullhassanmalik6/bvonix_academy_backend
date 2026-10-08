from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.core.attendance_correction import OPEN_STATES
from app.models.attendance_correction import AttendanceCorrection
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


def _ref(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return ObjectId(value)
    except Exception:
        return value


class AttendanceCorrectionRepository(BaseRepository[AttendanceCorrection]):
    collection_name = "attendance_corrections"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("attendance_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"status": {"$in": list(OPEN_STATES)}},
            name="one_open_correction_per_attendance",
        )
        await self.collection.create_index(
            [("status", ASCENDING), ("requested_at", DESCENDING)]
        )
        await self.collection.create_index(
            [("student_id", ASCENDING), ("requested_at", DESCENDING)]
        )
        await self.collection.create_index(
            [("course_id", ASCENDING), ("requested_at", DESCENDING)]
        )

    def _to_model(self, doc: dict[str, Any]) -> AttendanceCorrection:
        now = datetime.now(timezone.utc)
        return AttendanceCorrection(
            id=oid_str(doc["_id"]),
            attendance_id=oid_str(doc["attendance_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_id=oid_str(doc["enrollment_id"]),
            requester_id=oid_str(doc["requester_id"]) if doc.get("requester_id") is not None else "",
            reviewer_id=oid_str(doc["reviewer_id"]) if doc.get("reviewer_id") else None,
            reason=doc.get("reason") or "",
            previous_status=doc.get("previous_status") or "",
            previous_is_excused=bool(doc.get("previous_is_excused", False)),
            requested_status=doc.get("requested_status") or "",
            status=doc.get("status") or "requested",
            decision=doc.get("decision"),
            requested_at=doc.get("requested_at") or now,
            review_started_at=doc.get("review_started_at"),
            reviewed_at=doc.get("reviewed_at"),
            review_note=doc.get("review_note"),
            created_at=doc.get("created_at") or now,
            updated_at=doc.get("updated_at") or now,
        )

    async def get_by_id(self, correction_id: str) -> AttendanceCorrection | None:
        try:
            oid = ObjectId(correction_id)
        except Exception:
            return None
        doc = await self.collection.find_one({"_id": oid})
        return self._to_model(doc) if doc else None

    async def find_open_for_attendance(self, attendance_id: str) -> AttendanceCorrection | None:
        doc = await self.collection.find_one(
            {
                "attendance_id": _ref(attendance_id),
                "status": {"$in": list(OPEN_STATES)},
            }
        )
        return self._to_model(doc) if doc else None

    async def create_request(self, correction: AttendanceCorrection) -> AttendanceCorrection:
        now = datetime.now(timezone.utc)
        payload = {
            "attendance_id": _ref(correction.attendance_id),
            "student_id": _ref(correction.student_id),
            "course_id": _ref(correction.course_id),
            "enrollment_id": _ref(correction.enrollment_id),
            "requester_id": _ref(correction.requester_id),
            "reviewer_id": None,
            "reason": correction.reason,
            "previous_status": correction.previous_status,
            "previous_is_excused": correction.previous_is_excused,
            "requested_status": correction.requested_status,
            "status": correction.status,
            "decision": None,
            "requested_at": correction.requested_at or now,
            "review_started_at": None,
            "reviewed_at": None,
            "review_note": None,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    async def save(self, correction: AttendanceCorrection) -> AttendanceCorrection | None:
        try:
            oid = ObjectId(correction.id)
        except Exception:
            return None
        now = datetime.now(timezone.utc)
        update = {
            "reviewer_id": _ref(correction.reviewer_id),
            "status": correction.status,
            "decision": correction.decision,
            "review_started_at": correction.review_started_at,
            "reviewed_at": correction.reviewed_at,
            "review_note": correction.review_note,
            "updated_at": now,
        }
        result = await self.collection.find_one_and_update(
            {"_id": oid},
            {"$set": update},
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def list_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        open_only: bool = False,
        student_id: str | None = None,
        course_id: str | None = None,
    ) -> tuple[list[AttendanceCorrection], int]:
        """Page correction requests in MongoDB."""
        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        elif open_only:
            query["status"] = {"$in": list(OPEN_STATES)}
        if student_id:
            query["student_id"] = _ref(student_id)
        if course_id:
            query["course_id"] = _ref(course_id)
        return await self.find_page(
            query,
            skip=skip,
            limit=limit,
            sort=[("requested_at", DESCENDING)],
        )
