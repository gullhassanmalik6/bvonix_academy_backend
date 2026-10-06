from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.attendance import Attendance
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class AttendanceRepository(BaseRepository[Attendance]):
    collection_name = "attendances"

    async def ensure_indexes(self) -> None:
        # Unique attendance per student-course-date
        await self.collection.create_index(
            [("student_id", ASCENDING), ("course_id", ASCENDING), ("date", ASCENDING)],
            unique=True
        )
        await self.collection.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
        await self.collection.create_index([("enrollment_id", ASCENDING)])
        await self.collection.create_index([("date", ASCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Attendance:
        return Attendance(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_id=oid_str(doc["enrollment_id"]),
            date=doc.get("date") or datetime.now(timezone.utc),
            status=doc.get("status", "absent"),
            marked_by=oid_str(doc["marked_by"]),
            notes=doc.get("notes"),
            absence_reason=doc.get("absence_reason"),
            absence_reason_submitted_at=doc.get("absence_reason_submitted_at"),
            is_excused=doc.get("is_excused", False),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> list[Attendance]:
        """Get all attendance records for a student in a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        cursor = self.collection.find({"student_id": student_oid, "course_id": course_oid}).sort("date", -1)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_by_enrollment(self, enrollment_id: str) -> list[Attendance]:
        """Get all attendance records for an enrollment."""
        try:
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            return []
        cursor = self.collection.find({"enrollment_id": enrollment_oid}).sort("date", -1)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def create_attendance(
        self,
        *,
        student_id: str,
        course_id: str,
        enrollment_id: str,
        date: datetime,
        status: str,
        marked_by: str,
        notes: str | None = None,
        absence_reason: str | None = None,
        is_excused: bool = False,
    ) -> Attendance:
        now = datetime.now(timezone.utc)
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
            enrollment_oid = ObjectId(enrollment_id)
            marked_by_oid = ObjectId(marked_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        payload = {
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_id": enrollment_oid,
            "date": date,
            "status": status,
            "marked_by": marked_by_oid,
            "notes": notes,
            "absence_reason": absence_reason,
            "absence_reason_submitted_at": now if absence_reason else None,
            "is_excused": is_excused,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    async def submit_absence_reason(
        self,
        attendance_id: str,
        absence_reason: str,
    ) -> Attendance | None:
        """Submit absence reason for an attendance record."""
        now = datetime.now(timezone.utc)
        try:
            oid = ObjectId(attendance_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            {"_id": oid},
            {
                "$set": {
                    "absence_reason": absence_reason,
                    "absence_reason_submitted_at": now,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def get_attendance_stats(self, student_id: str, course_id: str) -> dict[str, int]:
        """Get attendance statistics for a student in a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return {"present": 0, "absent": 0, "late": 0, "excused": 0, "total": 0}
        
        pipeline = [
            {"$match": {"student_id": student_oid, "course_id": course_oid}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        stats = {"present": 0, "absent": 0, "late": 0, "excused": 0, "total": 0}
        async for doc in self.collection.aggregate(pipeline):
            status = doc["_id"]
            count = doc["count"]
            if status in stats:
                stats[status] = count
            stats["total"] += count
        
        return stats

    async def count_statuses(self) -> dict[str, int]:
        """Count every stored attendance mark by status."""
        pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
        counts: dict[str, int] = {}
        async for doc in self.collection.aggregate(pipeline):
            if doc.get("_id") is None:
                continue
            counts[str(doc["_id"])] = int(doc["count"])
        return counts
