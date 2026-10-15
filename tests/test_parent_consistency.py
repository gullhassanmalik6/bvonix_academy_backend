"""Archived parents stay out of active lists. Enrollment and corrections keep their own lifecycles."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from bson import ObjectId

from app.models.user import User
from app.repositories.attendance_correction_repository import AttendanceCorrectionRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.forum_repository import ForumPostRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.admin import admin_verify_enrollment
from app.routes.lms import enroll_in_course, get_student_dashboard
from app.routes.search import search
from app.schemas.course_material import CourseMaterialUpdate
from app.schemas.enrollment import EnrollmentCreate
from app.services.attendance_correction_service import AttendanceCorrectionService
from app.services.course_material_service import CourseMaterialService
from app.services.course_service import CourseService
from app.services.forum_service import ForumService
from app.utils.exceptions import ConflictError, NotFoundError
try:
    from test_content_archive import NOW, _Audit, _Database, _course, _run, _user
except ImportError:
    from tests.test_content_archive import NOW, _Audit, _Database, _course, _run, _user


def _material(material_id: ObjectId, course_id: ObjectId, actor_id: ObjectId, title: str) -> dict:
    return {
        "_id": material_id,
        "course_id": course_id,
        "title": title,
        "material_type": "document",
        "is_published": True,
        "created_by": actor_id,
        "created_at": NOW,
        "updated_at": NOW,
    }


class ArchivedParentListTests(unittest.TestCase):
    def test_admin_pages_hide_children_and_keep_the_count_at_zero(self) -> None:
        archived_course, live_course, actor_id = ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [
            _course(archived_course, actor_id, title="Closed"),
            _course(live_course, actor_id, title="Open"),
        ])
        db.add("course_materials", [
            _material(ObjectId(), archived_course, actor_id, "Hidden lesson"),
            _material(ObjectId(), archived_course, actor_id, "Hidden notes"),
            _material(ObjectId(), live_course, actor_id, "Visible lesson"),
        ])
        courses = CourseRepository(db)
        service = CourseMaterialService(CourseMaterialRepository(db), courses=courses, audit=_Audit())
        _run(CourseService(courses, audit=_Audit()).delete_course(
            str(archived_course), archived_by="admin-1", actor_role="admin",
        ))

        hidden, hidden_total = _run(service.list_course_materials(str(archived_course), skip=0, limit=10))
        visible, visible_total = _run(service.list_course_materials(str(live_course), skip=0, limit=10))
        self.assertEqual(hidden, [])
        self.assertEqual(hidden_total, 0)
        self.assertEqual(visible_total, 1)
        self.assertEqual(visible[0].title, "Visible lesson")
        self.assertEqual(len(db["course_materials"].documents), 3)
        self.assertEqual(db["course_materials"].delete_calls, 0)

        with self.assertRaises(NotFoundError):
            _run(service.update_material(str(db["course_materials"].documents[0]["_id"]), CourseMaterialUpdate(title="Edited")))
        self.assertEqual(db["course_materials"].documents[0]["title"], "Hidden lesson")

        found = _run(search("Closed", "course", 20, courses, StudentRepository(db), UserRepository(db), _user(actor_id)))
        self.assertEqual(found.results, [])
        open_hits = _run(search("Open", "course", 20, courses, StudentRepository(db), UserRepository(db), _user(actor_id)))
        self.assertEqual([item.title for item in open_hits.results], ["Open"])

    def test_legacy_course_children_stay_listed(self) -> None:
        course_id, actor_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id, actor_id, title="Legacy", include_archived_field=False)])
        db.add("course_materials", [_material(ObjectId(), course_id, actor_id, "Old lesson")])
        service = CourseMaterialService(
            CourseMaterialRepository(db),
            courses=CourseRepository(db),
            audit=_Audit(),
        )
        rows, total = _run(service.list_course_materials(str(course_id)))
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].title, "Old lesson")

    def test_forum_detail_hides_an_archived_parent_and_delete_still_archives(self) -> None:
        course_id, author_id, post_id = ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id, author_id)])
        db.add("forum_posts", [{
            "_id": post_id,
            "course_id": course_id,
            "author_id": author_id,
            "content": "Question",
            "created_at": NOW,
            "updated_at": NOW,
        }])
        courses = CourseRepository(db)
        forum = ForumService(ForumPostRepository(db), courses=courses)
        _run(CourseService(courses, audit=_Audit()).delete_course(
            str(course_id), archived_by="admin-1", actor_role="admin",
        ))
        self.assertEqual(_run(forum.get_course_posts(str(course_id))), [])
        with self.assertRaises(NotFoundError):
            _run(forum.get_post(str(post_id), operational=True))
        _run(forum.delete_post(str(post_id), archived_by="admin-1"))
        self.assertEqual(db["forum_posts"].delete_calls, 0)
        self.assertIsNotNone(db["forum_posts"].documents[0].get("archived_at"))


class EnrollmentLifecycleTests(unittest.TestCase):
    def _people(self) -> tuple[_Database, ObjectId, ObjectId, ObjectId, ObjectId]:
        course_id, user_id, student_id, enrollment_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id, user_id, title="Speech")])
        db.add("users", [{
            "_id": user_id,
            "email": "ada@example.com",
            "hashed_password": "hashed",
            "full_name": "Ada",
            "is_active": True,
            "role": "user",
            "created_at": NOW,
        }])
        db.add("students", [{
            "_id": student_id,
            "user_id": user_id,
            "enrollment_date": NOW,
            "enrolled_courses": [course_id],
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("enrollments", [{
            "_id": enrollment_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_date": NOW,
            "status": "cancelled",
            "payment_status": "paid",
            "verified_by_admin": True,
            "payment_receipt_url": "/uploads/receipt.pdf",
            "created_at": NOW,
            "updated_at": NOW,
        }])
        return db, course_id, user_id, student_id, enrollment_id

    def test_cancelled_enrollment_is_history_and_not_current_access(self) -> None:
        db, course_id, user_id, student_id, enrollment_id = self._people()
        enrollments = EnrollmentRepository(db)
        self.assertFalse(_run(enrollments.has_verified_enrollment(str(student_id))))
        self.assertEqual(_run(enrollments.get_verified_by_student(str(student_id))), [])
        stored = _run(enrollments.get_by_id(str(enrollment_id)))
        self.assertEqual(stored.status, "cancelled")
        page, total = _run(enrollments.list_page())
        self.assertEqual(total, 1)
        self.assertEqual(page[0].id, str(enrollment_id))
        self.assertFalse(_run(enrollments.delete(str(enrollment_id))))
        self.assertEqual(len(db["enrollments"].documents), 1)
        self.assertEqual(db["enrollments"].delete_calls, 0)

        dashboard = _run(get_student_dashboard(
            _user(user_id),
            enrollments,
            StudentRepository(db),
            CourseRepository(db),
            InstructorRepository(db),
            UserRepository(db),
            CourseMaterialService(CourseMaterialRepository(db)),
        ))
        self.assertEqual(dashboard["enrollments"], [])

        with self.assertRaises(ConflictError):
            _run(enroll_in_course(
                str(course_id),
                EnrollmentCreate(class_type="online"),
                _user(user_id),
                enrollments,
                StudentRepository(db),
                CourseRepository(db),
            ))
        self.assertEqual(len(db["enrollments"].documents), 1)

    def test_completed_enrollment_keeps_history_without_a_current_dashboard_card(self) -> None:
        db, _course_id, user_id, student_id, enrollment_id = self._people()
        db["enrollments"].documents[0]["status"] = "completed"
        enrollments = EnrollmentRepository(db)
        self.assertTrue(_run(enrollments.has_verified_enrollment(str(student_id))))
        verified = _run(enrollments.get_verified_by_student(str(student_id)))
        self.assertEqual(verified[0].id, str(enrollment_id))
        dashboard = _run(get_student_dashboard(
            _user(user_id),
            enrollments,
            StudentRepository(db),
            CourseRepository(db),
            InstructorRepository(db),
            UserRepository(db),
            CourseMaterialService(CourseMaterialRepository(db)),
        ))
        self.assertEqual(dashboard["enrollments"], [])

    def test_archived_course_cannot_be_verified(self) -> None:
        db, course_id, user_id, _student_id, enrollment_id = self._people()
        db["enrollments"].documents[0]["status"] = "pending"
        db["enrollments"].documents[0]["verified_by_admin"] = False
        _run(CourseService(CourseRepository(db), audit=_Audit()).delete_course(
            str(course_id), archived_by="admin-1", actor_role="admin",
        ))
        admin = User(
            id="admin-1",
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
            is_active=True,
            role="admin",
            created_at=NOW,
        )
        with self.assertRaises(NotFoundError):
            _run(admin_verify_enrollment(
                str(enrollment_id),
                admin,
                EnrollmentRepository(db),
                CourseRepository(db),
                UserRepository(db),
                StudentRepository(db),
                SimpleNamespace(),
                _Audit(),
            ))
        self.assertFalse(db["enrollments"].documents[0]["verified_by_admin"])
        self.assertEqual(db["enrollments"].documents[0]["status"], "pending")


class AttendanceCorrectionRetentionTests(unittest.TestCase):
    def test_corrections_cannot_be_deleted_or_purged(self) -> None:
        correction_id, course_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("attendance_corrections", [{
            "_id": correction_id,
            "attendance_id": ObjectId(),
            "student_id": ObjectId(),
            "course_id": course_id,
            "enrollment_id": ObjectId(),
            "requester_id": ObjectId(),
            "reason": "I was present for the full class",
            "previous_status": "absent",
            "requested_status": "present",
            "status": "rejected",
            "requested_at": NOW,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        repo = AttendanceCorrectionRepository(db)
        self.assertFalse(_run(repo.delete(str(correction_id))))
        self.assertFalse(_run(repo.purge_document(str(correction_id))))
        self.assertEqual(db["attendance_corrections"].delete_calls, 0)
        self.assertEqual(_run(repo.get_by_id(str(correction_id))).status, "rejected")
        rows, total = _run(repo.list_page())
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].status, "rejected")

    def test_new_correction_is_refused_for_an_archived_course(self) -> None:
        class _Marks:
            async def get_attendance(self, attendance_id: str):
                del attendance_id
                try:
                    from test_attendance_correction import _attendance
                except ImportError:
                    from tests.test_attendance_correction import _attendance
                return _attendance()

        class _Courses:
            async def get_by_id(self, course_id: str):
                del course_id
                return None

        service = AttendanceCorrectionService(_Marks(), _Marks(), courses=_Courses())
        with self.assertRaises(NotFoundError):
            _run(service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            ))


if __name__ == "__main__":
    unittest.main()
