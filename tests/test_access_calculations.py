"""Access checks and calculations stay exact without loading every enrollment."""

from __future__ import annotations

import unittest
from datetime import timedelta
from types import SimpleNamespace

from bson import ObjectId

from app.repositories.assignment_repository import AssignmentRepository, AssignmentSubmissionRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.models.user import User
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.student_repository import StudentRepository
from app.routes.lms import (
    get_all_my_results,
    get_announcements,
    get_attendance_stats,
    get_course_progress,
    get_my_attendance,
    get_my_results,
    get_performance_dashboard,
    submit_absence_reason,
)
from app.utils.exceptions import NotFoundError
from app.services.assignment_service import AssignmentService
from app.services.course_material_service import CourseMaterialService
try:
    from tests.test_pagination import NOW, _Database, _run
except ImportError:
    from test_pagination import NOW, _Database, _run


def _watch(collection):
    calls = {"find": 0, "find_one": 0, "count": 0}
    original_find = collection.find
    original_find_one = collection.find_one
    original_count = collection.count_documents

    def find(query=None):
        calls["find"] += 1
        return original_find(query)

    async def find_one(query):
        calls["find_one"] += 1
        return await original_find_one(query)

    async def count_documents(query=None):
        calls["count"] += 1
        return await original_count(query)

    collection.find = find
    collection.find_one = find_one
    collection.count_documents = count_documents
    return calls


def _enrollment(student_id, course_id, *, status, verified, when=None):
    return {
        "_id": ObjectId(),
        "student_id": student_id,
        "course_id": course_id,
        "enrollment_date": when or NOW,
        "status": status,
        "payment_status": "paid",
        "verified_by_admin": verified,
        "progress_percentage": 40,
        "created_at": NOW,
        "updated_at": NOW,
    }


class AccessCheckTests(unittest.TestCase):
    def test_one_course_check_does_not_read_the_enrollment_collection(self) -> None:
        student_id = ObjectId()
        target_course = ObjectId()
        db = _Database()
        rows = []
        for index in range(1000):
            rows.append(_enrollment(ObjectId(), ObjectId(), status="active", verified=True, when=NOW + timedelta(seconds=index)))
        active = _enrollment(student_id, target_course, status="active", verified=True)
        completed = _enrollment(student_id, ObjectId(), status="completed", verified=True)
        cancelled = _enrollment(student_id, ObjectId(), status="cancelled", verified=True)
        pending = _enrollment(student_id, ObjectId(), status="pending", verified=False)
        rows.extend([active, completed, cancelled, pending])
        db.add("enrollments", rows)
        repo = EnrollmentRepository(db)
        calls = _watch(db["enrollments"])

        granted = _run(repo.get_access_enrollment(str(student_id), str(target_course)))
        self.assertEqual(granted.id, str(active["_id"]))
        self.assertEqual(calls["find_one"], 1)
        self.assertEqual(calls["find"], 0)

        self.assertIsNotNone(_run(repo.get_access_enrollment(str(student_id), str(completed["course_id"]))))
        self.assertIsNone(_run(repo.get_access_enrollment(str(student_id), str(cancelled["course_id"]))))
        self.assertIsNone(_run(repo.get_access_enrollment(str(student_id), str(pending["course_id"]))))
        self.assertTrue(_run(repo.has_verified_enrollment(str(student_id))))
        self.assertEqual(calls["find"], 0)
        self.assertGreaterEqual(calls["find_one"], 5)


class ProgressCalculationTests(unittest.TestCase):
    def test_progress_counts_match_published_active_content(self) -> None:
        student_id, course_id, actor_id = ObjectId(), ObjectId(), ObjectId()
        enrollment = _enrollment(student_id, course_id, status="active", verified=True)
        archived_course = ObjectId()
        archived_enrollment = _enrollment(student_id, archived_course, status="active", verified=True)
        db = _Database()
        db.add("courses", [
            {
                "_id": course_id,
                "title": "Speech",
                "description": "Speech",
                "instructor_id": actor_id,
                "duration_hours": 2,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "_id": archived_course,
                "title": "Closed",
                "description": "Closed",
                "instructor_id": actor_id,
                "duration_hours": 2,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
                "updated_at": NOW,
                "archived_at": NOW,
            },
        ])
        db.add("enrollments", [enrollment, archived_enrollment])
        db.add("course_materials", [
            {"_id": ObjectId(), "course_id": course_id, "title": "One", "is_published": True, "created_by": actor_id, "created_at": NOW},
            {"_id": ObjectId(), "course_id": course_id, "title": "Two", "is_published": True, "created_by": actor_id, "created_at": NOW},
            {"_id": ObjectId(), "course_id": course_id, "title": "Draft", "is_published": False, "created_by": actor_id, "created_at": NOW},
            {"_id": ObjectId(), "course_id": course_id, "title": "Old", "is_published": True, "created_by": actor_id, "created_at": NOW, "archived_at": NOW},
            {"_id": ObjectId(), "course_id": archived_course, "title": "Hidden", "is_published": True, "created_by": actor_id, "created_at": NOW},
        ])
        db.add("assignments", [
            {"_id": ObjectId(), "course_id": course_id, "title": "Work", "is_published": True, "created_by": actor_id, "created_at": NOW},
            {"_id": ObjectId(), "course_id": course_id, "title": "Stored", "is_published": True, "created_by": actor_id, "created_at": NOW, "archived_at": NOW},
        ])
        material_calls = _watch(db["course_materials"])
        student = SimpleNamespace(id=str(student_id))
        courses = CourseRepository(db)
        payload = _run(get_course_progress(
            str(enrollment["_id"]),
            (student, None),
            EnrollmentRepository(db),
            CourseMaterialService(CourseMaterialRepository(db), courses=courses),
            AssignmentService(
                AssignmentRepository(db),
                AssignmentSubmissionRepository(db),
                courses=courses,
            ),
            courses,
        ))
        self.assertEqual(payload["progress_percentage"], 40)
        self.assertEqual(payload["total_materials"], 2)
        self.assertEqual(payload["total_assignments"], 1)
        self.assertEqual(payload["total_items"], 3)
        self.assertEqual(payload["completed_items"], 0)
        self.assertEqual(material_calls["find"], 0)
        self.assertEqual(material_calls["count"], 1)

        hidden = _run(get_course_progress(
            str(archived_enrollment["_id"]),
            (student, None),
            EnrollmentRepository(db),
            CourseMaterialService(CourseMaterialRepository(db), courses=courses),
            AssignmentService(
                AssignmentRepository(db),
                AssignmentSubmissionRepository(db),
                courses=courses,
            ),
            courses,
        ))
        self.assertEqual(hidden["total_materials"], 0)
        self.assertEqual(hidden["total_assignments"], 0)
        self.assertEqual(hidden["progress_percentage"], 40)


class PerformanceFormulaTests(unittest.TestCase):
    def test_streamed_gpa_matches_the_existing_grade_map(self) -> None:
        student_id, instructor_id, actor_id = ObjectId(), ObjectId(), ObjectId()
        active_course, other_course, cancelled_course = ObjectId(), ObjectId(), ObjectId()
        active = _enrollment(student_id, active_course, status="active", verified=True)
        other = _enrollment(student_id, other_course, status="completed", verified=True, when=NOW + timedelta(days=1))
        cancelled = _enrollment(student_id, cancelled_course, status="cancelled", verified=True, when=NOW + timedelta(days=2))
        db = _Database()
        db.add("students", [{
            "_id": student_id,
            "user_id": ObjectId(),
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("courses", [
            {
                "_id": course_id,
                "title": title,
                "description": title,
                "instructor_id": instructor_id,
                "duration_hours": 1,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
            for course_id, title in (
                (active_course, "Active"),
                (other_course, "Done"),
                (cancelled_course, "Cancelled"),
            )
        ])
        db.add("enrollments", [active, other, cancelled])
        db.add("results", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": active_course,
                "enrollment_id": active["_id"],
                "assessment_name": "Early",
                "assessment_type": "quiz",
                "marks_obtained": 90,
                "total_marks": 100,
                "issued_by": actor_id,
                "issued_date": NOW,
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": active_course,
                "enrollment_id": active["_id"],
                "assessment_name": "Later tie",
                "assessment_type": "quiz",
                "marks_obtained": 90,
                "total_marks": 100,
                "grade": "A",
                "issued_by": actor_id,
                "issued_date": NOW + timedelta(days=1),
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": other_course,
                "enrollment_id": other["_id"],
                "assessment_name": "Missing marks",
                "assessment_type": "quiz",
                "marks_obtained": 0,
                "issued_by": actor_id,
                "issued_date": NOW,
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": cancelled_course,
                "enrollment_id": cancelled["_id"],
                "assessment_name": "Should not count",
                "assessment_type": "final",
                "marks_obtained": 100,
                "total_marks": 100,
                "grade": "A+",
                "issued_by": actor_id,
                "issued_date": NOW + timedelta(days=3),
            },
        ])
        db.add("attendances", [])
        from app.repositories.attendance_repository import AttendanceRepository
        from app.repositories.student_repository import StudentRepository

        student = _run(StudentRepository(db).get_by_id(str(student_id)))
        payload = _run(get_performance_dashboard(
            verified_data=(student, None),
            result_repo=ResultRepository(db),
            course_repo=CourseRepository(db),
            attendance_repo=AttendanceRepository(db),
            enrollment_repo=EnrollmentRepository(db),
        ))
        by_title = {row["course_title"]: row for row in payload["course_performance"]}
        self.assertEqual(set(by_title), {"Active", "Done"})
        self.assertEqual(by_title["Active"]["average_percentage"], 90.0)
        self.assertEqual(by_title["Active"]["final_grade"], "A")
        self.assertEqual(by_title["Active"]["recent_assessment"], "Later tie")
        self.assertEqual(by_title["Done"]["final_grade"], "F")
        self.assertEqual(by_title["Done"]["average_percentage"], 0.0)
        # A is 4.0 and F is 0.0. The cancelled A+ is not included.
        self.assertEqual(payload["overall_gpa"], 2.0)
        self.assertEqual(payload["grade_distribution"], {"A-": 1, "A": 1, "F": 1})
        self.assertEqual(
            [item["assessment_name"] for item in payload["recent_results"]],
            ["Later tie", "Early", "Missing marks"],
        )
        self.assertEqual(payload["total_courses"], 2)
        self.assertEqual(payload["active_courses"], 1)
        self.assertEqual(payload["completed_courses"], 1)
        self.assertNotIn("Should not count", [item["assessment_name"] for item in payload["recent_results"]])

        empty_student = ObjectId()
        db["students"].documents.append({
            "_id": empty_student,
            "user_id": ObjectId(),
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        })
        db["enrollments"].documents.append(
            _enrollment(empty_student, active_course, status="active", verified=True)
        )
        empty = _run(StudentRepository(db).get_by_id(str(empty_student)))
        blank = _run(get_performance_dashboard(
            verified_data=(empty, None),
            result_repo=ResultRepository(db),
            course_repo=CourseRepository(db),
            attendance_repo=AttendanceRepository(db),
            enrollment_repo=EnrollmentRepository(db),
        ))
        self.assertEqual(blank["overall_gpa"], 0.0)
        self.assertEqual(blank["grade_distribution"], {})
        self.assertEqual(blank["course_performance"], [])
        self.assertEqual(blank["recent_results"], [])
        self.assertEqual(blank["total_courses"], 1)
        result_reads = [query for query in db["results"].queries if "aggregate" not in query]
        self.assertEqual(result_reads, [])
        self.assertEqual(sum("aggregate" in query for query in db["results"].queries), 2)


def _reference_performance(results: list[dict], enrollments: list[dict], student_id: ObjectId):
    """Recompute the published formula from stored rows, without calling the route."""
    points = {
        "A+": 4.0, "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
        "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0,
    }
    bounds = (
        (97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
        (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"), (60, "D-"),
    )

    def percentage(document: dict) -> float:
        marks = document["marks_obtained"] if "marks_obtained" in document else 0
        total = document["total_marks"] if "total_marks" in document else 1
        return (marks / total) * 100

    def grade_for(document: dict, score: float) -> str:
        stored = document.get("grade")
        if stored:
            return stored
        for threshold, grade in bounds:
            if score >= threshold:
                return grade
        return "F"

    eligible = {
        enrollment["_id"]
        for enrollment in enrollments
        if enrollment.get("archived_at") is None
        and enrollment["student_id"] == student_id
        and enrollment.get("verified_by_admin") is True
        and enrollment.get("status") in ("active", "completed")
    }
    chosen = []
    for document in results:
        if document.get("archived_at") is not None:
            continue
        if document.get("student_id") != student_id or document.get("enrollment_id") not in eligible:
            continue
        score = percentage(document)
        chosen.append((document, score, grade_for(document, score)))
    ordered = sorted(chosen, key=lambda item: item[0]["_id"])
    ordered.sort(key=lambda item: item[0]["issued_date"], reverse=True)
    summaries: dict = {}
    distribution: dict[str, int] = {}
    for document, score, grade in ordered:
        bucket = summaries.setdefault(document["enrollment_id"], {
            "sum": 0.0, "count": 0, "best": None, "grade": None, "recent": None,
        })
        bucket["sum"] += score
        bucket["count"] += 1
        if bucket["best"] is None or score > bucket["best"]:
            bucket["best"] = score
            bucket["grade"] = grade
        if bucket["recent"] is None:
            bucket["recent"] = document["assessment_name"]
        distribution[grade] = distribution.get(grade, 0) + 1
    gpa = 0.0
    if summaries:
        gpa = round(
            sum(points.get(bucket["grade"], 0.0) for bucket in summaries.values()) / len(summaries),
            2,
        )
    return {
        "gpa": gpa,
        "distribution": distribution,
        "recent": [document["assessment_name"] for document, _score, _grade in ordered[:10]],
        "rows": summaries,
    }


class PerformanceAggregationTests(unittest.TestCase):
    def test_aggregation_matches_the_reference_formula(self) -> None:
        student_id, actor_id = ObjectId(), ObjectId()
        courses = {
            "Alpha": ObjectId(),
            "Done": ObjectId(),
            "Blank grade": ObjectId(),
            "Unknown": ObjectId(),
            "Split": ObjectId(),
            "Cancelled": ObjectId(),
            "Pending": ObjectId(),
            "Unverified": ObjectId(),
            "Archived enrollment": ObjectId(),
        }
        enrollments = [
            _enrollment(student_id, courses["Alpha"], status="active", verified=True),
            _enrollment(student_id, courses["Done"], status="completed", verified=True),
            _enrollment(student_id, courses["Blank grade"], status="active", verified=True),
            _enrollment(student_id, courses["Unknown"], status="active", verified=True),
            _enrollment(student_id, courses["Split"], status="active", verified=True),
            _enrollment(student_id, courses["Cancelled"], status="cancelled", verified=True),
            _enrollment(student_id, courses["Pending"], status="pending", verified=True),
            _enrollment(student_id, courses["Unverified"], status="active", verified=False),
            _enrollment(student_id, courses["Archived enrollment"], status="active", verified=True),
        ]
        enrollments[-1]["archived_at"] = NOW
        by_course = {enrollment["course_id"]: enrollment for enrollment in enrollments}

        def row(course, name, marks, day, **extra):
            document = {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": courses[course],
                "enrollment_id": by_course[courses[course]]["_id"],
                "assessment_name": name,
                "assessment_type": "quiz",
                "marks_obtained": marks,
                "total_marks": 100,
                "issued_by": actor_id,
                "issued_date": NOW + timedelta(days=day),
            }
            document.update(extra)
            return document

        results = [
            row("Alpha", f"Extra {day}", 10, day) for day in range(1, 7)
        ] + [
            row("Split", "High", 95, 7),
            row("Done", "Missing marks", 0, 8),
            row("Blank grade", "Perfect", 100, 9, grade=""),
            row("Unknown", "Odd", 50, 10, grade="Nope"),
            row("Alpha", "Early", 90, 11),
            row("Split", "Latest lower", 70, 12, grade="C"),
            row("Alpha", "Later tie", 90, 13, grade="A"),
            row("Cancelled", "Cancelled win", 100, 30, grade="A+"),
            row("Pending", "Pending win", 100, 31, grade="A+"),
            row("Unverified", "Hidden win", 100, 32, grade="A+"),
            row("Archived enrollment", "Old enrollment", 100, 33, grade="A+"),
            row("Alpha", "Archived paper", 100, 34, grade="A+", archived_at=NOW),
        ]
        next(item for item in results if item["assessment_name"] == "Missing marks").pop("total_marks")
        db = _Database()
        db.add("students", [{
            "_id": student_id,
            "user_id": ObjectId(),
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("courses", [
            {
                "_id": course_id,
                "title": title,
                "description": title,
                "instructor_id": ObjectId(),
                "duration_hours": 1,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
            for title, course_id in courses.items()
        ])
        db.add("enrollments", enrollments)
        db.add("results", results)
        db.add("attendances", [])
        student = _run(StudentRepository(db).get_by_id(str(student_id)))
        payload = _run(get_performance_dashboard(
            verified_data=(student, None),
            result_repo=ResultRepository(db),
            course_repo=CourseRepository(db),
            attendance_repo=AttendanceRepository(db),
            enrollment_repo=EnrollmentRepository(db),
        ))
        expected = _reference_performance(results, enrollments, student_id)
        self.assertEqual(payload["overall_gpa"], expected["gpa"])
        self.assertEqual(payload["overall_gpa"], 2.4)
        self.assertEqual(payload["grade_distribution"], expected["distribution"])
        self.assertEqual(payload["grade_distribution"]["F"], 7)
        self.assertEqual(payload["grade_distribution"]["A+"], 1)
        self.assertEqual(
            [item["assessment_name"] for item in payload["recent_results"]],
            expected["recent"],
        )
        self.assertEqual(len(payload["recent_results"]), 10)
        self.assertEqual(payload["recent_results"][0]["assessment_name"], "Later tie")
        by_title = {item["course_title"]: item for item in payload["course_performance"]}
        self.assertEqual(set(by_title), {"Alpha", "Done", "Blank grade", "Unknown", "Split"})
        self.assertEqual(by_title["Alpha"]["final_grade"], "A")
        self.assertEqual(by_title["Alpha"]["recent_assessment"], "Later tie")
        self.assertEqual(by_title["Alpha"]["average_percentage"], 30.0)
        self.assertEqual(by_title["Done"]["final_grade"], "F")
        self.assertEqual(by_title["Done"]["average_percentage"], 0.0)
        self.assertEqual(by_title["Blank grade"]["final_grade"], "A+")
        self.assertEqual(by_title["Unknown"]["grade_point"], 0.0)
        self.assertEqual(by_title["Split"]["final_grade"], "A")
        self.assertEqual(by_title["Split"]["recent_assessment"], "Latest lower")
        self.assertEqual(
            [query for query in db["results"].queries if "aggregate" not in query],
            [],
        )
        self.assertEqual(sum("aggregate" in query for query in db["results"].queries), 1)

    def test_null_and_zero_marks_still_abort_the_dashboard(self) -> None:
        student_id, actor_id, course_id = ObjectId(), ObjectId(), ObjectId()
        enrollment = _enrollment(student_id, course_id, status="active", verified=True)

        def dashboard(marks, total):
            db = _Database()
            db.add("students", [{
                "_id": student_id,
                "user_id": ObjectId(),
                "enrollment_date": NOW,
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }])
            db.add("courses", [{
                "_id": course_id,
                "title": "Marks",
                "description": "Marks",
                "instructor_id": ObjectId(),
                "duration_hours": 1,
                "price": 0,
                "is_published": True,
                "created_at": NOW,
                "updated_at": NOW,
            }])
            db.add("enrollments", [enrollment])
            db.add("results", [{
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_id": enrollment["_id"],
                "assessment_name": "Broken",
                "assessment_type": "quiz",
                "marks_obtained": marks,
                "total_marks": total,
                "issued_by": actor_id,
                "issued_date": NOW,
            }])
            db.add("attendances", [])
            student = _run(StudentRepository(db).get_by_id(str(student_id)))
            return get_performance_dashboard(
                verified_data=(student, None),
                result_repo=ResultRepository(db),
                course_repo=CourseRepository(db),
                attendance_repo=AttendanceRepository(db),
                enrollment_repo=EnrollmentRepository(db),
            )

        with self.assertRaises(ZeroDivisionError):
            _run(dashboard(10, 0))
        with self.assertRaises(TypeError):
            _run(dashboard(None, 100))


class CourseAccessRouteTests(unittest.TestCase):
    def _student(self, db, student_id, user_id):
        db.add("students", [{
            "_id": student_id,
            "user_id": user_id,
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        return User(
            id=str(user_id),
            email="ada@example.com",
            full_name="Ada",
            hashed_password="hashed",
            is_active=True,
            role="user",
            created_at=NOW,
        )

    def test_course_routes_do_not_trust_the_general_existence_check(self) -> None:
        student_id, user_id, actor_id = ObjectId(), ObjectId(), ObjectId()
        allowed_course, other_course = ObjectId(), ObjectId()
        allowed = _enrollment(student_id, allowed_course, status="completed", verified=True)
        cancelled = _enrollment(student_id, other_course, status="cancelled", verified=True)
        db = _Database()
        user = self._student(db, student_id, user_id)
        db.add("enrollments", [allowed, cancelled])
        db.add("results", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": allowed_course,
                "enrollment_id": allowed["_id"],
                "assessment_name": "Kept",
                "assessment_type": "quiz",
                "marks_obtained": 80,
                "total_marks": 100,
                "issued_by": actor_id,
                "issued_date": NOW,
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": other_course,
                "enrollment_id": cancelled["_id"],
                "assessment_name": "Blocked",
                "assessment_type": "quiz",
                "marks_obtained": 100,
                "total_marks": 100,
                "grade": "A+",
                "issued_by": actor_id,
                "issued_date": NOW,
            },
        ])
        db.add("attendances", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": allowed_course,
                "enrollment_id": allowed["_id"],
                "status": "present",
                "marked_by": actor_id,
                "date": NOW,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": other_course,
                "enrollment_id": cancelled["_id"],
                "status": "absent",
                "marked_by": actor_id,
                "date": NOW,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ])
        student = SimpleNamespace(id=str(student_id))
        principal = (student, None)
        allowed_page = _run(get_my_results(
            str(allowed_course), 0, 100, principal, ResultRepository(db), EnrollmentRepository(db),
        ))
        blocked_page = _run(get_my_results(
            str(other_course), 0, 100, principal, ResultRepository(db), EnrollmentRepository(db),
        ))
        history = _run(get_all_my_results(0, 100, principal, ResultRepository(db)))
        self.assertEqual([item.assessment_name for item in allowed_page.items], ["Kept"])
        self.assertEqual(blocked_page.items, [])
        self.assertEqual(blocked_page.total, 0)
        self.assertEqual(
            sorted(item.assessment_name for item in history.items),
            ["Blocked", "Kept"],
        )

        hidden_attendance = _run(get_my_attendance(
            str(other_course),
            0,
            100,
            user,
            AttendanceRepository(db),
            StudentRepository(db),
            EnrollmentRepository(db),
        ))
        visible_attendance = _run(get_my_attendance(
            str(allowed_course),
            0,
            100,
            user,
            AttendanceRepository(db),
            StudentRepository(db),
            EnrollmentRepository(db),
        ))
        self.assertEqual(hidden_attendance.items, [])
        self.assertEqual(visible_attendance.total, 1)
        stats = _run(get_attendance_stats(
            str(other_course),
            principal,
            AttendanceRepository(db),
            EnrollmentRepository(db),
        ))
        self.assertEqual(stats, {
            "present": 0, "absent": 0, "late": 0, "excused": 0, "total": 0, "percentage": 0.0,
        })

        class _Announcements:
            def __init__(self):
                self.calls = []

            async def page_published(self, course_id, skip=0, limit=100):
                self.calls.append(course_id)
                return [SimpleNamespace(
                    id="ann-1",
                    course_id=course_id,
                    title="Room",
                    content="Bring notes",
                    priority="normal",
                    is_published=True,
                    published_at=NOW,
                    expires_at=None,
                    created_by=str(actor_id),
                    created_at=NOW,
                    updated_at=NOW,
                )], 1

        announcements = _Announcements()
        denied = _run(get_announcements(
            str(other_course), 0, 100, principal, announcements, EnrollmentRepository(db),
        ))
        opened = _run(get_announcements(
            str(allowed_course), 0, 100, principal, announcements, EnrollmentRepository(db),
        ))
        system = _run(get_announcements(
            None, 0, 100, principal, announcements, EnrollmentRepository(db),
        ))
        self.assertEqual(denied.items, [])
        self.assertEqual(opened.items[0].title, "Room")
        self.assertIsNone(system.items[0].course_id)
        self.assertEqual(announcements.calls, [str(allowed_course), None])

        class _Marks:
            def __init__(self, record):
                self.record = record
                self.reasons = []

            async def get_attendance(self, attendance_id):
                return self.record

            async def submit_absence_reason(self, attendance_id, reason):
                self.reasons.append(reason)
                return SimpleNamespace(**{**self.record.__dict__, "absence_reason": reason})

        blocked_mark = SimpleNamespace(
            id="mark-1",
            student_id=str(student_id),
            course_id=str(other_course),
            enrollment_id=str(cancelled["_id"]),
            date=NOW,
            status="absent",
            marked_by=str(actor_id),
            notes=None,
            absence_reason=None,
            absence_reason_submitted_at=None,
            is_excused=False,
            created_at=NOW,
            updated_at=NOW,
        )
        marks = _Marks(blocked_mark)
        with self.assertRaises(NotFoundError):
            _run(submit_absence_reason(
                "mark-1",
                SimpleNamespace(absence_reason="I was ill"),
                principal,
                marks,
                EnrollmentRepository(db),
            ))
        self.assertEqual(marks.reasons, [])


if __name__ == "__main__":
    unittest.main()
