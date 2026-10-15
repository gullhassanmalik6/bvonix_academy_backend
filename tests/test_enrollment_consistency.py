"""Enrollment creation and cancellation stay recoverable when a later write fails."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.admin import get_management_user
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.student_repository import StudentRepository
from app.routes.admin import admin_cancel_enrollment
from app.routes.lms import enroll_in_course
from app.schemas.enrollment import EnrollmentCreate
from app.services.enrollment_registration import EnrollmentRegistration, RegistrationReconcileError
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError

try:
    from tests.test_pagination import NOW, _Database, _run
except ImportError:
    from test_pagination import NOW, _Database, _run


PHONE = "03007654321"


def _user(user_id: ObjectId, role: str = "user") -> User:
    return User(
        id=str(user_id),
        email=f"{role}@example.com",
        full_name=role,
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=NOW,
    )


def _course(course_id: ObjectId, *, archived: bool = False) -> dict:
    document = {
        "_id": course_id,
        "title": "Speech",
        "description": "Speech description",
        "instructor_id": ObjectId(),
        "duration_hours": 4,
        "price": 0,
        "is_published": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    if archived:
        document["archived_at"] = NOW
    return document


def _student(student_id: ObjectId, user_id: ObjectId, courses: list) -> dict:
    return {
        "_id": student_id,
        "user_id": user_id,
        "enrollment_date": NOW,
        "enrolled_courses": courses,
        "is_active": True,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _enrollment(enrollment_id: ObjectId, student_id: ObjectId, course_id: ObjectId, status: str) -> dict:
    return {
        "_id": enrollment_id,
        "student_id": student_id,
        "course_id": course_id,
        "enrollment_date": NOW,
        "status": status,
        "payment_status": "paid",
        "verified_by_admin": True,
        "class_type": "online",
        "phone_number": PHONE,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _payload() -> EnrollmentCreate:
    return EnrollmentCreate(class_type="online", payment_status="paid", phone_number=PHONE)


class _Audit:
    def __init__(self) -> None:
        self.records: list[str] = []

    async def record(self, **kwargs):
        self.records.append(kwargs["action"])
        return SimpleNamespace(id="audit-1")


class EnrollmentConsistencyTests(unittest.TestCase):
    def _services(self, db: _Database) -> tuple[EnrollmentRepository, StudentRepository, CourseRepository]:
        return EnrollmentRepository(db), StudentRepository(db), CourseRepository(db)

    def _listed(self, db: _Database, student_id: ObjectId) -> list[str]:
        student = next(item for item in db["students"].documents if item["_id"] == student_id)
        return [str(course_id) for course_id in student.get("enrolled_courses", [])]

    def test_creation_and_cancellation_keep_one_enrollment_and_unrelated_courses(self) -> None:
        user_id, student_id = ObjectId(), ObjectId()
        course_id, other_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id), _course(other_id)])
        db.add("students", [_student(student_id, user_id, [other_id])])
        db.add("enrollments", [_enrollment(ObjectId(), student_id, other_id, "active")])
        db.add("payments", [{"_id": ObjectId(), "student_id": student_id, "status": "completed"}])
        enrollments, students, courses = self._services(db)
        created = _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(created.status, "pending")
        self.assertEqual(created.payment_status, "pending")
        self.assertEqual(created.phone_number, PHONE)
        self.assertEqual(len(db["enrollments"].documents), 2)
        self.assertEqual(self._listed(db, student_id), sorted([str(course_id), str(other_id)]))

        audit = _Audit()
        cancelled = _run(admin_cancel_enrollment(
            created.id,
            _user(ObjectId(), "academic_manager"),
            enrollments,
            students,
            audit,
        ))
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(len(db["enrollments"].documents), 2)
        created_row = next(item for item in db["enrollments"].documents if item["course_id"] == course_id)
        self.assertEqual(created_row["payment_status"], "pending")
        self.assertEqual(created_row["status"], "cancelled")
        self.assertEqual(db["payments"].documents[0]["status"], "completed")
        self.assertEqual(self._listed(db, student_id), [str(other_id)])
        self.assertEqual(audit.records, ["enrollment.cancel"])

        repeated = _run(admin_cancel_enrollment(
            created.id,
            _user(ObjectId(), "admin"),
            enrollments,
            students,
            audit,
        ))
        self.assertEqual(repeated.id, created.id)
        self.assertEqual(repeated.status, "cancelled")
        self.assertEqual(self._listed(db, student_id), [str(other_id)])
        self.assertEqual(audit.records, ["enrollment.cancel"])
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(student_id), str(course_id))))

    def test_failure_before_insert_writes_nothing_and_retry_creates_one_enrollment(self) -> None:
        user_id, course_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id, archived=True)])
        db.add("students", [])
        db.add("enrollments", [])
        enrollments, students, courses = self._services(db)
        with self.assertRaises(NotFoundError):
            _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(db["students"].documents, [])
        self.assertEqual(db["enrollments"].documents, [])

        db["courses"].documents[0].pop("archived_at")

        async def fail_insert(document: dict):
            raise RuntimeError("insert failed")

        db["enrollments"].insert_one = fail_insert
        with self.assertRaises(RuntimeError):
            _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(len(db["students"].documents), 1)
        self.assertEqual(db["enrollments"].documents, [])

        async def insert_one(document: dict):
            stored = dict(document)
            stored.setdefault("_id", ObjectId())
            db["enrollments"].documents.append(stored)
            return type("Inserted", (), {"inserted_id": stored["_id"]})()

        db["enrollments"].insert_one = insert_one
        created = _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(created.status, "pending")
        self.assertEqual(len(db["students"].documents), 1)
        self.assertEqual(len(db["enrollments"].documents), 1)
        self.assertEqual(self._listed(db, db["students"].documents[0]["_id"]), [str(course_id)])

    def test_retry_after_a_failed_list_update_repairs_the_same_enrollment(self) -> None:
        user_id, student_id, course_id = ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id)])
        db.add("students", [_student(student_id, user_id, [])])
        db.add("enrollments", [])
        enrollments, students, courses = self._services(db)
        original_update = db["students"].find_one_and_update

        async def fail_list(query, update, return_document=False):
            raise RuntimeError("list write failed")

        db["students"].find_one_and_update = fail_list
        with self.assertLogs("app.services.enrollment_registration", level="WARNING") as captured:
            with self.assertRaises(RegistrationReconcileError) as raised:
                _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertNotIn(PHONE, str(raised.exception.detail))
        self.assertNotIn(PHONE, "\n".join(captured.output))
        self.assertNotIn("ENR-", "\n".join(captured.output))
        self.assertEqual(len(db["enrollments"].documents), 1)
        self.assertEqual(self._listed(db, student_id), [])

        db["students"].find_one_and_update = original_update
        repaired = _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(repaired.id, str(db["enrollments"].documents[0]["_id"]))
        self.assertEqual(len(db["enrollments"].documents), 1)
        self.assertEqual(self._listed(db, student_id), [str(course_id)])

        with self.assertRaises(ConflictError) as conflict:
            _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(conflict.exception.detail, "Already enrolled in this course")
        self.assertEqual(len(db["enrollments"].documents), 1)

    def test_duplicate_key_race_and_cancelled_row_do_not_create_or_reactivate(self) -> None:
        user_id, student_id = ObjectId(), ObjectId()
        course_id, other_id = ObjectId(), ObjectId()
        existing_id = ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id)])
        db.add("students", [_student(student_id, user_id, [other_id])])
        db.add("enrollments", [
            _enrollment(existing_id, student_id, course_id, "pending"),
            _enrollment(ObjectId(), student_id, other_id, "completed"),
        ])
        enrollments, students, courses = self._services(db)

        real_find = db["enrollments"].find_one
        finds = {"count": 0}

        async def miss_once(query: dict):
            finds["count"] += 1
            if finds["count"] == 1:
                return None
            return await real_find(query)

        async def duplicate_insert(document: dict):
            raise DuplicateKeyError("duplicate key")

        db["enrollments"].find_one = miss_once
        db["enrollments"].insert_one = duplicate_insert
        with self.assertLogs("app.services.enrollment_registration", level="WARNING") as captured:
            repaired = _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(repaired.id, str(existing_id))
        self.assertEqual(repaired.status, "pending")
        self.assertEqual(len(db["enrollments"].documents), 2)
        self.assertEqual(self._listed(db, student_id), sorted([str(course_id), str(other_id)]))
        self.assertNotIn(PHONE, "\n".join(captured.output))

        db["enrollments"].documents[0]["status"] = "cancelled"
        with self.assertRaises(ConflictError) as conflict:
            _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(conflict.exception.detail, "This course enrollment is cancelled")
        pending = next(item for item in db["enrollments"].documents if item["_id"] == existing_id)
        self.assertEqual(pending["status"], "cancelled")
        self.assertEqual(len(db["enrollments"].documents), 2)
        self.assertEqual(self._listed(db, student_id), [str(other_id)])

    def test_concurrent_profile_create_keeps_one_student(self) -> None:
        user_id, course_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id)])
        db.add("students", [])
        db.add("enrollments", [])
        enrollments, students, courses = self._services(db)

        async def duplicate_student(document: dict):
            stored = dict(document)
            stored["_id"] = ObjectId()
            db["students"].documents.append(stored)
            raise DuplicateKeyError("duplicate user")

        db["students"].insert_one = duplicate_student
        created = _run(enroll_in_course(str(course_id), _payload(), _user(user_id), enrollments, students, courses))
        self.assertEqual(created.student_id, str(db["students"].documents[0]["_id"]))
        self.assertEqual(len(db["students"].documents), 1)
        self.assertEqual(len(db["enrollments"].documents), 1)

    def test_cancel_retries_after_a_failed_list_update_and_denies_access(self) -> None:
        user_id, student_id = ObjectId(), ObjectId()
        course_id, other_id, enrollment_id = ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id)])
        db.add("students", [_student(student_id, user_id, [course_id, other_id])])
        db.add("enrollments", [
            _enrollment(enrollment_id, student_id, course_id, "active"),
            _enrollment(ObjectId(), student_id, other_id, "completed"),
        ])
        enrollments, students, courses = self._services(db)
        original_update = db["students"].find_one_and_update

        async def fail_list(query, update, return_document=False):
            raise RuntimeError("list write failed")

        db["students"].find_one_and_update = fail_list
        with self.assertRaises(RegistrationReconcileError):
            _run(admin_cancel_enrollment(
                str(enrollment_id),
                _user(ObjectId(), "admin"),
                enrollments,
                students,
                _Audit(),
            ))
        self.assertEqual(db["enrollments"].documents[0]["status"], "cancelled")
        self.assertEqual(self._listed(db, student_id), [str(course_id), str(other_id)])
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(student_id), str(course_id))))

        db["students"].find_one_and_update = original_update
        repaired = _run(admin_cancel_enrollment(
            str(enrollment_id),
            _user(ObjectId(), "admin"),
            enrollments,
            students,
            _Audit(),
        ))
        self.assertEqual(repaired.status, "cancelled")
        self.assertEqual(self._listed(db, student_id), [str(other_id)])
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(student_id), str(course_id))))

    def test_stale_or_missing_list_entries_do_not_grant_access(self) -> None:
        student_id, course_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("students", [_student(student_id, ObjectId(), [course_id])])
        db.add("enrollments", [])
        enrollments = EnrollmentRepository(db)
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(student_id), str(course_id))))
        registration = EnrollmentRegistration(enrollments, StudentRepository(db))
        cleared = _run(registration.reconcile_enrolled_courses(str(student_id)))
        self.assertEqual(cleared.enrolled_courses, [])
        self.assertIsNone(_run(enrollments.get_access_enrollment(str(student_id), str(course_id))))
        with self.assertRaises(NotFoundError):
            _run(registration.reconcile_enrolled_courses(str(ObjectId())))
        self.assertEqual(self._listed(db, student_id), [])

    def test_reconcile_pages_courses_and_keeps_duplicate_rows(self) -> None:
        student_id = ObjectId()
        kept = [ObjectId() for _ in range(101)]
        duplicate_course = kept[0]
        cancelled_course = ObjectId()
        db = _Database()
        db.add("students", [_student(student_id, ObjectId(), [cancelled_course])])
        db.add("enrollments", [
            _enrollment(ObjectId(), student_id, course_id, "active")
            for course_id in kept
        ] + [
            _enrollment(ObjectId(), student_id, duplicate_course, "pending"),
            _enrollment(ObjectId(), student_id, cancelled_course, "cancelled"),
        ])
        enrollments, students, _courses = self._services(db)
        before = len(db["enrollments"].documents)
        updated = _run(EnrollmentRegistration(enrollments, students).reconcile_enrolled_courses(str(student_id)))
        self.assertEqual(before, len(db["enrollments"].documents))
        self.assertEqual(len(updated.enrolled_courses), 101)
        self.assertNotIn(str(cancelled_course), updated.enrolled_courses)
        self.assertIn(str(duplicate_course), updated.enrolled_courses)
        again = _run(EnrollmentRegistration(enrollments, students).reconcile_enrolled_courses(str(student_id)))
        self.assertEqual(set(again.enrolled_courses), set(updated.enrolled_courses))

    def test_ordinary_user_cannot_cancel_and_missing_student_is_explicit(self) -> None:
        student_id, course_id, enrollment_id = ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("students", [])
        db.add("enrollments", [_enrollment(enrollment_id, student_id, course_id, "pending")])
        enrollments, students, _courses = self._services(db)
        with self.assertRaises(ForbiddenError):
            _run(get_management_user(_user(ObjectId(), "user")))
        with self.assertRaises(ForbiddenError):
            _run(EnrollmentRegistration(enrollments, students).cancel(
                str(enrollment_id),
                actor_id=str(ObjectId()),
                actor_role="user",
            ))
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")
        with self.assertRaises(NotFoundError):
            _run(admin_cancel_enrollment(
                str(enrollment_id),
                _user(ObjectId(), "admin"),
                enrollments,
                students,
                _Audit(),
            ))
        self.assertEqual(db["enrollments"].documents[0]["status"], "cancelled")
        self.assertEqual(len(db["enrollments"].documents), 1)
