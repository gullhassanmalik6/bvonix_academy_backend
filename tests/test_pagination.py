"""Pagination walks every matching row and does not stop at a fixed cap."""

from __future__ import annotations

import asyncio
import inspect
import re
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from bson import ObjectId

from app.models.user import User
from app.repositories.announcement_repository import AnnouncementRepository
from app.repositories.assignment_repository import AssignmentRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.certificate_repository import CertificateRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.listing import MAX_PAGE_SIZE, clamp_limit, clamp_skip
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.scholarship_repository import ScholarshipRepository
from app.repositories.student_repository import StudentRepository
from app.routes.lms import get_my_enrollments, get_student_dashboard
from app.services.course_material_service import CourseMaterialService
import add_dummy_data
import fetch_data
import remove_dummy_enrollments


def _run(coro):
    return asyncio.run(coro)


NOW = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _field(document: dict, key: str):
    if key in document or "." not in key:
        return document.get(key)
    current = document
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _matches(document: dict, query: dict) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
            continue
        if (key == "archived_at" or key.endswith(".archived_at")) and expected is None:
            if _field(document, key) is not None:
                return False
            continue
        if isinstance(expected, dict) and "$ne" in expected:
            if _field(document, key) == expected["$ne"]:
                return False
            continue
        if isinstance(expected, dict) and "$in" in expected:
            if _field(document, key) not in expected["$in"]:
                return False
            continue
        if isinstance(expected, dict) and ("$gte" in expected or "$lte" in expected):
            value = _field(document, key)
            if value is None:
                return False
            if "$gte" in expected and value < expected["$gte"]:
                return False
            if "$lte" in expected and value > expected["$lte"]:
                return False
            continue
        if isinstance(expected, dict) and "$regex" in expected:
            flags = re.IGNORECASE if "i" in str(expected.get("$options", "")) else 0
            if re.search(expected["$regex"], str(_field(document, key) or ""), flags) is None:
                return False
            continue
        if _field(document, key) != expected:
            return False
    return True


def _eval(document: dict, expression):
    if isinstance(expression, str) and expression.startswith("$"):
        return _field(document, expression[1:])
    if not isinstance(expression, dict) or len(expression) != 1:
        return expression
    operator, argument = next(iter(expression.items()))
    if not isinstance(operator, str) or not operator.startswith("$"):
        return expression
    if operator == "$ifNull":
        value = _eval(document, argument[0])
        return value if value is not None else _eval(document, argument[1])
    if operator == "$multiply":
        total = 1
        for item in argument:
            total *= _eval(document, item)
        return total
    if operator == "$divide":
        return _eval(document, argument[0]) / _eval(document, argument[1])
    if operator == "$and":
        return all(_eval(document, item) for item in argument)
    if operator == "$or":
        return any(_eval(document, item) for item in argument)
    if operator == "$eq":
        return _eval(document, argument[0]) == _eval(document, argument[1])
    if operator == "$ne":
        return _eval(document, argument[0]) != _eval(document, argument[1])
    if operator == "$type":
        if isinstance(argument, str) and argument.startswith("$"):
            name = argument[1:]
            if name not in document:
                return "missing"
            value = document[name]
        else:
            value = _eval(document, argument)
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "double"
        if isinstance(value, str):
            return "string"
        return "object"
    if operator == "$gte":
        return _eval(document, argument[0]) >= _eval(document, argument[1])
    if operator == "$cond":
        test, yes, no = argument
        return _eval(document, yes if _eval(document, test) else no)
    if operator == "$switch":
        for branch in argument["branches"]:
            if _eval(document, branch["case"]):
                return _eval(document, branch["then"])
        return _eval(document, argument.get("default"))
    raise AssertionError(f"Unsupported aggregation expression: {expression}")


def _group_identity(document: dict, id_spec):
    if isinstance(id_spec, dict):
        return {name: _eval(document, value) for name, value in id_spec.items()}
    return _eval(document, id_spec)


def _apply_pipeline(documents: list[dict], pipeline: list[dict], database) -> list[dict]:
    docs = list(documents)
    for stage in pipeline:
        if "$match" in stage:
            docs = [document for document in docs if _matches(document, stage["$match"])]
            continue
        if "$lookup" in stage:
            spec = stage["$lookup"]
            foreign = database[spec["from"]].documents if database is not None else []
            joined = []
            for document in docs:
                copied = dict(document)
                local_value = document.get(spec["localField"])
                copied[spec["as"]] = [
                    item for item in foreign if item.get(spec["foreignField"]) == local_value
                ]
                joined.append(copied)
            docs = joined
            continue
        if "$unwind" in stage:
            path = stage["$unwind"]
            name = path[1:] if isinstance(path, str) and path.startswith("$") else path
            unwound = []
            for document in docs:
                values = document.get(name) or []
                for value in values:
                    copied = dict(document)
                    copied[name] = value
                    unwound.append(copied)
            docs = unwound
            continue
        if "$addFields" in stage:
            updated = []
            for document in docs:
                copied = dict(document)
                for name, expression in stage["$addFields"].items():
                    copied[name] = _eval(document, expression)
                updated.append(copied)
            docs = updated
            continue
        if "$sort" in stage:
            ordered = list(docs)
            for field, direction in reversed(list(stage["$sort"].items())):
                ordered.sort(
                    key=lambda document, name=field: (
                        _field(document, name) is None,
                        "" if _field(document, name) is None else _field(document, name),
                    ),
                    reverse=direction < 0,
                )
            docs = ordered
            continue
        if "$limit" in stage:
            docs = docs[: stage["$limit"]]
            continue
        if "$project" in stage:
            projected = []
            for document in docs:
                row = {}
                include_id = stage["$project"].get("_id", 1) != 0
                for name, flag in stage["$project"].items():
                    if name == "_id":
                        continue
                    if flag == 1:
                        row[name] = document.get(name)
                    elif isinstance(flag, dict):
                        row[name] = _eval(document, flag)
                if include_id:
                    row["_id"] = document.get("_id")
                projected.append(row)
            docs = projected
            continue
        if "$group" in stage:
            spec = stage["$group"]
            grouped: dict[tuple, dict] = {}
            order: list[tuple] = []
            for document in docs:
                identity = _group_identity(document, spec["_id"])
                key = tuple(sorted(identity.items())) if isinstance(identity, dict) else (identity,)
                if key not in grouped:
                    bucket = {"_id": identity}
                    for name, accumulator in spec.items():
                        if name == "_id":
                            continue
                        if isinstance(accumulator, dict) and "$sum" in accumulator:
                            value = 1 if accumulator["$sum"] == 1 else _eval(document, accumulator["$sum"])
                            bucket[name] = value or 0
                        elif isinstance(accumulator, dict) and "$first" in accumulator:
                            bucket[name] = _eval(document, accumulator["$first"])
                        else:
                            raise AssertionError(f"Unsupported group accumulator: {accumulator}")
                    grouped[key] = bucket
                    order.append(key)
                    continue
                bucket = grouped[key]
                for name, accumulator in spec.items():
                    if name == "_id" or not isinstance(accumulator, dict) or "$sum" not in accumulator:
                        continue
                    value = 1 if accumulator["$sum"] == 1 else (_eval(document, accumulator["$sum"]) or 0)
                    bucket[name] += value
            docs = [grouped[key] for key in order]
            continue
        if "$facet" in stage:
            facets = {
                name: _apply_pipeline(docs, subpipeline, database)
                for name, subpipeline in stage["$facet"].items()
            }
            return [facets]
        raise AssertionError(f"Unsupported aggregation stage: {stage}")
    return docs


class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = list(documents)
        self._skip = 0
        self._limit: int | None = None

    def sort(self, spec):
        if isinstance(spec, str):
            return self
        for field, direction in reversed(list(spec)):
            self.documents.sort(
                key=lambda document, name=field: (
                    document.get(name) is None,
                    "" if document.get(name) is None else document.get(name),
                ),
                reverse=direction < 0,
            )
        return self

    def skip(self, count: int):
        self._skip = count
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        size = self._limit if self._limit is not None else length
        if size is None:
            return self.documents[self._skip:]
        return self.documents[self._skip:self._skip + size]


class _Collection:
    def __init__(self, documents: list[dict] | None = None, database=None) -> None:
        self.documents = list(documents or [])
        self.queries: list[dict] = []
        self.database = database

    def find(self, query: dict | None = None) -> _Cursor:
        query = query or {}
        self.queries.append(query)
        return _Cursor([document for document in self.documents if _matches(document, query)])

    async def count_documents(self, query: dict | None = None) -> int:
        query = query or {}
        self.queries.append(query)
        return sum(1 for document in self.documents if _matches(document, query))

    async def find_one(self, query: dict) -> dict | None:
        self.queries.append(query)
        for document in self.documents:
            if _matches(document, query):
                return document
        return None

    async def insert_one(self, document: dict) -> SimpleNamespace:
        stored = dict(document)
        stored.setdefault("_id", ObjectId())
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def find_one_and_update(self, query: dict, update: dict, return_document: bool = False) -> dict | None:
        del return_document
        self.queries.append(query)
        for document in self.documents:
            if _matches(document, query):
                document.update(update.get("$set", {}))
                return document
        return None

    def aggregate(self, pipeline: list[dict]):
        """Evaluate the aggregation stages used by stats and performance summaries."""
        self.queries.append({"aggregate": pipeline})
        docs = _apply_pipeline(self.documents, pipeline, self.database)

        class _Aggregate:
            def __aiter__(self):
                async def _rows():
                    for row in docs:
                        yield row
                return _rows()

        return _Aggregate()


class _Database:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def add(self, name: str, documents: list[dict]) -> _Collection:
        collection = _Collection(documents, database=self)
        self._collections[name] = collection
        return collection

    def __getitem__(self, name: str) -> _Collection:
        if name not in self._collections:
            self._collections[name] = _Collection(database=self)
        return self._collections[name]


def _enrollment(student_id: ObjectId, course_id: ObjectId, *, status: str, verified: bool, archived_at=None, include_archived: bool = True) -> dict:
    document = {
        "_id": ObjectId(),
        "student_id": student_id,
        "course_id": course_id,
        "enrollment_date": NOW,
        "status": status,
        "payment_status": "paid",
        "verified_by_admin": verified,
        "created_at": NOW,
        "updated_at": NOW,
    }
    if include_archived:
        document["archived_at"] = archived_at
    return document


class PaginationBoundsTests(unittest.TestCase):
    def test_limits_are_clamped_and_pages_do_not_skip_or_repeat(self) -> None:
        self.assertEqual(clamp_skip(-4), 0)
        self.assertEqual(clamp_limit(0), 1)
        self.assertEqual(clamp_limit(-8), 1)
        self.assertEqual(clamp_limit(10000), MAX_PAGE_SIZE)

        student_id, course_id = ObjectId(), ObjectId()
        rows = [
            _enrollment(student_id, course_id, status="active", verified=True, include_archived=False)
            for _index in range(1001)
        ]
        rows.append(_enrollment(student_id, course_id, status="active", verified=True, archived_at=NOW))
        db = _Database()
        db.add("enrollments", rows)
        repo = EnrollmentRepository(db)

        collected = _run(repo.get_by_student(str(student_id)))
        self.assertEqual(len(collected), 1001)
        self.assertEqual(len({item.id for item in collected}), 1001)
        expected = [str(row["_id"]) for row in rows if row.get("archived_at") is None]
        self.assertEqual([item.id for item in collected], expected)

        seen: list[str] = []
        skip = 0
        total = None
        while True:
            page, page_total = _run(repo.find_page({"student_id": student_id}, skip=skip, limit=10000))
            if total is None:
                total = page_total
            self.assertEqual(page_total, 1001)
            self.assertLessEqual(len(page), MAX_PAGE_SIZE)
            if not page:
                break
            seen.extend(item.id for item in page)
            skip += len(page)
            if skip >= page_total:
                break
        self.assertEqual(seen, expected)
        self.assertEqual(total, 1001)

        first, first_total = _run(repo.find_page({"student_id": student_id}, skip=-5, limit=0))
        self.assertEqual(first_total, 1001)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].id, expected[0])
        self.assertEqual(_run(repo.get_by_student("not-an-id")), [])

    def test_enrollment_status_filters_match_the_returned_rows(self) -> None:
        student_id, course_id = ObjectId(), ObjectId()
        rows = [
            _enrollment(student_id, course_id, status="active", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="completed", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="cancelled", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="pending", verified=False, include_archived=False),
            _enrollment(student_id, course_id, status="active", verified=False, include_archived=False),
        ]
        db = _Database()
        db.add("enrollments", rows)
        repo = EnrollmentRepository(db)

        verified = _run(repo.get_verified_by_student(str(student_id)))
        self.assertEqual({item.status for item in verified}, {"active", "completed"})
        current = _run(repo.list_current_for_student(str(student_id)))
        self.assertEqual([item.status for item in current], ["active"])
        self.assertTrue(current[0].verified_by_admin)

        page, total = _run(repo.list_page(status="active", verified=True))
        self.assertEqual(total, 1)
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0].status, "active")
        self.assertTrue(any(query.get("status") == "active" and query.get("verified_by_admin") is True for query in db["enrollments"].queries))

    def test_relationship_reads_pass_the_old_fixed_caps(self) -> None:
        student_id, course_id, actor_id = ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("payments", [
            {"_id": ObjectId(), "student_id": student_id, "course_id": course_id, "amount": index, "created_at": NOW}
            for index in range(150)
        ] + [{"_id": ObjectId(), "student_id": student_id, "course_id": course_id, "archived_at": NOW, "created_at": NOW}])
        db.add("scholarships", [
            {"_id": ObjectId(), "student_id": student_id, "course_id": course_id, "status": "active", "created_at": NOW}
            for _index in range(120)
        ])
        db.add("attendances", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_id": ObjectId(),
                "date": NOW,
                "status": "present",
                "marked_by": actor_id,
            }
            for _index in range(130)
        ])
        db.add("results", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_id": ObjectId(),
                "issued_by": actor_id,
                "marks_obtained": 80,
                "total_marks": 100,
            }
            for _index in range(140)
        ])
        db.add("certificates", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_id": ObjectId(),
                "issued_by": actor_id,
                "certificate_number": f"C-{index}",
            }
            for index in range(110)
        ])
        db.add("course_materials", [
            {
                "_id": ObjectId(),
                "course_id": course_id,
                "title": f"Lesson {index}",
                "created_by": actor_id,
                "is_published": True,
                "order": index,
            }
            for index in range(160)
        ])
        db.add("assignments", [
            {
                "_id": ObjectId(),
                "course_id": course_id,
                "title": f"Work {index}",
                "created_by": actor_id,
                "is_published": True,
            }
            for index in range(115)
        ])
        db.add("live_sessions", [
            {"_id": ObjectId(), "course_id": course_id, "title": f"Session {index}", "instructor_id": actor_id, "created_by": actor_id, "start_time": NOW}
            for index in range(105)
        ])
        db.add("announcements", [
            {
                "_id": ObjectId(),
                "course_id": course_id,
                "title": f"Note {index}",
                "content": "Hello",
                "created_by": actor_id,
                "is_published": True,
                "priority": "normal",
            }
            for index in range(125)
        ])
        db.add("notifications", [
            {
                "_id": ObjectId(),
                "user_id": actor_id,
                "title": f"Notice {index}",
                "message": "Update",
                "created_at": NOW,
                "is_read": False,
            }
            for index in range(150)
        ])

        self.assertEqual(len(_run(PaymentRepository(db).get_by_student(str(student_id)))), 150)
        self.assertEqual(len(_run(ScholarshipRepository(db).get_by_student(str(student_id)))), 120)
        self.assertEqual(len(_run(AttendanceRepository(db).get_by_student_and_course(str(student_id), str(course_id)))), 130)
        self.assertEqual(len(_run(ResultRepository(db).get_by_student(str(student_id)))), 140)
        self.assertEqual(len(_run(CertificateRepository(db).get_by_student(str(student_id)))), 110)
        self.assertEqual(len(_run(CourseMaterialRepository(db).get_by_course(str(course_id)))), 160)
        self.assertEqual(len(_run(AssignmentRepository(db).get_by_course(str(course_id)))), 115)
        self.assertEqual(len(_run(LiveSessionRepository(db).get_by_course(str(course_id)))), 105)
        self.assertEqual(len(_run(AnnouncementRepository(db).get_by_course(str(course_id)))), 125)

        notes = NotificationRepository(db)
        first = _run(notes.get_by_user(str(actor_id), limit=100, skip=0))
        second = _run(notes.get_by_user(str(actor_id), limit=100, skip=100))
        self.assertEqual(len(first), MAX_PAGE_SIZE)
        self.assertEqual(len(second), 50)
        self.assertEqual(len({item.id for item in first + second}), 150)

    def test_archived_parent_and_legacy_rows_follow_the_operational_filter(self) -> None:
        instructor_id, active_course, archived_course, legacy_course = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        actor_id = ObjectId()
        db = _Database()
        db.add("courses", [
            {
                "_id": active_course,
                "title": "Open",
                "description": "Open course",
                "instructor_id": instructor_id,
                "duration_hours": 4,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
            },
            {
                "_id": archived_course,
                "title": "Closed",
                "description": "Closed course",
                "instructor_id": instructor_id,
                "duration_hours": 4,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
                "archived_at": NOW,
            },
            {
                "_id": legacy_course,
                "title": "Legacy",
                "description": "Legacy course",
                "instructor_id": instructor_id,
                "duration_hours": 4,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
            },
        ])
        db.add("course_materials", [
            {"_id": ObjectId(), "course_id": active_course, "title": f"L{index}", "created_by": actor_id, "order": index}
            for index in range(3)
        ] + [
            {"_id": ObjectId(), "course_id": archived_course, "title": "Hidden", "created_by": actor_id},
            {"_id": ObjectId(), "course_id": active_course, "title": "Old lesson", "created_by": actor_id, "archived_at": NOW},
        ])
        courses = CourseRepository(db)
        owned = _run(courses.get_by_instructor(str(instructor_id)))
        self.assertEqual({item.id for item in owned}, {str(active_course), str(legacy_course)})

        service = CourseMaterialService(CourseMaterialRepository(db), courses=courses)
        hidden, hidden_total = _run(service.list_course_materials(str(archived_course), skip=0, limit=50))
        self.assertEqual(hidden, [])
        self.assertEqual(hidden_total, 0)
        page, total = _run(service.list_course_materials(str(active_course), skip=0, limit=2))
        rest, rest_total = _run(service.list_course_materials(str(active_course), skip=2, limit=2))
        self.assertEqual(total, 3)
        self.assertEqual(rest_total, 3)
        self.assertEqual(len(page) + len(rest), 3)
        self.assertEqual(len({item.id for item in page + rest}), 3)

    def test_dashboard_uses_the_current_enrollment_query(self) -> None:
        user_id, student_id, course_id, archived_course, instructor_id = (
            ObjectId(), ObjectId(), ObjectId(), ObjectId(), ObjectId()
        )
        db = _Database()
        db.add("users", [{
            "_id": user_id,
            "email": "ada@example.com",
            "full_name": "Ada",
            "hashed_password": "hashed",
            "is_active": True,
            "role": "user",
            "created_at": NOW,
        }])
        db.add("students", [{
            "_id": student_id,
            "user_id": user_id,
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("courses", [
            {
                "_id": course_id,
                "title": "Speech",
                "description": "Spoken",
                "instructor_id": instructor_id,
                "duration_hours": 4,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
            },
            {
                "_id": archived_course,
                "title": "Old",
                "description": "Old",
                "instructor_id": instructor_id,
                "duration_hours": 4,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
                "archived_at": NOW,
            },
        ])
        db.add("enrollments", [
            _enrollment(student_id, course_id, status="active", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="cancelled", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="completed", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="pending", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="active", verified=False, include_archived=False),
            _enrollment(student_id, archived_course, status="active", verified=True, include_archived=False),
        ])
        current = User(
            id=str(user_id),
            email="ada@example.com",
            full_name="Ada",
            hashed_password="hashed",
            is_active=True,
            role="user",
            created_at=NOW,
        )
        history = _run(get_my_enrollments(
            current,
            EnrollmentRepository(db),
            StudentRepository(db),
        ))
        self.assertEqual(len(history.items), 6)
        self.assertEqual(history.total, 6)
        dashboard = _run(get_student_dashboard(
            current,
            EnrollmentRepository(db),
            StudentRepository(db),
            CourseRepository(db),
            StudentRepository(db),
            StudentRepository(db),
            CourseMaterialService(CourseMaterialRepository(db), courses=CourseRepository(db)),
        ))
        self.assertEqual(len(dashboard["enrollments"]), 1)
        self.assertEqual(dashboard["enrollments"][0]["course_title"], "Speech")
        self.assertTrue(any(
            query.get("status") == "active" and query.get("verified_by_admin") is True
            for query in db["enrollments"].queries
        ))

    def test_maintenance_scripts_are_bounded_and_refuse_production(self) -> None:
        cleanup = inspect.getsource(remove_dummy_enrollments)
        seeder = inspect.getsource(add_dummy_data)
        export = inspect.getsource(fetch_data)
        self.assertIn("production", cleanup)
        self.assertIn("production", seeder)
        self.assertNotIn("limit=10000", cleanup)
        self.assertNotIn("to_list(length=1000)", cleanup)
        self.assertNotIn("to_list(length=None)", cleanup + seeder + export)
        self.assertIn("SystemExit", cleanup)
        self.assertIn("SystemExit", seeder)
        self.assertIn("SystemExit", export)
        self.assertIn("_purge_matching", cleanup)


if __name__ == "__main__":
    unittest.main()
