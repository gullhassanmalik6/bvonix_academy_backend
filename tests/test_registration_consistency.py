"""The student course list follows enrollment rows and is not an independent registration."""

from __future__ import annotations

import inspect
import unittest

from bson import ObjectId

from app.core.admin import get_management_user
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.student_repository import StudentRepository
from app.routes.students import enroll_in_course, unenroll_from_course, update_student
from app.schemas.student import StudentUpdate
from app.services.enrollment_registration import RegistrationReconcileError
from app.services.registration_consistency import reconcile_registration_lists, registration_consistency_report
from app.services.student_service import StudentService
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError
from scripts.reconcile_enrolled_courses import assert_reconciliation_target, command_exit_code, main as reconcile_main
from scripts.registration_consistency_report import main, refuse_write

try:
    from tests.test_pagination import NOW, _Database, _run
except ImportError:
    from test_pagination import NOW, _Database, _run


PHONE = "03001112233"


def _user(user_id: ObjectId, role: str = "user") -> User:
    return User(
        id=str(user_id),
        email="ada.private@example.com",
        full_name="Ada",
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=NOW,
    )


def _course(course_id: ObjectId) -> dict:
    return {
        "_id": course_id,
        "title": "Speech",
        "description": "Speaking",
        "instructor_id": ObjectId(),
        "duration_hours": 8,
        "price": 100.0,
        "is_published": True,
        "created_at": NOW,
        "updated_at": NOW,
    }


class RegistrationConsistencyTests(unittest.TestCase):
    def _world(self):
        student_id, other_student, user_id = ObjectId(), ObjectId(), ObjectId()
        course_id, stray_course, other_course = ObjectId(), ObjectId(), ObjectId()
        enrollment_id = ObjectId()
        db = _Database()
        db.add("students", [
            {
                "_id": student_id,
                "user_id": user_id,
                "enrollment_date": NOW,
                "enrolled_courses": [stray_course],
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "_id": other_student,
                "user_id": ObjectId(),
                "enrollment_date": NOW,
                "enrolled_courses": [other_course],
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
                "phone_number": PHONE,
            },
        ])
        db.add("courses", [_course(course_id), _course(other_course)])
        db.add("enrollments", [{
            "_id": enrollment_id,
            "student_id": student_id,
            "course_id": course_id,
            "status": "pending",
            "payment_status": "pending",
            "phone_number": PHONE,
        }])
        service = StudentService(StudentRepository(db))
        return db, service, {
            "student_id": student_id,
            "other_student": other_student,
            "user_id": user_id,
            "course_id": course_id,
            "stray_course": stray_course,
            "other_course": other_course,
            "enrollment_id": enrollment_id,
        }

    def test_management_membership_routes_follow_enrollments(self) -> None:
        db, service, ids = self._world()
        enrollments = EnrollmentRepository(db)
        courses = CourseRepository(db)
        dependency = inspect.signature(enroll_in_course).parameters["current_user"].default.dependency
        self.assertIs(dependency, get_management_user)
        self.assertIs(
            inspect.signature(unenroll_from_course).parameters["current_user"].default.dependency,
            get_management_user,
        )
        with self.assertRaises(ForbiddenError):
            _run(get_management_user(_user(ids["user_id"])))
        self.assertEqual(db["students"].documents[0]["enrolled_courses"], [ids["stray_course"]])
        self.assertEqual(len(db["enrollments"].documents), 1)

        with self.assertRaises(NotFoundError):
            _run(service.enroll_in_course(
                str(ids["student_id"]),
                str(ObjectId()),
                enrollments=enrollments,
                courses=courses,
            ))
        self.assertEqual(db["students"].documents[0]["enrolled_courses"], [ids["stray_course"]])

        listed = _run(enroll_in_course(
            str(ids["student_id"]),
            str(ids["course_id"]),
            service,
            enrollments,
            courses,
            _user(ids["user_id"], "academic_manager"),
        ))
        self.assertEqual(listed.enrolled_courses, [str(ids["course_id"])])
        self.assertEqual(len(db["enrollments"].documents), 1)
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")
        again = _run(service.enroll_in_course(
            str(ids["student_id"]),
            str(ids["course_id"]),
            enrollments=enrollments,
            courses=courses,
        ))
        self.assertEqual(again.enrolled_courses, [str(ids["course_id"])])
        self.assertEqual(len(db["enrollments"].documents), 1)

        kept = _run(unenroll_from_course(
            str(ids["student_id"]),
            str(ids["course_id"]),
            service,
            enrollments,
            _user(ids["user_id"], "admin"),
        ))
        self.assertEqual(kept.enrolled_courses, [str(ids["course_id"])])
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")
        self.assertEqual(db["enrollments"].documents[0]["payment_status"], "pending")
        self.assertEqual(db["students"].documents[1]["enrolled_courses"], [ids["other_course"]])

        inactive = _run(update_student(
            str(ids["student_id"]),
            StudentUpdate(is_active=False, enrolled_courses=[str(ids["stray_course"])]),
            service,
            enrollments,
            _user(ids["user_id"], "super_admin"),
        ))
        self.assertFalse(inactive.is_active)
        self.assertEqual(inactive.enrolled_courses, [str(ids["course_id"])])
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")

    def test_list_write_failure_keeps_the_enrollment_and_retry_repairs_the_list(self) -> None:
        db, service, ids = self._world()
        students = service._students
        original = students.set_enrolled_courses
        calls = {"n": 0}

        async def fail_once(student_id: str, course_ids: list[str]):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("list store unavailable")
            return await original(student_id, course_ids)

        students.set_enrolled_courses = fail_once
        with self.assertRaises(RegistrationReconcileError):
            _run(service.enroll_in_course(
                str(ids["student_id"]),
                str(ids["course_id"]),
                enrollments=EnrollmentRepository(db),
                courses=CourseRepository(db),
            ))
        self.assertEqual(db["students"].documents[0]["enrolled_courses"], [ids["stray_course"]])
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")
        self.assertEqual(len(db["enrollments"].documents), 1)
        repaired = _run(service.unenroll_from_course(
            str(ids["student_id"]),
            str(ids["course_id"]),
            enrollments=EnrollmentRepository(db),
        ))
        self.assertEqual(repaired.enrolled_courses, [str(ids["course_id"])])
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")
        self.assertEqual(calls["n"], 2)

    def test_profile_flag_update_does_not_invent_a_course_list(self) -> None:
        db, service, ids = self._world()
        updated = _run(service.update_student(
            str(ids["student_id"]),
            StudentUpdate(is_active=False),
        ))
        self.assertFalse(updated.is_active)
        self.assertEqual(updated.enrolled_courses, [str(ids["stray_course"])])
        with self.assertRaises(ConflictError):
            _run(service.update_student(
                str(ids["student_id"]),
                StudentUpdate(enrolled_courses=[str(ids["course_id"])]),
            ))
        self.assertEqual(db["students"].documents[0]["enrolled_courses"], [ids["stray_course"]])

    def test_report_classifies_drift_without_changing_records(self) -> None:
        student_id, missing_student = ObjectId(), ObjectId()
        course_id, listed_only, duplicate_course = ObjectId(), ObjectId(), ObjectId()
        present_id, missing_id, cancelled_id = ObjectId(), ObjectId(), ObjectId()
        first_duplicate, second_duplicate = ObjectId(), ObjectId()
        db = _Database()
        db.add("students", [
            {
                "_id": student_id,
                "user_id": ObjectId(),
                "enrolled_courses": [course_id, listed_only],
                "archived_at": NOW,
                "phone_number": PHONE,
            },
            {
                "_id": ObjectId(),
                "user_id": ObjectId(),
                "enrolled_courses": ["not-a-course"],
                "address": "House 4",
            },
        ])
        db.add("enrollments", [
            {"_id": present_id, "student_id": student_id, "course_id": course_id, "status": "active", "phone_number": PHONE},
            {"_id": missing_id, "student_id": student_id, "course_id": duplicate_course, "status": "pending"},
            {"_id": cancelled_id, "student_id": student_id, "course_id": listed_only, "status": "cancelled"},
            {"_id": first_duplicate, "student_id": missing_student, "course_id": course_id, "status": "active"},
            {"_id": second_duplicate, "student_id": missing_student, "course_id": course_id, "status": "completed"},
            {"_id": ObjectId(), "student_id": "not-a-student", "course_id": "not-a-course", "status": "pending", "father_guardian_name": "Private Guardian"},
        ])
        before_students = [dict(item) for item in db["students"].documents]
        before_enrollments = [dict(item) for item in db["enrollments"].documents]
        report = _run(registration_consistency_report(db))
        self.assertEqual(db["students"].documents, before_students)
        self.assertEqual(db["enrollments"].documents, before_enrollments)
        counts = report["counts"]
        self.assertEqual(counts["students"], 2)
        self.assertEqual(counts["enrollments"], 6)
        self.assertEqual(counts["list_entry_without_registration"], 1)
        self.assertEqual(report["ids"]["list_entry_without_registration"], [str(student_id)])
        self.assertEqual(counts["registration_missing_from_list"], 3)
        self.assertIn(str(missing_id), report["ids"]["registration_missing_from_list"])
        self.assertIn(str(first_duplicate), report["ids"]["registration_missing_from_list"])
        self.assertEqual(counts["cancelled_registration_still_listed"], 1)
        self.assertEqual(report["ids"]["cancelled_registration_still_listed"], [str(cancelled_id)])
        self.assertEqual(counts["duplicate_registration"], 1)
        self.assertEqual(counts["invalid_relationship_id"], 2)
        rendered = str(report)
        self.assertNotIn(PHONE, rendered)
        self.assertNotIn("not-a-course", rendered)
        self.assertNotIn("Private Guardian", rendered)
        self.assertNotIn("House 4", rendered)

    def test_report_script_does_not_select_or_write_a_database(self) -> None:
        self.assertEqual(main([]), 2)
        with self.assertRaises(SystemExit) as raised:
            refuse_write("bvonix_academy")
        self.assertIn("read-only", str(raised.exception))
        with self.assertRaises(SystemExit):
            main(["--write", "--uri", "mongodb://localhost:27017", "--database", "bvonix_test_registration"])

    def test_repository_has_no_independent_course_list_mutation(self) -> None:
        source = inspect.getsource(StudentRepository)
        self.assertNotIn("$addToSet", source)
        self.assertNotIn("$pull", source)
        self.assertFalse(hasattr(StudentRepository, "enroll_in_course"))
        self.assertFalse(hasattr(StudentRepository, "unenroll_from_course"))
        self.assertIn("def set_enrolled_courses", source)

    def test_reconciliation_rebuilds_lists_without_touching_enrollments(self) -> None:
        student_id, archived_student, missing_student = ObjectId(), ObjectId(), ObjectId()
        active_course, completed_course, pending_course = ObjectId(), ObjectId(), ObjectId()
        cancelled_course, legacy_course, duplicate_course = ObjectId(), ObjectId(), ObjectId()
        active_id, completed_id, pending_id = ObjectId(), ObjectId(), ObjectId()
        cancelled_id, legacy_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("students", [
            {
                "_id": student_id,
                "user_id": ObjectId(),
                "enrolled_courses": [cancelled_course, cancelled_course, active_course],
                "is_active": True,
                "phone_number": PHONE,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "_id": archived_student,
                "user_id": ObjectId(),
                "enrolled_courses": [],
                "is_active": False,
                "archived_at": NOW,
                "archived_by": str(ObjectId()),
                "address": "House 4",
            },
        ])
        db.add("enrollments", [
            {"_id": active_id, "student_id": student_id, "course_id": active_course, "status": "active", "verified_by_admin": True, "payment_status": "paid"},
            {"_id": completed_id, "student_id": student_id, "course_id": completed_course, "status": "completed", "verified_by_admin": True, "payment_status": "paid"},
            {"_id": pending_id, "student_id": student_id, "course_id": pending_course, "status": "pending", "verified_by_admin": False, "payment_status": "pending"},
            {"_id": cancelled_id, "student_id": student_id, "course_id": cancelled_course, "status": "cancelled", "verified_by_admin": True, "payment_status": "paid"},
            {"_id": legacy_id, "student_id": archived_student, "course_id": legacy_course, "verified_by_admin": False, "payment_status": "pending"},
            {"_id": ObjectId(), "student_id": student_id, "course_id": duplicate_course, "status": "active", "verified_by_admin": False},
            {"_id": ObjectId(), "student_id": student_id, "course_id": duplicate_course, "status": "pending", "verified_by_admin": False},
            {"_id": ObjectId(), "student_id": missing_student, "course_id": active_course, "status": "active"},
            {"_id": ObjectId(), "student_id": "not-a-student", "course_id": "not-a-course", "status": "pending", "phone_number": PHONE},
        ])
        db.add("payments", [{"_id": ObjectId(), "enrollment_id": active_id, "payment_status": "pending", "amount": 10}])
        before_enrollments = [dict(item) for item in db["enrollments"].documents]
        before_payments = [dict(item) for item in db["payments"].documents]
        preview = _run(reconcile_registration_lists(db, write=False))
        self.assertFalse(preview["write"])
        self.assertTrue(preview["completed"])
        self.assertEqual(preview["counts"]["would_update"], 2)
        self.assertEqual(preview["counts"]["updated"], 0)
        self.assertEqual(preview["counts"]["archived_students_would_update"], 1)
        self.assertEqual(preview["counts"]["duplicate_registration"], 1)
        self.assertEqual(preview["counts"]["enrollment_without_student"], 1)
        self.assertEqual(preview["counts"]["invalid_relationship_id"], 1)
        self.assertEqual(db["enrollments"].documents, before_enrollments)
        self.assertEqual(db["students"].documents[0]["enrolled_courses"][0], cancelled_course)

        result = _run(reconcile_registration_lists(db, write=True))
        self.assertTrue(result["write"])
        self.assertTrue(result["completed"])
        self.assertEqual(result["counts"]["updated"], 2)
        self.assertEqual(result["counts"]["archived_students_updated"], 1)
        self.assertEqual(result["counts"]["failed"], 0)
        listed = [str(course_id) for course_id in db["students"].documents[0]["enrolled_courses"]]
        self.assertEqual(listed, sorted({str(active_course), str(completed_course), str(pending_course), str(duplicate_course)}))
        self.assertNotIn(str(cancelled_course), listed)
        self.assertEqual(db["students"].documents[0]["is_active"], True)
        self.assertEqual(db["students"].documents[0]["phone_number"], PHONE)
        archived_list = [str(course_id) for course_id in db["students"].documents[1]["enrolled_courses"]]
        self.assertEqual(archived_list, [str(legacy_course)])
        self.assertEqual(db["students"].documents[1]["archived_at"], NOW)
        self.assertEqual(db["students"].documents[1]["is_active"], False)
        self.assertEqual(db["students"].documents[1]["address"], "House 4")
        self.assertEqual(db["enrollments"].documents, before_enrollments)
        self.assertEqual(db["payments"].documents, before_payments)
        self.assertNotIn("courses", db._collections)
        enrollments = EnrollmentRepository(db)
        self.assertIsNotNone(_run(enrollments.get_access_enrollment(str(student_id), str(active_course))))
        self.assertIsNotNone(_run(enrollments.get_access_enrollment(str(student_id), str(completed_course))))
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(student_id), str(pending_course))))
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(student_id), str(cancelled_course))))
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(archived_student), str(legacy_course))))
        again = _run(reconcile_registration_lists(db, write=True))
        self.assertEqual(again["counts"]["updated"], 0)
        self.assertEqual(again["counts"]["unchanged"], 2)
        self.assertTrue(again["completed"])
        rendered = str(result)
        self.assertNotIn(PHONE, rendered)
        self.assertNotIn("House 4", rendered)
        self.assertNotIn("not-a-course", rendered)

    def test_reconciliation_reports_a_partial_failure_and_retry_finishes_it(self) -> None:
        first_student, second_student = ObjectId(), ObjectId()
        first_course, second_course = ObjectId(), ObjectId()
        db = _Database()
        db.add("students", [
            {"_id": first_student, "user_id": ObjectId(), "enrolled_courses": [], "is_active": True},
            {"_id": second_student, "user_id": ObjectId(), "enrolled_courses": [ObjectId()], "is_active": True},
        ])
        db.add("enrollments", [
            {"_id": ObjectId(), "student_id": first_student, "course_id": first_course, "status": "active", "verified_by_admin": True},
            {"_id": ObjectId(), "student_id": second_student, "course_id": second_course, "status": "completed", "verified_by_admin": True},
        ])
        original = StudentRepository.set_enrolled_courses

        async def fail_second(self, student_id: str, course_ids: list[str], *, include_archived: bool = False):
            if student_id == str(second_student):
                raise RuntimeError("list store unavailable")
            return await original(self, student_id, course_ids, include_archived=include_archived)

        StudentRepository.set_enrolled_courses = fail_second
        try:
            partial = _run(reconcile_registration_lists(db, write=True))
        finally:
            StudentRepository.set_enrolled_courses = original
        self.assertFalse(partial["completed"])
        self.assertEqual(partial["counts"]["updated"], 1)
        self.assertEqual(partial["counts"]["failed"], 1)
        self.assertEqual(partial["failed_student_ids"], [str(second_student)])
        self.assertEqual(command_exit_code(partial), 1)
        self.assertEqual([str(course_id) for course_id in db["students"].documents[0]["enrolled_courses"]], [str(first_course)])
        self.assertEqual(db["enrollments"].documents[1]["status"], "completed")
        self.assertEqual(db["enrollments"].documents[1]["verified_by_admin"], True)
        finished = _run(reconcile_registration_lists(db, write=True))
        self.assertTrue(finished["completed"])
        self.assertEqual(finished["counts"]["updated"], 1)
        self.assertEqual(finished["counts"]["failed"], 0)
        self.assertEqual([str(course_id) for course_id in db["students"].documents[1]["enrolled_courses"]], [str(second_course)])
        self.assertEqual(command_exit_code(finished), 0)

    def test_reconciliation_command_refuses_an_implicit_or_production_database(self) -> None:
        self.assertEqual(reconcile_main([]), 2)
        self.assertEqual(command_exit_code({"completed": False}), 1)
        with self.assertRaises(SystemExit) as raised:
            assert_reconciliation_target("bvonix_academy", "development")
        self.assertIn("Refusing", str(raised.exception))
        with self.assertRaises(SystemExit):
            assert_reconciliation_target("bvonix_test_prod", "development")
        with self.assertRaises(SystemExit):
            assert_reconciliation_target("bvonix_test_registration", "production")
        with self.assertRaises(SystemExit):
            assert_reconciliation_target("staging", "development")
        assert_reconciliation_target("bvonix_test_registration", "development")
