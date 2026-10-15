from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.models.result import Result
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


_GRADE_BOUNDS = (
    (97, "A+"),
    (93, "A"),
    (90, "A-"),
    (87, "B+"),
    (83, "B"),
    (80, "B-"),
    (77, "C+"),
    (73, "C"),
    (70, "C-"),
    (67, "D+"),
    (63, "D"),
    (60, "D-"),
)


def calculate_grade(percentage: float) -> str:
    """Calculate grade based on percentage."""
    for threshold, grade in _GRADE_BOUNDS:
        if percentage >= threshold:
            return grade
    return "F"


class ResultRepository(BaseRepository[Result]):
    collection_name = "results"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
        await self.collection.create_index([("enrollment_id", ASCENDING)])
        await self.collection.create_index([("assessment_type", ASCENDING)])
        await self.collection.create_index([
            ("student_id", ASCENDING),
            ("archived_at", ASCENDING),
            ("issued_date", DESCENDING),
        ])

    def _to_model(self, doc: dict[str, Any]) -> Result:
        percentage = (doc.get("marks_obtained", 0) / doc.get("total_marks", 1)) * 100
        return Result(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]),
            enrollment_id=oid_str(doc["enrollment_id"]),
            assessment_type=doc.get("assessment_type", "assignment"),
            assessment_name=doc.get("assessment_name", ""),
            marks_obtained=doc.get("marks_obtained", 0.0),
            total_marks=doc.get("total_marks", 100.0),
            percentage=percentage,
            grade=doc.get("grade") or calculate_grade(percentage),
            feedback=doc.get("feedback"),
            issued_by=oid_str(doc["issued_by"]),
            issued_date=doc.get("issued_date") or datetime.now(timezone.utc),
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
        )

    async def get_by_student_and_course(self, student_id: str, course_id: str) -> list[Result]:
        """Get all results for a student in a course."""
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        return await self.collect(
            {"student_id": student_oid, "course_id": course_oid},
            sort=[("issued_date", -1)],
        )

    async def page_for_student(
        self,
        student_id: str,
        *,
        course_id: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Result], int]:
        try:
            query: dict[str, Any] = {"student_id": ObjectId(student_id)}
            if course_id is not None:
                query["course_id"] = ObjectId(course_id)
        except Exception:
            return [], 0
        return await self.find_page(query, skip=skip, limit=limit, sort=[("issued_date", -1)])

    async def summarize_for_student(self, student_id: str) -> dict[str, Any]:
        """Aggregate GPA inputs without returning every result document.

        Percentage is marks_obtained (missing means 0) divided by total_marks
        (missing means 1), times 100. A stored non-empty grade is kept; otherwise
        the same thresholds as calculate_grade apply. Each enrollment's final
        grade is the highest percentage, and an equal percentage keeps the later
        issued_date (then the smaller id). recent_assessment is the name on the
        latest issued_date. Only active results whose enrollment is the same
        student, admin-verified, and active or completed are included.
        """
        empty: dict[str, Any] = {
            "distribution": [],
            "by_enrollment": [],
            "recent_names": [],
            "recent": [],
        }
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return empty
        percentage = {
            "$multiply": [
                {
                    "$divide": [
                        {"$ifNull": ["$marks_obtained", 0]},
                        {"$ifNull": ["$total_marks", 1]},
                    ]
                },
                100,
            ]
        }
        stored_grade = {
            "$and": [
                {"$ne": [{"$ifNull": ["$grade", None]}, None]},
                {"$ne": ["$grade", ""]},
            ]
        }
        null_marks = {
            "$or": [
                {"$eq": [{"$type": "$marks_obtained"}, "null"]},
                {"$eq": [{"$type": "$total_marks"}, "null"]},
            ]
        }
        zero_total = {"$eq": ["$total_marks", 0]}
        invalid_marks = {"$or": [null_marks, zero_total]}
        branches = [
            {"case": {"$gte": ["$percentage", threshold]}, "then": grade}
            for threshold, grade in _GRADE_BOUNDS
        ]
        pipeline = [
            {"$match": with_active({"student_id": student_oid})},
            {
                "$lookup": {
                    "from": "enrollments",
                    "localField": "enrollment_id",
                    "foreignField": "_id",
                    "as": "enrollment",
                }
            },
            {"$unwind": "$enrollment"},
            {
                "$match": {
                    "enrollment.student_id": student_oid,
                    "enrollment.verified_by_admin": True,
                    "enrollment.status": {"$in": ["active", "completed"]},
                    "enrollment.archived_at": None,
                }
            },
            {"$addFields": {"null_marks": null_marks, "zero_total": zero_total}},
            {
                "$addFields": {
                    "percentage": {"$cond": [invalid_marks, None, percentage]},
                }
            },
            {
                "$addFields": {
                    "resolved_grade": {
                        "$cond": [
                            invalid_marks,
                            None,
                            {
                                "$cond": [
                                    stored_grade,
                                    "$grade",
                                    {"$switch": {"branches": branches, "default": "F"}},
                                ]
                            },
                        ]
                    }
                }
            },
            {
                "$facet": {
                    "distribution": [
                        {"$group": {"_id": "$resolved_grade", "count": {"$sum": 1}}},
                    ],
                    "by_enrollment": [
                        {"$sort": {"percentage": -1, "issued_date": -1, "_id": 1}},
                        {
                            "$group": {
                                "_id": "$enrollment_id",
                                "total_percentage": {"$sum": "$percentage"},
                                "count": {"$sum": 1},
                                "final_grade": {"$first": "$resolved_grade"},
                            }
                        },
                    ],
                    "recent_names": [
                        {"$sort": {"issued_date": -1, "_id": 1}},
                        {
                            "$group": {
                                "_id": "$enrollment_id",
                                "recent_assessment": {"$first": "$assessment_name"},
                            }
                        },
                    ],
                    "problems": [
                        {
                            "$group": {
                                "_id": None,
                                "null_marks": {"$sum": {"$cond": ["$null_marks", 1, 0]}},
                                "zero_total": {"$sum": {"$cond": ["$zero_total", 1, 0]}},
                            }
                        },
                    ],
                    "recent": [
                        {"$sort": {"issued_date": -1, "_id": 1}},
                        {"$limit": 10},
                        {
                            "$project": {
                                "_id": 1,
                                "course_id": 1,
                                "assessment_name": 1,
                                "assessment_type": 1,
                                "percentage": 1,
                                "resolved_grade": 1,
                                "issued_date": 1,
                            }
                        },
                    ],
                }
            },
        ]
        summary = empty
        async for document in self.collection.aggregate(pipeline):
            summary = document
            break
        problem_rows = summary.get("problems") or []
        problem = problem_rows[0] if problem_rows else {}
        if problem.get("null_marks"):
            raise TypeError("unsupported operand type(s) for /: 'NoneType' and 'int'")
        if problem.get("zero_total"):
            raise ZeroDivisionError("division by zero")
        return summary

    async def get_by_enrollment(self, enrollment_id: str) -> list[Result]:
        """Get all results for an enrollment."""
        try:
            enrollment_oid = ObjectId(enrollment_id)
        except Exception:
            return []
        return await self.collect(
            {"enrollment_id": enrollment_oid},
            sort=[("issued_date", -1)],
        )

    async def get_by_student(self, student_id: str) -> list[Result]:
        """Get every active result for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        return await self.collect(
            {"student_id": student_oid},
            sort=[("issued_date", -1)],
        )

    async def create_result(
        self,
        *,
        student_id: str,
        course_id: str,
        enrollment_id: str,
        assessment_type: str,
        assessment_name: str,
        marks_obtained: float,
        total_marks: float,
        feedback: str | None = None,
        issued_by: str,
    ) -> Result:
        now = datetime.now(timezone.utc)
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id)
            enrollment_oid = ObjectId(enrollment_id)
            issued_by_oid = ObjectId(issued_by)
        except Exception:
            raise ValueError("Invalid IDs")
        
        percentage = (marks_obtained / total_marks) * 100
        grade = calculate_grade(percentage)
        
        payload = {
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_id": enrollment_oid,
            "assessment_type": assessment_type,
            "assessment_name": assessment_name,
            "marks_obtained": marks_obtained,
            "total_marks": total_marks,
            "percentage": percentage,
            "grade": grade,
            "feedback": feedback,
            "issued_by": issued_by_oid,
            "issued_date": now,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
