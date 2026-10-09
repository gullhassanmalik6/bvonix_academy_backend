"""Normal course and learning-content deletion archives. Purge stays explicit."""

from __future__ import annotations

import asyncio
import re
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from bson import ObjectId

from app.models.user import User
from app.repositories.announcement_repository import AnnouncementRepository
from app.repositories.assignment_repository import AssignmentRepository, AssignmentSubmissionRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.calendar_event_repository import CalendarEventRepository
from app.repositories.certificate_repository import CertificateRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.forum_repository import ForumPostRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.lms import enroll_in_course, get_course_materials, get_student_dashboard
from app.routes.public import verify_enrollment_card
from app.routes.search import search
from app.schemas.assignment import AssignmentCreate, AssignmentSubmissionCreate
from app.schemas.course_material import CourseMaterialCreate
from app.schemas.enrollment import EnrollmentCreate
from app.services.announcement_service import AnnouncementService
from app.services.assignment_service import AssignmentService
from app.services.calendar_event_service import CalendarEventService
from app.services.course_material_service import CourseMaterialService
from app.services.course_service import CourseService
from app.services.forum_service import ForumService
from app.services.live_session_service import LiveSessionService
from app.utils.exceptions import ForbiddenError, NotFoundError


def _matches(document: dict, query: dict) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
            continue
        if key == "archived_at" and expected is None:
            if document.get("archived_at") is not None:
                return False
            continue
        if isinstance(expected, dict) and "$regex" in expected:
            flags = re.IGNORECASE if "i" in str(expected.get("$options", "")) else 0
            if re.search(expected["$regex"], str(document.get(key) or ""), flags) is None:
                return False
            continue
        if isinstance(expected, dict) and "$gte" in expected:
            value = document.get(key)
            if value is None or value < expected["$gte"]:
                return False
            continue
        if isinstance(expected, dict) and "$ne" in expected:
            if document.get(key) == expected["$ne"]:
                return False
            continue
        if isinstance(expected, dict) and "$in" in expected:
            if document.get(key) not in expected["$in"]:
                return False
            continue
        if document.get(key) != expected:
            return False
    return True


class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = list(documents)

    def sort(self, *_args, **_kwargs):
        return self

    def skip(self, count: int):
        self.documents = self.documents[count:]
        return self

    def limit(self, count: int):
        self.documents = self.documents[:count]
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        if length is None:
            return list(self.documents)
        return list(self.documents[:length])


class _Collection:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.queries: list[dict] = []
        self.delete_calls = 0

    async def find_one(self, query: dict) -> dict | None:
        self.queries.append(query)
        for document in self.documents:
            if _matches(document, query):
                return document
        return None

    def find(self, query: dict) -> _Cursor:
        self.queries.append(query)
        return _Cursor([document for document in self.documents if _matches(document, query)])

    async def count_documents(self, query: dict) -> int:
        self.queries.append(query)
        return sum(1 for document in self.documents if _matches(document, query))

    async def find_one_and_update(self, query: dict, update: dict, return_document: bool = False) -> dict | None:
        del return_document
        self.queries.append(query)
        for document in self.documents:
            if _matches(document, query):
                document.update(update.get("$set", {}))
                return document
        return None

    async def insert_one(self, document: dict) -> SimpleNamespace:
        stored = dict(document)
        stored.setdefault("_id", ObjectId())
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def delete_one(self, query: dict) -> SimpleNamespace:
        self.delete_calls += 1
        before = len(self.documents)
        self.documents = [document for document in self.documents if not _matches(document, query)]
        return SimpleNamespace(deleted_count=before - len(self.documents))


class _Database:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def add(self, name: str, documents: list[dict]) -> _Collection:
        collection = _Collection(documents)
        self._collections[name] = collection
        return collection

    def __getitem__(self, name: str) -> _Collection:
        if name not in self._collections:
            self._collections[name] = _Collection([])
        return self._collections[name]


def _run(coro):
    return asyncio.run(coro)


NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record(self, **kwargs) -> None:
        self.events.append(kwargs)


def _user(user_id: ObjectId, role: str = "user") -> User:
    return User(
        id=str(user_id),
        email="ada@example.com",
        full_name="Ada",
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=NOW,
    )


def _course(course_id: ObjectId, instructor_id: ObjectId, *, title: str = "Speech", published: bool = True, archived_at=None, include_archived_field: bool = True) -> dict:
    document = {
        "_id": course_id,
        "title": title,
        "description": "Spoken English",
        "instructor_id": instructor_id,
        "duration_hours": 12,
        "price": 0,
        "is_published": published,
        "created_at": NOW,
        "updated_at": NOW,
    }
    if include_archived_field:
        document["archived_at"] = archived_at
    return document


class CourseArchiveTests(unittest.TestCase):
    def _world(self) -> tuple[_Database, ObjectId, ObjectId, ObjectId, ObjectId]:
        course_id, instructor_id, user_id, student_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id, instructor_id, title="Visible Speech")])
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
            "_id": ObjectId(),
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_date": NOW,
            "status": "active",
            "payment_status": "paid",
            "verified_by_admin": True,
            "enrollment_card_number": "CARD-1",
            "created_at": NOW,
            "updated_at": NOW,
        }])
        return db, course_id, instructor_id, user_id, student_id

    def test_normal_delete_archives_and_hides_operational_reads(self) -> None:
        db, course_id, instructor_id, user_id, _student_id = self._world()
        courses = db["courses"]
        repo = CourseRepository(db)
        audit = _Audit()
        service = CourseService(repo, audit=audit)

        with self.assertRaises(ForbiddenError):
            _run(service.delete_course(str(course_id), archived_by="student", actor_role="user"))
        self.assertIsNone(courses.documents[0]["archived_at"])
        self.assertEqual(courses.delete_calls, 0)

        _run(service.delete_course(str(course_id), archived_by="mgr-1", actor_role="academic_manager"))
        stored = courses.documents[0]
        self.assertIsNotNone(stored["archived_at"])
        self.assertEqual(stored["archived_by"], "mgr-1")
        self.assertEqual(courses.delete_calls, 0)
        self.assertEqual(audit.events[0]["action"], "course.delete")
        self.assertEqual(audit.events[0]["entity_id"], str(course_id))

        self.assertIsNone(_run(repo.get_by_id(str(course_id))))
        self.assertEqual(_run(repo.get_published()), [])
        listed, total = _run(service.list_courses())
        self.assertEqual(listed, [])
        self.assertEqual(total, 0)
        self.assertEqual(_run(repo.get_by_instructor(str(instructor_id))), [])
        found = _run(search("Visible", "course", 20, repo, StudentRepository(db), UserRepository(db), _user(user_id)))
        self.assertEqual(found.results, [])
        self.assertIn({"_id": course_id, "archived_at": None}, courses.queries)

        with self.assertRaises(NotFoundError):
            _run(service.delete_course(str(course_id), archived_by="mgr-1", actor_role="admin"))
        self.assertEqual(len(courses.documents), 1)
        self.assertEqual(courses.delete_calls, 0)

        historical = _run(repo.get_including_archived(str(course_id)))
        self.assertEqual(historical.title, "Visible Speech")

    def test_invalid_and_missing_ids_do_not_delete(self) -> None:
        db, _course_id, _instructor_id, _user_id, _student_id = self._world()
        service = CourseService(CourseRepository(db), audit=_Audit())
        with self.assertRaises(NotFoundError):
            _run(service.delete_course("not-an-id", archived_by="mgr-1", actor_role="admin"))
        with self.assertRaises(NotFoundError):
            _run(service.delete_course(str(ObjectId()), archived_by="mgr-1", actor_role="admin"))
        self.assertEqual(db["courses"].delete_calls, 0)
        self.assertEqual(len(db["courses"].documents), 1)

    def test_archived_course_rejects_new_enrollment_and_dashboard_hides_it(self) -> None:
        db, course_id, _instructor_id, user_id, _student_id = self._world()
        course_repo = CourseRepository(db)
        service = CourseService(course_repo, audit=_Audit())
        current = _user(user_id)
        dashboard = _run(get_student_dashboard(
            current,
            EnrollmentRepository(db),
            StudentRepository(db),
            course_repo,
            InstructorRepository(db),
            UserRepository(db),
            CourseMaterialService(CourseMaterialRepository(db)),
        ))
        self.assertEqual(len(dashboard["enrollments"]), 1)

        _run(service.delete_course(str(course_id), archived_by=current.id, actor_role="admin"))
        hidden = _run(get_student_dashboard(
            current,
            EnrollmentRepository(db),
            StudentRepository(db),
            course_repo,
            InstructorRepository(db),
            UserRepository(db),
            CourseMaterialService(CourseMaterialRepository(db)),
        ))
        self.assertEqual(hidden["enrollments"], [])

        enrollment = _run(EnrollmentRepository(db).get_by_card_number("CARD-1"))
        self.assertEqual(enrollment.payment_status, "paid")
        self.assertEqual(enrollment.status, "active")
        card = _run(verify_enrollment_card(
            "CARD-1",
            EnrollmentRepository(db),
            StudentRepository(db),
            UserRepository(db),
            course_repo,
        ))
        self.assertTrue(card.valid)
        self.assertEqual(card.course_name, "Visible Speech")

        with self.assertRaises(NotFoundError):
            _run(enroll_in_course(
                str(course_id),
                EnrollmentCreate(class_type="online"),
                current,
                EnrollmentRepository(db),
                StudentRepository(db),
                course_repo,
            ))
        self.assertEqual(len(db["enrollments"].documents), 1)

    def test_history_survives_course_archival(self) -> None:
        db, course_id, instructor_id, user_id, student_id = self._world()
        enrollment_id = db["enrollments"].documents[0]["_id"]
        payment_id, result_id, attendance_id, certificate_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        db.add("payments", [{
            "_id": payment_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_id": enrollment_id,
            "amount": 1500,
            "payment_status": "completed",
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("results", [{
            "_id": result_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_id": enrollment_id,
            "assessment_name": "Final",
            "marks_obtained": 90,
            "total_marks": 100,
            "issued_by": user_id,
            "issued_date": NOW,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("attendances", [{
            "_id": attendance_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_id": enrollment_id,
            "date": NOW,
            "status": "present",
            "marked_by": user_id,
            "is_excused": False,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("certificates", [{
            "_id": certificate_id,
            "student_id": student_id,
            "course_id": course_id,
            "enrollment_id": enrollment_id,
            "certificate_number": "BVX-1",
            "issued_by": user_id,
            "is_verified": True,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        _run(CourseService(CourseRepository(db), audit=_Audit()).delete_course(
            str(course_id),
            archived_by="admin-1",
            actor_role="admin",
        ))
        self.assertEqual(_run(PaymentRepository(db).get_by_id(str(payment_id))).amount, 1500)
        self.assertEqual(len(_run(ResultRepository(db).get_by_student_and_course(str(student_id), str(course_id)))), 1)
        self.assertEqual(_run(AttendanceRepository(db).get_by_id(str(attendance_id))).status, "present")
        self.assertEqual(_run(CertificateRepository(db).get_by_id(str(certificate_id))).certificate_number, "BVX-1")
        self.assertEqual(_run(EnrollmentRepository(db).get_by_id(str(enrollment_id))).course_id, str(course_id))
        for name in ("payments", "results", "attendances", "certificates", "enrollments"):
            self.assertEqual(db[name].delete_calls, 0)
            self.assertIsNone(db[name].documents[0].get("archived_at"))
        self.assertEqual(instructor_id, db["courses"].documents[0]["instructor_id"])

    def test_legacy_course_without_archived_at_stays_active(self) -> None:
        course_id, instructor_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id, instructor_id, title="Legacy", include_archived_field=False)])
        repo = CourseRepository(db)
        self.assertEqual(_run(repo.get_by_id(str(course_id))).title, "Legacy")
        self.assertEqual(len(_run(repo.get_published())), 1)
        self.assertEqual(_run(repo.count()), 1)

    def test_purge_is_super_admin_only_and_audited(self) -> None:
        db, course_id, _instructor_id, _user_id, _student_id = self._world()
        audit = _Audit()
        service = CourseService(CourseRepository(db), audit=audit)
        _run(service.delete_course(str(course_id), archived_by="admin-1", actor_role="admin"))
        with self.assertRaises(ForbiddenError):
            _run(service.purge_course(str(course_id), actor_role="admin", actor_id="admin-1"))
        self.assertEqual(db["courses"].delete_calls, 0)
        self.assertEqual(len(db["courses"].documents), 1)
        _run(service.purge_course(str(course_id), actor_role="super_admin", actor_id="root"))
        self.assertEqual(db["courses"].documents, [])
        self.assertEqual(db["courses"].delete_calls, 1)
        purge = audit.events[-1]
        self.assertEqual(purge["action"], "course.purge")
        self.assertEqual(purge["actor_id"], "root")
        self.assertEqual(purge["actor_role"], "super_admin")
        self.assertIsNone(_run(CourseRepository(db).get_including_archived(str(course_id))))


class ContentArchiveTests(unittest.TestCase):
    def _ids(self) -> tuple[ObjectId, ObjectId, ObjectId]:
        return ObjectId(), ObjectId(), ObjectId()

    def test_learning_content_delete_archives_and_blocks_archived_parents(self) -> None:
        course_id, actor_id, other_id = self._ids()
        db = _Database()
        db.add("courses", [_course(course_id, actor_id)])
        material_id, assignment_id, session_id, announcement_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        submission_id = ObjectId()
        db.add("course_materials", [{
            "_id": material_id,
            "course_id": course_id,
            "title": "Lesson",
            "material_type": "document",
            "order": 1,
            "is_published": True,
            "created_by": actor_id,
            "created_at": NOW,
            "updated_at": NOW,
            "archived_at": None,
        }])
        db.add("assignments", [{
            "_id": assignment_id,
            "course_id": course_id,
            "title": "Homework",
            "description": "Read",
            "max_marks": 10,
            "assignment_type": "homework",
            "is_published": True,
            "created_by": actor_id,
            "created_at": NOW,
            "updated_at": NOW,
            "archived_at": None,
        }])
        db.add("assignment_submissions", [{
            "_id": submission_id,
            "assignment_id": assignment_id,
            "student_id": other_id,
            "course_id": course_id,
            "enrollment_id": other_id,
            "status": "pending",
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("live_sessions", [{
            "_id": session_id,
            "course_id": course_id,
            "title": "Live",
            "start_time": NOW,
            "end_time": NOW,
            "instructor_id": actor_id,
            "created_by": actor_id,
            "status": "scheduled",
            "created_at": NOW,
            "updated_at": NOW,
            "archived_at": None,
        }])
        db.add("announcements", [{
            "_id": announcement_id,
            "course_id": course_id,
            "title": "News",
            "content": "Hello",
            "priority": "normal",
            "is_published": True,
            "expires_at": None,
            "created_by": actor_id,
            "created_at": NOW,
            "updated_at": NOW,
            "archived_at": None,
        }])
        materials = CourseMaterialService(CourseMaterialRepository(db), courses=CourseRepository(db), audit=_Audit())
        assignments = AssignmentService(AssignmentRepository(db), AssignmentSubmissionRepository(db), courses=CourseRepository(db), audit=_Audit())
        sessions = LiveSessionService(LiveSessionRepository(db), courses=CourseRepository(db), audit=_Audit())
        announcements = AnnouncementService(AnnouncementRepository(db), courses=CourseRepository(db), audit=_Audit())

        for service, method, record_id in (
            (materials, "delete_material", material_id),
            (assignments, "delete_assignment", assignment_id),
            (sessions, "delete_session", session_id),
            (announcements, "delete_announcement", announcement_id),
        ):
            with self.assertRaises(ForbiddenError):
                _run(getattr(service, method)(str(record_id), archived_by="student", actor_role="user"))
            _run(getattr(service, method)(str(record_id), archived_by="admin-1", actor_role="admin"))
            with self.assertRaises(NotFoundError):
                _run(getattr(service, method)(str(record_id), archived_by="admin-1", actor_role="admin"))

        self.assertIsNone(_run(CourseMaterialRepository(db).get_by_id(str(material_id))))
        self.assertEqual(_run(CourseMaterialRepository(db).get_by_course(str(course_id))), [])
        self.assertIsNone(_run(AssignmentRepository(db).get_by_id(str(assignment_id))))
        self.assertEqual(_run(AssignmentRepository(db).get_by_course(str(course_id))), [])
        self.assertEqual(len(_run(AssignmentSubmissionRepository(db).get_by_assignment(str(assignment_id)))), 1)
        self.assertIsNone(_run(LiveSessionRepository(db).get_by_id(str(session_id))))
        self.assertEqual(_run(LiveSessionRepository(db).get_by_course(str(course_id))), [])
        self.assertIsNone(_run(AnnouncementRepository(db).get_by_id(str(announcement_id))))
        self.assertEqual(_run(AnnouncementRepository(db).get_by_course(str(course_id))), [])
        for name in ("course_materials", "assignments", "live_sessions", "announcements", "assignment_submissions"):
            self.assertEqual(db[name].delete_calls, 0)

        _run(CourseService(CourseRepository(db), audit=_Audit()).delete_course(
            str(course_id), archived_by="admin-1", actor_role="admin",
        ))
        with self.assertRaises(NotFoundError):
            _run(materials.create_material(
                CourseMaterialCreate(course_id=str(course_id), title="New", material_type="document"),
                str(actor_id),
            ))
        with self.assertRaises(NotFoundError):
            _run(assignments.create_assignment(
                AssignmentCreate(
                    course_id=str(course_id),
                    title="New",
                    description="Work",
                    max_marks=5,
                    assignment_type="homework",
                ),
                str(actor_id),
            ))
        self.assertEqual(len(db["course_materials"].documents), 1)
        self.assertEqual(len(db["assignments"].documents), 1)

    def test_active_content_of_an_archived_course_leaves_current_learning_views(self) -> None:
        course_id, actor_id, student_id = ObjectId(), ObjectId(), ObjectId()
        material_id, assignment_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("courses", [_course(course_id, actor_id)])
        db.add("course_materials", [{
            "_id": material_id,
            "course_id": course_id,
            "title": "Still stored",
            "material_type": "document",
            "is_published": True,
            "created_by": actor_id,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("assignments", [{
            "_id": assignment_id,
            "course_id": course_id,
            "title": "Open work",
            "description": "Read",
            "is_published": True,
            "created_by": actor_id,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        _run(CourseService(CourseRepository(db), audit=_Audit()).delete_course(
            str(course_id), archived_by="admin-1", actor_role="admin",
        ))
        enrollment = SimpleNamespace(id="enr", course_id=str(course_id), student_id=str(student_id))
        listed = _run(get_course_materials(
            str(course_id),
            (SimpleNamespace(id=str(student_id)), [enrollment]),
            CourseMaterialService(CourseMaterialRepository(db)),
            CourseRepository(db),
        ))
        self.assertEqual(listed.items, [])
        self.assertEqual(listed.total, 0)
        self.assertEqual(db["course_materials"].documents[0]["title"], "Still stored")
        self.assertIsNone(db["course_materials"].documents[0].get("archived_at"))
        assignments = AssignmentService(
            AssignmentRepository(db),
            AssignmentSubmissionRepository(db),
            courses=CourseRepository(db),
        )
        with self.assertRaises(NotFoundError):
            _run(assignments.submit_assignment(
                AssignmentSubmissionCreate(assignment_id=str(assignment_id), submission_text="Answer"),
                str(student_id),
                str(course_id),
                "enr",
            ))
        self.assertEqual(db["assignment_submissions"].documents, [])

    def test_forum_and_calendar_deletes_archive(self) -> None:
        course_id, author_id = ObjectId(), ObjectId()
        post_id, event_id = ObjectId(), ObjectId()
        db = _Database()
        db.add("forum_posts", [{
            "_id": post_id,
            "course_id": course_id,
            "author_id": author_id,
            "content": "Question",
            "created_at": NOW,
            "updated_at": NOW,
        }])
        db.add("calendar_events", [{
            "_id": event_id,
            "course_id": course_id,
            "title": "Class",
            "start_time": NOW,
            "created_by": author_id,
            "created_at": NOW,
            "updated_at": NOW,
        }])
        _run(ForumService(ForumPostRepository(db), UserRepository(db)).delete_post(str(post_id), archived_by="admin-1"))
        _run(CalendarEventService(CalendarEventRepository(db)).delete_event(str(event_id), archived_by="admin-1"))
        self.assertIsNone(_run(ForumPostRepository(db).get_by_id(str(post_id))))
        self.assertIsNone(_run(CalendarEventRepository(db).get_by_id(str(event_id))))
        self.assertEqual(db["forum_posts"].delete_calls, 0)
        self.assertEqual(db["calendar_events"].delete_calls, 0)
        self.assertIsNotNone(db["forum_posts"].documents[0]["archived_at"])
        self.assertIsNotNone(db["calendar_events"].documents[0]["archived_at"])


if __name__ == "__main__":
    unittest.main()
