"""Dashboard batching, bounded pages, and search totals.

Query counts come from the in-memory collection double. They show that course,
material, and attendance work stays constant as enrollment count grows. They are
not a live MongoDB explain plan.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.models.user import User
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.lms import get_my_enrollments, get_performance_dashboard, get_student_dashboard
from app.routes.search import search
from app.services.course_material_service import CourseMaterialService
try:
    from tests.test_pagination import NOW, _Database, _enrollment, _run
except ImportError:
    from test_pagination import NOW, _Database, _enrollment, _run


def _user(user_id: ObjectId) -> User:
    return User(
        id=str(user_id),
        email="ada@example.com",
        full_name="Ada",
        hashed_password="hashed",
        is_active=True,
        role="user",
        created_at=NOW,
    )


def _watch(collection):
    calls = {"find": 0, "aggregate": 0}
    original_find = collection.find
    original_aggregate = collection.aggregate

    def find(query=None):
        calls["find"] += 1
        return original_find(query)

    def aggregate(pipeline):
        calls["aggregate"] += 1
        return original_aggregate(pipeline)

    collection.find = find
    collection.aggregate = aggregate
    return calls


def _course(course_id: ObjectId, instructor_id: ObjectId, title: str, *, archived_at=None, include_archived: bool = True) -> dict:
    document = {
        "_id": course_id,
        "title": title,
        "description": title,
        "instructor_id": instructor_id,
        "duration_hours": 4,
        "price": 0,
        "is_published": True,
        "created_at": NOW,
        "updated_at": NOW,
    }
    if include_archived:
        document["archived_at"] = archived_at
    return document


def _people(enrollment_count: int):
    user_id, student_id, instructor_id, actor_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
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
    courses = []
    enrollments = []
    materials = []
    for index in range(enrollment_count):
        course_id = ObjectId()
        courses.append(_course(course_id, instructor_id, f"Course {index:03d}", include_archived=False))
        enrollments.append({
            "_id": ObjectId(),
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_date": NOW + timedelta(minutes=index),
            "status": "active",
            "payment_status": "paid",
            "verified_by_admin": True,
            "progress_percentage": 0,
            "created_at": NOW,
            "updated_at": NOW,
        })
        materials.append({
            "_id": ObjectId(),
            "course_id": course_id,
            "title": f"Lesson {index}",
            "material_type": "document",
            "order": 1,
            "is_published": True,
            "created_by": actor_id,
            "created_at": NOW,
            "updated_at": NOW,
        })
    db.add("courses", courses)
    db.add("enrollments", enrollments)
    db.add("course_materials", materials)
    return db, user_id, student_id


class DashboardBatchingTests(unittest.TestCase):
    def _dashboard(self, db, user_id, *, skip: int = 0, limit: int = 100):
        return _run(get_student_dashboard(
            _user(user_id),
            EnrollmentRepository(db),
            StudentRepository(db),
            CourseRepository(db),
            StudentRepository(db),
            StudentRepository(db),
            CourseMaterialService(CourseMaterialRepository(db), courses=CourseRepository(db)),
            skip=skip,
            limit=limit,
        ))

    def test_course_and_material_queries_stay_constant_as_enrollments_grow(self) -> None:
        counts = {}
        for size in (5, 20):
            db, user_id, _student_id = _people(size)
            course_calls = _watch(db["courses"])
            material_calls = _watch(db["course_materials"])
            dashboard = self._dashboard(db, user_id)
            self.assertEqual(len(dashboard["enrollments"]), size)
            self.assertEqual(dashboard["total"], size)
            self.assertEqual(
                [card["course_title"] for card in dashboard["enrollments"]],
                [f"Course {index:03d}" for index in range(size)],
            )
            self.assertTrue(all(card["total_materials"] == 1 for card in dashboard["enrollments"]))
            counts[size] = (course_calls["find"], material_calls["find"])

        self.assertEqual(counts[5], counts[20])
        self.assertEqual(counts[20][0], 1)
        self.assertEqual(counts[20][1], 1)
        self.assertLess(counts[20][0], 20)

    def test_dashboard_page_is_bounded_and_keeps_order(self) -> None:
        db, user_id, _student_id = _people(150)
        first = self._dashboard(db, user_id, limit=500)
        second = self._dashboard(db, user_id, skip=100, limit=100)
        self.assertEqual(first["limit"], 100)
        self.assertEqual(first["total"], 150)
        self.assertEqual(len(first["enrollments"]), 100)
        self.assertEqual(len(second["enrollments"]), 50)
        self.assertEqual(first["enrollments"][0]["course_title"], "Course 000")
        self.assertEqual(second["enrollments"][0]["course_title"], "Course 100")
        combined = [card["course_id"] for card in first["enrollments"] + second["enrollments"]]
        self.assertEqual(len(combined), len(set(combined)))

    def test_archived_parent_cancelled_and_duplicate_materials_are_handled(self) -> None:
        db, user_id, student_id = _people(1)
        legacy_id, archived_id, actor_id = ObjectId(), ObjectId(), ObjectId()
        instructor_id = db["courses"].documents[0]["instructor_id"]
        course_id = db["courses"].documents[0]["_id"]
        db["courses"].documents.append(_course(legacy_id, instructor_id, "Legacy", include_archived=False))
        db["courses"].documents.append(_course(archived_id, instructor_id, "Archived", archived_at=NOW))
        db["enrollments"].documents.extend([
            _enrollment(student_id, legacy_id, status="active", verified=True, include_archived=False),
            _enrollment(student_id, archived_id, status="active", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="cancelled", verified=True, include_archived=False),
            _enrollment(student_id, course_id, status="pending", verified=False, include_archived=False),
        ])
        material_id = ObjectId()
        db["course_materials"].documents = [
            {
                "_id": material_id,
                "course_id": course_id,
                "title": "Same lesson",
                "material_type": "document",
                "order": 1,
                "is_published": True,
                "created_by": actor_id,
                "created_at": NOW,
            },
            {
                "_id": material_id,
                "course_id": course_id,
                "title": "Same lesson again",
                "material_type": "document",
                "order": 2,
                "is_published": True,
                "created_by": actor_id,
                "created_at": NOW,
            },
        ]
        dashboard = self._dashboard(db, user_id)
        titles = [card["course_title"] for card in dashboard["enrollments"]]
        self.assertEqual(titles, ["Course 000", "Legacy"])
        self.assertNotIn("Archived", titles)
        speech = next(card for card in dashboard["enrollments"] if card["course_title"] == "Course 000")
        self.assertEqual(speech["total_materials"], 1)
        self.assertEqual(dashboard["total"], 3)

    def test_enrollment_history_page_reports_the_full_total(self) -> None:
        db, user_id, student_id = _people(120)
        history = _run(get_my_enrollments(
            _user(user_id),
            EnrollmentRepository(db),
            StudentRepository(db),
            skip=0,
            limit=500,
        ))
        self.assertEqual(history.total, 120)
        self.assertEqual(len(history.items), 100)
        self.assertEqual(history.limit, 100)
        self.assertEqual(history.skip, 0)


class PerformanceBatchingTests(unittest.TestCase):
    def _build(self, enrollment_count: int):
        user_id, student_id, instructor_id, actor_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("students", [{
            "_id": student_id,
            "user_id": user_id,
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        courses = []
        enrollments = []
        for index in range(enrollment_count):
            course_id = ObjectId()
            courses.append(_course(course_id, instructor_id, f"Course {index}", include_archived=False))
            enrollments.append({
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_date": NOW + timedelta(minutes=index),
                "status": "active",
                "payment_status": "paid",
                "verified_by_admin": True,
                "progress_percentage": 10,
                "created_at": NOW,
                "updated_at": NOW,
            })
        db.add("courses", courses)
        db.add("enrollments", enrollments)
        first_enrollment = enrollments[0]
        second_enrollment = enrollments[1]
        db.add("results", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": first_enrollment["course_id"],
                "enrollment_id": first_enrollment["_id"],
                "assessment_name": "Quiz",
                "assessment_type": "quiz",
                "marks_obtained": 80,
                "total_marks": 100,
                "grade": "B-",
                "issued_by": actor_id,
                "issued_date": NOW,
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": second_enrollment["course_id"],
                "enrollment_id": second_enrollment["_id"],
                "assessment_name": "Final",
                "assessment_type": "final",
                "marks_obtained": 90,
                "total_marks": 100,
                "grade": "A-",
                "issued_by": actor_id,
                "issued_date": NOW + timedelta(days=1),
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": first_enrollment["course_id"],
                "enrollment_id": first_enrollment["_id"],
                "assessment_name": "Archived paper",
                "assessment_type": "quiz",
                "marks_obtained": 10,
                "total_marks": 100,
                "grade": "F",
                "issued_by": actor_id,
                "issued_date": NOW,
                "archived_at": NOW,
            },
        ])
        db.add("attendances", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": first_enrollment["course_id"],
                "status": "present",
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": first_enrollment["course_id"],
                "status": "present",
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": first_enrollment["course_id"],
                "status": "absent",
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": first_enrollment["course_id"],
                "status": "present",
                "archived_at": NOW,
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": second_enrollment["course_id"],
                "status": "present",
            },
        ])
        return db, student_id

    def _performance(self, db, student_id):
        student = _run(StudentRepository(db).get_by_id(str(student_id)))
        attendance = db["attendances"]
        calls = _watch(attendance)
        payload = _run(get_performance_dashboard(
            verified_data=(student, None),
            result_repo=ResultRepository(db),
            course_repo=CourseRepository(db),
            attendance_repo=AttendanceRepository(db),
            enrollment_repo=EnrollmentRepository(db),
        ))
        return payload, calls, []

    def test_attendance_aggregation_does_not_grow_with_enrollments(self) -> None:
        small, _student_id = self._build(3)
        large, large_student = self._build(8)
        _small_payload, small_calls, _rows = self._performance(small, _student_id)
        payload, large_calls, enrollments = self._performance(large, large_student)
        self.assertEqual(small_calls["aggregate"], 1)
        self.assertEqual(large_calls["aggregate"], 1)

        by_title = {row["course_title"]: row for row in payload["course_performance"]}
        self.assertEqual(set(by_title), {"Course 0", "Course 1"})
        self.assertEqual(by_title["Course 0"]["average_percentage"], 80.0)
        self.assertEqual(by_title["Course 0"]["final_grade"], "B-")
        self.assertEqual(by_title["Course 1"]["average_percentage"], 90.0)
        self.assertEqual(by_title["Course 1"]["final_grade"], "A-")
        self.assertEqual(payload["overall_gpa"], 3.2)

        summary_by_title = {item["course_title"]: item for item in payload["attendance_summary"].values()}
        self.assertEqual(summary_by_title["Course 0"]["present"], 2)
        self.assertEqual(summary_by_title["Course 0"]["absent"], 1)
        self.assertEqual(summary_by_title["Course 0"]["total"], 3)
        self.assertEqual(summary_by_title["Course 0"]["percentage"], 66.67)
        self.assertEqual(summary_by_title["Course 1"]["percentage"], 100.0)
        self.assertNotIn("Archived paper", str(payload["recent_results"]))


class SearchMetadataTests(unittest.TestCase):
    def _courses(self):
        db = _Database()
        instructor_id = ObjectId()
        titles = ["Alpha Speech", "Beta Speech", "Gamma Speech"]
        for title in titles:
            db["courses"].documents.append(_course(ObjectId(), instructor_id, title, include_archived=False))
        db["courses"].documents.append(_course(ObjectId(), instructor_id, "Hidden Speech", archived_at=NOW))
        return db

    def _search(self, db, **kwargs):
        user = _user(ObjectId())
        user.role = "academic_manager"
        return _run(search(
            kwargs.get("q", "Speech"),
            kwargs.get("types", "course"),
            kwargs.get("limit", 20),
            CourseRepository(db),
            StudentRepository(db),
            UserRepository(db),
            user,
            skip=kwargs.get("skip", 0),
        ))

    def test_total_counts_every_match_and_pages_stay_ordered(self) -> None:
        db = self._courses()
        first = self._search(db, limit=1)
        second = self._search(db, limit=1, skip=1)
        third = self._search(db, limit=1, skip=2)
        empty = self._search(db, q="zzzz-none")
        self.assertEqual(first.total, 3)
        self.assertEqual([item.title for item in first.results], ["Alpha Speech"])
        self.assertEqual([item.title for item in second.results], ["Beta Speech"])
        self.assertEqual([item.title for item in third.results], ["Gamma Speech"])
        self.assertEqual(empty.total, 0)
        self.assertEqual(empty.results, [])
        self.assertNotIn("Hidden Speech", [item.title for item in first.results + second.results + third.results])

    def test_caller_limit_cannot_exceed_the_search_maximum(self) -> None:
        db = _Database()
        instructor_id = ObjectId()
        for index in range(60):
            db["courses"].documents.append(
                _course(ObjectId(), instructor_id, f"Speech {index:02d}", include_archived=False)
            )
        page = self._search(db, limit=80)
        self.assertEqual(page.limit, 50)
        self.assertEqual(len(page.results), 50)
        self.assertEqual(page.total, 60)


if __name__ == "__main__":
    unittest.main()
