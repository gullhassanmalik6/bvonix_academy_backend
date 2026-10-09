from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.models.scholarship import Scholarship
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.repositories.listing import sort_pairs, text_clause
from app.utils.helpers import oid_str

SCHOLARSHIP_SORTS = {
    "created_at": [("created_at", ASCENDING)],
    "-created_at": [("created_at", DESCENDING)],
    "amount": [("amount", ASCENDING)],
    "-amount": [("amount", DESCENDING)],
    "status": [("status", ASCENDING), ("created_at", DESCENDING)],
}


class ScholarshipRepository(BaseRepository[Scholarship]):
    collection_name = "scholarships"

    async def ensure_indexes(self) -> None:
        # Index on student_id for quick lookups
        await self.collection.create_index([("student_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("status", ASCENDING)])
        await self.collection.create_index([("student_id", ASCENDING), ("status", ASCENDING)])
        await self.collection.create_index([("created_at", DESCENDING)])
        await self.collection.create_index([("status", ASCENDING), ("created_at", DESCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Scholarship:
        return Scholarship(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc.get("course_id")) if doc.get("course_id") else None,
            enrollment_id=oid_str(doc["enrollment_id"]) if doc.get("enrollment_id") else None,
            scholarship_type=doc.get("scholarship_type", "partial"),
            amount=doc.get("amount", 0.0),
            status=doc.get("status", "pending"),
            start_date=doc.get("start_date") or datetime.now(timezone.utc),
            end_date=doc.get("end_date"),
            termination_reason=doc.get("termination_reason"),
            terminated_at=doc.get("terminated_at"),
            terminated_by=oid_str(doc["terminated_by"]) if doc.get("terminated_by") else None,
            max_absences_per_month=doc.get("max_absences_per_month", 3),
            current_month_absences=doc.get("current_month_absences", 0),
            current_month_start=doc.get("current_month_start") or datetime.now(timezone.utc).replace(day=1),
            notes=doc.get("notes"),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
        )

    async def list_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        student_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Scholarship], int]:
        """Filter, search, sort, and page scholarships in MongoDB."""
        query: dict[str, Any] = {}
        if student_id:
            try:
                query["student_id"] = ObjectId(student_id)
            except Exception:
                return [], 0
        if status:
            query["status"] = status
        if q and q.strip():
            query["$or"] = text_clause(q, ("scholarship_type", "notes", "status"))["$or"]
        return await self.find_page(
            query,
            skip=skip,
            limit=limit,
            sort=sort_pairs(sort, allowed=SCHOLARSHIP_SORTS, default="-created_at"),
        )

    async def get_by_id(self, scholarship_id: str) -> Scholarship | None:
        doc = await self.find_document_by_id(scholarship_id)
        return self._to_model(doc) if doc else None

    async def get_by_student(self, student_id: str, status: str | None = None) -> list[Scholarship]:
        """Get all scholarships for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        
        query: dict[str, Any] = {"student_id": student_oid}
        if status:
            query["status"] = status
        return await self.collect(query, sort=[("created_at", DESCENDING)])

    async def page_for_student(
        self,
        student_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Scholarship], int]:
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return [], 0
        return await self.find_page(
            {"student_id": student_oid},
            skip=skip,
            limit=limit,
            sort=[("created_at", DESCENDING)],
        )

    async def get_active_by_student(self, student_id: str) -> list[Scholarship]:
        """Get active scholarships for a student."""
        return await self.get_by_student(student_id, status="active")

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> list[Scholarship]:
        """Get scholarships for a student in a specific course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        return await self.collect(
            {
                "student_id": student_oid,
                "$or": [
                    {"course_id": course_oid},
                    {"course_id": None},
                ],
            },
            sort=[("created_at", DESCENDING)],
        )

    async def create_scholarship(
        self,
        *,
        student_id: str,
        course_id: str | None = None,
        enrollment_id: str | None = None,
        scholarship_type: str,
        amount: float,
        start_date: datetime,
        end_date: datetime | None = None,
        max_absences_per_month: int = 3,
        notes: str | None = None,
    ) -> Scholarship:
        now = datetime.now(timezone.utc)
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id) if course_id else None
            enrollment_oid = ObjectId(enrollment_id) if enrollment_id else None
        except Exception:
            raise ValueError("Invalid IDs")
        
        # Set current month start
        current_month_start = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        payload = {
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_id": enrollment_oid,
            "scholarship_type": scholarship_type,
            "amount": amount,
            "status": "active",
            "start_date": start_date,
            "end_date": end_date,
            "termination_reason": None,
            "terminated_at": None,
            "terminated_by": None,
            "max_absences_per_month": max_absences_per_month,
            "current_month_absences": 0,
            "current_month_start": current_month_start,
            "notes": notes,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    async def increment_absence(self, scholarship_id: str) -> Scholarship | None:
        """Increment absence count for current month."""
        now = datetime.now(timezone.utc)
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        try:
            oid = ObjectId(scholarship_id)
        except Exception:
            return None
        
        doc = await self.collection.find_one(with_active({"_id": oid}))
        if not doc:
            return None
        
        scholarship = self._to_model(doc)
        
        # If new month, reset counter; otherwise increment
        if scholarship.current_month_start < current_month_start:
            update_op: dict[str, Any] = {
                "$set": {
                    "current_month_absences": 1,
                    "current_month_start": current_month_start,
                    "updated_at": now,
                }
            }
        else:
            update_op = {
                "$inc": {"current_month_absences": 1},
                "$set": {"updated_at": now},
            }

        result = await self.collection.find_one_and_update(
            with_active({"_id": oid}),
            update_op,
            return_document=True,
        )

        if result:
            updated = self._to_model(result)
            if updated.current_month_absences >= updated.max_absences_per_month:
                await self.terminate_scholarship(
                    scholarship_id,
                    "Exceeded maximum absences per month",
                    terminated_by=None,
                )
                return await self.get_by_id(scholarship_id)
            return updated
        return None

    async def terminate_scholarship(
        self,
        scholarship_id: str,
        reason: str,
        terminated_by: str | None = None,
    ) -> Scholarship | None:
        """Terminate a scholarship."""
        now = datetime.now(timezone.utc)
        try:
            oid = ObjectId(scholarship_id)
        except Exception:
            return None

        update_fields: dict[str, Any] = {
            "status": "terminated",
            "termination_reason": reason,
            "terminated_at": now,
            "updated_at": now,
        }
        if terminated_by:
            try:
                update_fields["terminated_by"] = ObjectId(terminated_by)
            except Exception:
                pass

        result = await self.collection.find_one_and_update(
            with_active({"_id": oid}),
            {"$set": update_fields},
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def reset_monthly_absences(self, scholarship_id: str) -> Scholarship | None:
        """Reset monthly absence counter (called when new month starts)."""
        now = datetime.now(timezone.utc)
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        try:
            oid = ObjectId(scholarship_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            with_active({"_id": oid}),
            {
                "$set": {
                    "current_month_absences": 0,
                    "current_month_start": current_month_start,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
        return self._to_model(result) if result else None
