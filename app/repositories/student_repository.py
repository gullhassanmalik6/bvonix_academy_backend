from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.models.student import Student
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.repositories.listing import clamp_limit, clamp_skip, sort_pairs, text_clause
from app.utils.helpers import oid_str

STUDENT_SORTS = {
    "created_at": [("created_at", ASCENDING)],
    "-created_at": [("created_at", DESCENDING)],
    "enrollment_date": [("enrollment_date", ASCENDING)],
    "-enrollment_date": [("enrollment_date", DESCENDING)],
}


class StudentRepository(BaseRepository[Student]):
    collection_name = "students"

    async def ensure_indexes(self) -> None:
        # Unique user_id - one student per user
        await self.collection.create_index([("user_id", ASCENDING)], unique=True)
        # Index on is_active for filtering
        await self.collection.create_index([("is_active", ASCENDING)])
        await self.collection.create_index([("created_at", DESCENDING)])
        await self.collection.create_index([("enrollment_date", DESCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Student:
        return Student(
            id=oid_str(doc["_id"]),
            user_id=oid_str(doc["user_id"]),
            enrollment_date=doc.get("enrollment_date") or datetime.now(timezone.utc),
            enrolled_courses=[oid_str(cid) for cid in doc.get("enrolled_courses", [])],
            is_active=doc.get("is_active", True),
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
        q: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Student], int]:
        """Page students in MongoDB. A name search joins the user account in the database."""
        ordering = sort_pairs(sort, allowed=STUDENT_SORTS, default="-created_at")
        if not q or not q.strip():
            return await self.find_page({}, skip=skip, limit=limit, sort=ordering)
        safe_skip = clamp_skip(skip)
        safe_limit = clamp_limit(limit)
        name_match = text_clause(q, ("account.full_name", "account.email"))
        name_match["account.archived_at"] = None
        pipeline: list[dict[str, Any]] = [
            {"$match": with_active({})},
            {
                "$lookup": {
                    "from": "users",
                    "localField": "user_id",
                    "foreignField": "_id",
                    "as": "account",
                }
            },
            {"$unwind": "$account"},
            {"$match": name_match},
            {"$sort": {field: direction for field, direction in ordering}},
            {
                "$facet": {
                    "rows": [{"$skip": safe_skip}, {"$limit": safe_limit}],
                    "count": [{"$count": "total"}],
                }
            },
        ]
        docs = await self.collection.aggregate(pipeline).to_list(length=1)
        if not docs:
            return [], 0
        facet = docs[0]
        total = int(facet["count"][0]["total"]) if facet.get("count") else 0
        return [self._to_model(row) for row in facet.get("rows", [])], total

    async def find_active_by_user_ids(self, user_ids: list[str]) -> list[Student]:
        """Load the active student profiles for an already bounded set of user ids."""
        oids = []
        for user_id in user_ids[:100]:
            try:
                oids.append(ObjectId(user_id))
            except Exception:
                continue
        if not oids:
            return []
        docs = await self.collection.find(with_active({"user_id": {"$in": oids}})).to_list(length=len(oids))
        return [self._to_model(doc) for doc in docs]

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
        doc = await self.collection.find_one(with_active({"user_id": user_oid}))
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
