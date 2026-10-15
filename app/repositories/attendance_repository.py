from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.db.index_status import ensure_required_index
from app.models.attendance import Attendance
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class AttendanceRepository(BaseRepository[Attendance]):
    collection_name = "attendances"

    async def ensure_indexes(self) -> None:
        # Unique attendance per student-course-date
        await ensure_required_index(
            self.collection,
            [("student_id", ASCENDING), ("course_id", ASCENDING), ("date", ASCENDING)],
            unique=True,
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
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
        )

    async def get_by_id(self, attendance_id: str) -> Attendance | None:
        doc = await self.find_document_by_id(attendance_id)
        return self._to_model(doc) if doc else None

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> list[Attendance]:
        """Get all attendance records for a student in a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        return await self.collect(
            {"student_id": student_oid, "course_id": course_oid},
            sort=[("date", -1)],
        )

    async def page_for_student_course(
        self,
        student_id: str,
        course_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Attendance], int]:
        try:
            query = {"student_id": ObjectId(student_id), "course_id": ObjectId(course_id)}
        except Exception:
            return [], 0
        return await self.find_page(query, skip=skip, limit=limit, sort=[("date", -1)])

    async def find_by_session(self, student_id: str, course_id: str, date: datetime) -> Attendance | None:
        try:
            query = {
                "student_id": ObjectId(student_id),
                "course_id": ObjectId(course_id),
                "date": date,
            }
        except Exception:
            return None
        doc = await self.collection.find_one(with_active(query))
        return self._to_model(doc) if doc else None

    async def get_by_enrollment(self, enrollment_id: str) -> list[Attendance]:
        """Get all attendance records for an enrollment."""
        try:
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            return []
        return await self.collect(
            {"enrollment_id": enrollment_oid},
            sort=[("date", -1)],
        )

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
            {"$match": with_active({"student_id": student_oid, "course_id": course_oid})},
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

    async def stats_for_courses(self, student_id: str, course_ids: list[str]) -> dict[str, dict[str, int]]:
        """Count attendance marks for many courses in one aggregation per id chunk."""
        empty = {"present": 0, "absent": 0, "late": 0, "excused": 0, "total": 0}
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return {}
        oids = []
        for raw in course_ids:
            try:
                oids.append(ObjectId(raw))
            except Exception:
                continue
        stats = {oid_str(oid): dict(empty) for oid in oids}
        if not oids:
            return stats
        step = 100
        for start in range(0, len(oids), step):
            chunk = oids[start:start + step]
            pipeline = [
                {"$match": with_active({"student_id": student_oid, "course_id": {"$in": chunk}})},
                {"$group": {
                    "_id": {"course_id": "$course_id", "status": "$status"},
                    "count": {"$sum": 1},
                }},
            ]
            async for doc in self.collection.aggregate(pipeline):
                key = doc.get("_id") or {}
                course_key = oid_str(key.get("course_id")) if key.get("course_id") is not None else None
                status = key.get("status")
                count = int(doc.get("count") or 0)
                bucket = stats.setdefault(course_key or "", dict(empty))
                if status in bucket:
                    bucket[status] += count
                bucket["total"] += count
        return stats

    async def count_statuses(self) -> dict[str, int]:
        """Count every stored attendance mark by status."""
        pipeline = [
            {"$match": with_active()},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        counts: dict[str, int] = {}
        async for doc in self.collection.aggregate(pipeline):
            if doc.get("_id") is None:
                continue
            counts[str(doc["_id"])] = int(doc["count"])
        return counts
