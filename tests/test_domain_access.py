"""Student results stay on the authenticated student, and drafts stay off ordinary accounts."""

from __future__ import annotations

import unittest
from datetime import timedelta
from types import SimpleNamespace

from bson import ObjectId

from pydantic import ValidationError

from app.core.auth import get_current_user
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.admin import admin_update_course
from app.routes.courses import get_course, get_courses_by_instructor, list_courses, update_course
from app.routes.lms import get_all_my_results, get_my_results
from app.routes.public import verify_enrollment_card
from app.routes.search import search
from app.schemas.course import CourseUpdate
from app.services.course_service import CourseService
from app.utils.exceptions import ForbiddenError, NotFoundError, UnauthorizedError

try:
    from tests.test_pagination import NOW, _Database, _run
except ImportError:
    from test_pagination import NOW, _Database, _run


def _account(user_id: ObjectId, role: str) -> User:
    return User(
        id=str(user_id),
        email=f"{role}@example.com",
        full_name=role,
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=NOW,
    )


def _course(course_id: ObjectId, instructor_id: ObjectId, title: str, *, published: bool) -> dict:
    return {
        "_id": course_id,
        "title": title,
        "description": f"{title} description",
        "instructor_id": instructor_id,
        "duration_hours": 4,
        "price": 0,
        "is_published": published,
        "created_at": NOW,
        "updated_at": NOW,
    }


class ResultOwnershipTests(unittest.TestCase):
    def test_all_results_and_course_results_stay_on_the_authenticated_student(self) -> None:
        student_id, other_id, course_id, actor_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        enrollment_id = ObjectId()
        db = _Database()
        db.add("students", [{
            "_id": student_id,
            "user_id": ObjectId(),
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("enrollments", [{
            "_id": enrollment_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_date": NOW,
            "status": "active",
            "payment_status": "paid",
            "verified_by_admin": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("results", [
            {
                "_id": ObjectId(),
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_id": enrollment_id,
                "assessment_name": "Mine",
                "assessment_type": "quiz",
                "marks_obtained": 80,
                "total_marks": 100,
                "issued_by": actor_id,
                "issued_date": NOW,
            },
            {
                "_id": ObjectId(),
                "student_id": other_id,
                "course_id": course_id,
                "enrollment_id": ObjectId(),
                "assessment_name": "Theirs",
                "assessment_type": "quiz",
                "marks_obtained": 100,
                "total_marks": 100,
                "issued_by": actor_id,
                "issued_date": NOW + timedelta(days=1),
            },
        ])
        principal = (SimpleNamespace(id=str(student_id)), None)
        history = _run(get_all_my_results(0, 100, principal, ResultRepository(db)))
        course_page = _run(get_my_results(
            str(course_id),
            0,
            100,
            principal,
            ResultRepository(db),
            EnrollmentRepository(db),
        ))
        self.assertEqual([item.assessment_name for item in history.items], ["Mine"])
        self.assertEqual([item.student_id for item in history.items], [str(student_id)])
        self.assertEqual([item.assessment_name for item in course_page.items], ["Mine"])
        self.assertNotIn("Theirs", [item.assessment_name for item in history.items + course_page.items])


class UnpublishedCourseAccessTests(unittest.TestCase):
    def _world(self):
        owner_user, other_user, manager_user = ObjectId(), ObjectId(), ObjectId()
        instructor_id, other_instructor = ObjectId(), ObjectId()
        published_id, draft_id, other_draft = ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("instructors", [{
            "_id": instructor_id,
            "user_id": owner_user,
            "bio": "Speech",
            "specialization": "Speech",
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("courses", [
            _course(published_id, instructor_id, "Published Speech", published=True),
            _course(draft_id, instructor_id, "Draft Speech", published=False),
            _course(other_draft, other_instructor, "Other Draft", published=False),
        ])
        return db, {
            "owner": _account(owner_user, "user"),
            "other": _account(other_user, "user"),
            "manager": _account(manager_user, "academic_manager"),
            "instructor_id": str(instructor_id),
            "published_id": str(published_id),
            "draft_id": str(draft_id),
            "other_draft": str(other_draft),
        }

    def test_ordinary_user_cannot_read_drafts_by_instructor_id_or_course_id(self) -> None:
        db, ids = self._world()
        service = CourseService(CourseRepository(db))
        instructors = InstructorRepository(db)
        listed = _run(get_courses_by_instructor(
            ids["instructor_id"], 0, 100, service, ids["other"], instructors,
        ))
        catalog = _run(list_courses(0, 100, False, service, ids["other"]))
        self.assertEqual([item.title for item in listed.items], ["Published Speech"])
        self.assertEqual([item.title for item in catalog.items], ["Published Speech"])
        with self.assertRaises(NotFoundError):
            _run(get_course(ids["draft_id"], service, ids["other"], instructors))
        visible = _run(get_course(ids["published_id"], service, ids["other"], instructors))
        self.assertEqual(visible.title, "Published Speech")

        found = _run(search(
            "Speech",
            "course",
            20,
            CourseRepository(db),
            StudentRepository(db),
            UserRepository(db),
            ids["other"],
        ))
        self.assertEqual([item.title for item in found.results], ["Published Speech"])

    def test_owner_and_management_can_still_see_their_drafts(self) -> None:
        db, ids = self._world()
        service = CourseService(CourseRepository(db))
        instructors = InstructorRepository(db)
        owned = _run(get_courses_by_instructor(
            ids["instructor_id"], 0, 100, service, ids["owner"], instructors,
        ))
        managed = _run(list_courses(0, 100, False, service, ids["manager"]))
        own_draft = _run(get_course(ids["draft_id"], service, ids["owner"], instructors))
        self.assertEqual(
            sorted(item.title for item in owned.items),
            ["Draft Speech", "Published Speech"],
        )
        self.assertEqual(len(managed.items), 3)
        self.assertEqual(own_draft.title, "Draft Speech")
        with self.assertRaises(NotFoundError):
            _run(get_course(ids["other_draft"], service, ids["owner"], instructors))

    def test_ordinary_user_cannot_update_a_course_by_supplying_an_instructor(self) -> None:
        db, ids = self._world()
        service = CourseService(CourseRepository(db))
        with self.assertRaises(ForbiddenError):
            _run(update_course(
                ids["draft_id"],
                CourseUpdate(title="Taken over"),
                service,
                InstructorRepository(db),
                ids["other"],
            ))
        stored = db["courses"].documents
        self.assertIn("Draft Speech", [item["title"] for item in stored])


class CourseUpdateAuthorizationTests(unittest.TestCase):
    def _world(self):
        owner_user, other_user = ObjectId(), ObjectId()
        instructor_id, other_instructor = ObjectId(), ObjectId()
        course_id = ObjectId()
        db = _Database()
        db.add("instructors", [
            {
                "_id": instructor_id,
                "user_id": owner_user,
                "bio": "Speech",
                "specialization": "Speech",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "_id": other_instructor,
                "user_id": other_user,
                "bio": "Other",
                "specialization": "Other",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ])
        db.add("courses", [_course(course_id, instructor_id, "Speech Lab", published=False)])
        return db, {
            "owner": _account(owner_user, "user"),
            "other": _account(other_user, "user"),
            "manager": _account(ObjectId(), "academic_manager"),
            "course_id": str(course_id),
            "instructor_id": str(instructor_id),
            "other_instructor": str(other_instructor),
        }

    def _update(self, db, ids, user, payload):
        return _run(update_course(
            ids["course_id"],
            payload,
            CourseService(CourseRepository(db)),
            InstructorRepository(db),
            user,
        ))

    def test_assigned_instructor_can_edit_content_and_cannot_reassign_or_publish(self) -> None:
        db, ids = self._world()
        updated = self._update(db, ids, ids["owner"], CourseUpdate(title="Speech Workshop"))
        self.assertEqual(updated.title, "Speech Workshop")
        self.assertEqual(updated.instructor_id, ids["instructor_id"])
        self.assertFalse(updated.is_published)
        with self.assertRaises(ForbiddenError):
            self._update(db, ids, ids["owner"], CourseUpdate(instructor_id=ids["other_instructor"]))
        with self.assertRaises(ForbiddenError):
            self._update(db, ids, ids["owner"], CourseUpdate(is_published=True))
        stored = db["courses"].documents[0]
        self.assertEqual(stored["instructor_id"], ObjectId(ids["instructor_id"]))
        self.assertFalse(stored["is_published"])
        self.assertEqual(stored["title"], "Speech Workshop")

    def test_ordinary_user_cannot_reassign_publish_or_edit(self) -> None:
        db, ids = self._world()
        for payload in (
            CourseUpdate(title="Taken over"),
            CourseUpdate(instructor_id=ids["other_instructor"]),
            CourseUpdate(is_published=True),
        ):
            with self.assertRaises(ForbiddenError):
                self._update(db, ids, ids["other"], payload)
        stored = db["courses"].documents[0]
        self.assertEqual(stored["title"], "Speech Lab")
        self.assertFalse(stored["is_published"])

    def test_management_can_publish_and_reassign_to_a_real_instructor(self) -> None:
        db, ids = self._world()
        published = self._update(db, ids, ids["manager"], CourseUpdate(is_published=True))
        reassigned = _run(admin_update_course(
            ids["course_id"],
            CourseUpdate(instructor_id=ids["other_instructor"]),
            CourseService(CourseRepository(db)),
            InstructorRepository(db),
            ids["manager"],
        ))
        self.assertTrue(published.is_published)
        self.assertEqual(reassigned.instructor_id, ids["other_instructor"])
        archived_id = ObjectId()
        db["instructors"].documents.append({
            "_id": archived_id,
            "user_id": ObjectId(),
            "bio": "Archived",
            "specialization": "Archived",
            "is_active": False,
            "archived_at": NOW,
            "created_at": NOW,
            "updated_at": NOW,
        })
        with self.assertRaises(NotFoundError):
            self._update(db, ids, ids["manager"], CourseUpdate(instructor_id=str(ObjectId())))
        with self.assertRaises(NotFoundError):
            self._update(db, ids, ids["manager"], CourseUpdate(instructor_id="not-an-instructor"))
        with self.assertRaises(NotFoundError):
            self._update(db, ids, ids["manager"], CourseUpdate(instructor_id=str(archived_id)))
        self.assertEqual(db["courses"].documents[0]["instructor_id"], ObjectId(ids["other_instructor"]))

    def test_update_rejects_extra_fields_and_unauthenticated_callers(self) -> None:
        with self.assertRaises(ValidationError):
            CourseUpdate.model_validate({
                "title": "Speech Workshop",
                "role": "admin",
                "instructor_id": str(ObjectId()),
                "is_published": True,
            })
        with self.assertRaises(UnauthorizedError):
            _run(get_current_user(credentials=None, users=object()))


class CardVerificationPrivacyTests(unittest.TestCase):
    def _people(self, db, student_id, user_id, name):
        db["users"].documents.append({
            "_id": user_id,
            "email": f"{name}@example.com",
            "full_name": name,
            "hashed_password": "hashed",
            "is_active": True,
            "role": "user",
            "created_at": NOW,
        })
        db["students"].documents.append({
            "_id": student_id,
            "user_id": user_id,
            "enrollment_date": NOW,
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        })

    def _enrollment(self, student_id, course_id, number, **extra):
        document = {
            "_id": ObjectId(),
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_date": NOW,
            "status": "active",
            "payment_status": "paid",
            "verified_by_admin": True,
            "enrollment_card_number": number,
            "phone_number": "03001234567",
            "address": "12 Private Road",
            "father_guardian_name": "Guardian Name",
            "created_at": NOW,
            "updated_at": NOW,
        }
        document.update(extra)
        return document

    def _verify(self, db, number):
        return _run(verify_enrollment_card(
            number,
            EnrollmentRepository(db),
            StudentRepository(db),
            UserRepository(db),
            CourseRepository(db),
        ))

    def test_invalid_cards_share_one_response_and_hide_private_fields(self) -> None:
        student_id, user_id, course_id = ObjectId(), ObjectId(), ObjectId()
        archived_course = ObjectId()
        db = _Database()
        db.add("users", [])
        db.add("students", [])
        db.add("courses", [
            _course(course_id, ObjectId(), "Public Speech", published=True),
            _course(archived_course, ObjectId(), "Archived Speech", published=True),
        ])
        db["courses"].documents[1]["archived_at"] = NOW
        self._people(db, student_id, user_id, "Ada Khan")
        db.add("enrollments", [
            self._enrollment(student_id, course_id, "ENR-VALID"),
            self._enrollment(student_id, course_id, "ENR-PENDING", verified_by_admin=False, status="pending"),
            self._enrollment(student_id, course_id, "ENR-CANCELLED", status="cancelled"),
            self._enrollment(student_id, course_id, "ENR-REFUNDED", payment_status="refunded"),
            self._enrollment(student_id, archived_course, "ENR-ARCHIVED"),
        ])
        valid = self._verify(db, "ENR-VALID")
        pending = self._verify(db, "ENR-PENDING")
        cancelled = self._verify(db, "ENR-CANCELLED")
        refunded = self._verify(db, "ENR-REFUNDED")
        missing = self._verify(db, "ENR-MISSING")
        archived = self._verify(db, "ENR-ARCHIVED")

        self.assertTrue(valid.valid)
        self.assertEqual(valid.student_name, "Ada Khan")
        self.assertEqual(valid.course_name, "Public Speech")
        self.assertTrue(valid.verified_by_admin)
        self.assertEqual(archived.valid, True)
        self.assertEqual(archived.course_name, "Archived Speech")
        self.assertEqual(archived.student_name, "Ada Khan")

        def exposed(result):
            data = result.model_dump()
            data.pop("card_number")
            return data

        self.assertEqual(exposed(pending), exposed(cancelled))
        self.assertEqual(exposed(pending), exposed(refunded))
        self.assertEqual(exposed(pending), exposed(missing))
        for result in (pending, cancelled, refunded, missing):
            self.assertFalse(result.valid)
            self.assertFalse(result.verified_by_admin)
            self.assertIsNone(result.student_name)
            self.assertIsNone(result.course_name)
            self.assertIsNone(result.batch)
            self.assertIsNone(result.enrollment_date)
            self.assertEqual(result.message, "Card not found or invalid.")
            dumped = str(result.model_dump())
            self.assertNotIn("Ada Khan", dumped)
            self.assertNotIn("03001234567", dumped)
            self.assertNotIn("12 Private Road", dumped)
            self.assertNotIn("Guardian Name", dumped)
            self.assertNotIn("Public Speech", dumped)
