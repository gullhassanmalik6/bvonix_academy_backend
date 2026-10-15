"""Public course decision payload uses stored facts and hides lesson files."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.course import Course
from app.services.course_decision import build_course_decision
from app.utils.exceptions import NotFoundError


def _course(**overrides) -> Course:
    now = datetime.now(timezone.utc)
    values = {
        "id": "course-1",
        "title": "English speaking",
        "description": "Practice spoken English in class.",
        "instructor_id": "inst-1",
        "duration_hours": 24,
        "price": 5000,
        "is_published": True,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Course(**values)


class _Instructors:
    def __init__(self, record) -> None:
        self.record = record

    async def get_by_id(self, instructor_id: str):
        if self.record and self.record.id == instructor_id:
            return self.record
        return None


class _Users:
    def __init__(self, user) -> None:
        self.user = user

    async def get_by_id(self, user_id: str):
        if self.user and self.user.id == user_id:
            return self.user
        return None


class _Pages:
    def __init__(self, items) -> None:
        self.items = items

    async def get_by_course(self, course_id: str, published_only: bool = True):
        return list(self.items)


class _Record:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class CourseDecisionTests(unittest.TestCase):
    def test_unpublished_course_is_hidden(self) -> None:
        with self.assertRaises(NotFoundError):
            self._run(_course(is_published=False), _Record(id="inst-1"), _Record(id="user-1"), [], [])

    def test_payload_uses_stored_facts_and_omits_files(self) -> None:
        instructor = _Record(
            id="inst-1",
            user_id="user-1",
            specialization=" Spoken English ",
            bio="Teaches conversation.",
            years_of_experience=6,
            archived_at=None,
        )
        user = _Record(id="user-1", full_name="Amina Khan", email="amina@example.com", archived_at=None)
        lesson = _Record(
            title="Introductions",
            description="First conversation",
            material_type="video",
            order=1,
            duration_minutes=15,
            is_required=True,
            content_url="https://files.example/secret.mp4",
            file_path="/secret.mp4",
        )
        work = _Record(
            title="Shop dialogue",
            description="Record a shop conversation.",
            assignment_type="project",
            instructions="Use this private brief.",
        )
        decision = self._run(_course(), instructor, user, [lesson], [work])
        dumped = decision.model_dump()
        self.assertEqual(dumped["instructor"]["name"], "Amina Khan")
        self.assertEqual(dumped["instructor"]["specialization"], "Spoken English")
        self.assertEqual(dumped["instructor"]["years_of_experience"], 6)
        self.assertNotIn("email", dumped["instructor"])
        self.assertEqual(dumped["lessons"][0]["title"], "Introductions")
        self.assertNotIn("content_url", dumped["lessons"][0])
        self.assertNotIn("file_path", dumped["lessons"][0])
        self.assertEqual(dumped["practical_work"][0]["assignment_type"], "project")
        self.assertNotIn("instructions", dumped["practical_work"][0])
        self.assertNotIn("secret", str(dumped))
        self.assertNotIn("private brief", str(dumped))

    def test_archived_instructor_is_omitted(self) -> None:
        instructor = _Record(
            id="inst-1",
            user_id="user-1",
            specialization="Spoken English",
            bio=None,
            years_of_experience=None,
            archived_at=datetime.now(timezone.utc),
        )
        decision = self._run(_course(), instructor, None, [], [])
        self.assertIsNone(decision.instructor)
        self.assertEqual(decision.lesson_total, 0)
        self.assertEqual(decision.practical_total, 0)

    def _run(self, course, instructor, user, lessons, practical):
        import asyncio

        return asyncio.run(
            build_course_decision(
                course,
                instructors=_Instructors(instructor),
                users=_Users(user),
                materials=_Pages(lessons),
                assignments=_Pages(practical),
            )
        )
