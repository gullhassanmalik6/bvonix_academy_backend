"""Attendance corrections move requested → under_review → approved or rejected."""

from __future__ import annotations

import asyncio
import inspect
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.admin import get_management_user
from app.core.attendance_correction import assert_correction_transition
from app.models.attendance import Attendance
from app.models.attendance_correction import AttendanceCorrection
from app.models.user import User
from app.routes.admin import (
    admin_approve_attendance_correction,
    admin_reject_attendance_correction,
    admin_review_attendance_correction,
)
from app.services.attendance_correction_service import AttendanceCorrectionService
from app.utils.exceptions import ConflictError, ForbiddenError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attendance(**overrides) -> Attendance:
    values = dict(
        id="attendance-1",
        student_id="student-1",
        course_id="course-1",
        enrollment_id="enrollment-1",
        date=_now(),
        status="absent",
        marked_by="admin-1",
        notes=None,
        absence_reason=None,
        absence_reason_submitted_at=None,
        is_excused=False,
        created_at=_now(),
        updated_at=_now(),
    )
    values.update(overrides)
    return Attendance(**values)


def _user(role: str, user_id: str | None = None) -> User:
    return User(
        id=user_id or f"{role}-1",
        email=f"{role}@example.com",
        full_name=role,
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=_now(),
    )


class _Attendance:
    def __init__(self, record: Attendance) -> None:
        self.record = record
        self.applied: list[str] = []

    async def get_attendance(self, attendance_id: str) -> Attendance:
        if self.record.id != attendance_id:
            raise NotFoundError("Attendance not found")
        return self.record

    async def apply_corrected_status(self, attendance_id: str, status: str) -> Attendance:
        if self.record.id != attendance_id:
            raise NotFoundError("Attendance not found")
        self.applied.append(status)
        self.record.status = status
        self.record.is_excused = status == "excused"
        return self.record


class _Corrections:
    def __init__(self) -> None:
        self.items: dict[str, AttendanceCorrection] = {}
        self.list_calls: list[dict] = []
        self._next = 1
        self.fail_create = False

    async def find_open_for_attendance(self, attendance_id: str) -> AttendanceCorrection | None:
        for item in self.items.values():
            if item.attendance_id == attendance_id and item.status in {"requested", "under_review"}:
                return item
        return None

    async def create_request(self, correction: AttendanceCorrection) -> AttendanceCorrection:
        if self.fail_create:
            raise DuplicateKeyError("duplicate")
        saved = replace(correction, id=f"correction-{self._next}")
        self._next += 1
        self.items[saved.id] = saved
        return saved

    async def get_by_id(self, correction_id: str) -> AttendanceCorrection | None:
        return self.items.get(correction_id)

    async def save(self, correction: AttendanceCorrection) -> AttendanceCorrection | None:
        if correction.id not in self.items:
            return None
        self.items[correction.id] = correction
        return correction

    async def list_page(self, **kwargs):
        self.list_calls.append(kwargs)
        rows = list(self.items.values())
        return rows, len(rows)


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.fail = False

    async def record(self, **kwargs):
        if self.fail:
            return None
        self.records.append(kwargs)
        return kwargs


def _service(attendance: Attendance | None = None, audit: _Audit | None = None):
    record = attendance or _attendance()
    marks = _Attendance(record)
    corrections = _Corrections()
    service = AttendanceCorrectionService(corrections, marks, audit=audit if audit is not None else _Audit())
    return service, marks, corrections, service._audit


class AttendanceCorrectionTests(unittest.TestCase):
    def test_student_can_request_a_correction_for_their_own_mark(self) -> None:
        service, _marks, _corrections, _audit = _service()

        created = asyncio.run(
            service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            )
        )

        self.assertEqual(created.status, "requested")
        self.assertEqual(created.decision, None)
        self.assertEqual(created.requester_id, "user-1")
        self.assertEqual(created.previous_status, "absent")
        self.assertFalse(created.previous_is_excused)
        self.assertEqual(created.requested_status, "present")
        self.assertIsNotNone(created.requested_at)
        self.assertIsNone(created.reviewer_id)
        self.assertIsNone(created.reviewed_at)

    def test_students_cannot_request_someone_elses_mark_or_a_duplicate(self) -> None:
        service, _marks, corrections, _audit = _service()
        with self.assertRaises(NotFoundError):
            asyncio.run(
                service.request_correction(
                    attendance_id="attendance-1",
                    student_id="student-2",
                    requester_id="user-2",
                    reason="This is not my attendance record",
                    requested_status="present",
                )
            )
        asyncio.run(
            service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            )
        )
        with self.assertRaises(ConflictError):
            asyncio.run(
                service.request_correction(
                    attendance_id="attendance-1",
                    student_id="student-1",
                    requester_id="user-1",
                    reason="Please review this absence again",
                    requested_status="excused",
                )
            )
        corrections.fail_create = True
        corrections.items.clear()
        with self.assertRaises(ConflictError):
            asyncio.run(
                service.request_correction(
                    attendance_id="attendance-1",
                    student_id="student-1",
                    requester_id="user-1",
                    reason="I was present for the full session",
                    requested_status="present",
                )
            )

    def test_same_status_and_archived_marks_are_rejected(self) -> None:
        service, _marks, _corrections, _audit = _service()
        with self.assertRaises(ConflictError):
            asyncio.run(
                service.request_correction(
                    attendance_id="attendance-1",
                    student_id="student-1",
                    requester_id="user-1",
                    reason="Please keep the same status",
                    requested_status="absent",
                )
            )
        archived, _marks, _corrections, _audit = _service(_attendance(archived_at=_now()))
        with self.assertRaises(NotFoundError):
            asyncio.run(
                archived.request_correction(
                    attendance_id="attendance-1",
                    student_id="student-1",
                    requester_id="user-1",
                    reason="This archived mark should stay hidden",
                    requested_status="present",
                )
            )

    def test_review_then_approve_records_states_and_an_audit(self) -> None:
        service, marks, _corrections, audit = _service()
        created = asyncio.run(
            service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            )
        )
        reviewing = asyncio.run(
            service.start_review(created.id, actor_id="manager-1", actor_role="academic_manager")
        )
        self.assertEqual(reviewing.status, "under_review")
        self.assertEqual(reviewing.reviewer_id, "manager-1")
        self.assertIsNotNone(reviewing.review_started_at)
        self.assertIsNone(reviewing.decision)

        approved = asyncio.run(
            service.approve(
                created.id,
                actor_id="admin-1",
                actor_role="admin",
                review_note="Confirmed with the instructor",
            )
        )

        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.decision, "approved")
        self.assertEqual(approved.reviewer_id, "admin-1")
        self.assertEqual(approved.previous_status, "absent")
        self.assertEqual(approved.requested_status, "present")
        self.assertIsNotNone(approved.reviewed_at)
        self.assertEqual(marks.record.status, "present")
        self.assertEqual(marks.applied, ["present"])
        self.assertEqual(len(audit.records), 1)
        entry = audit.records[0]
        self.assertEqual(entry["action"], "attendance_correction.approve")
        self.assertEqual(entry["previous"].status, "under_review")
        self.assertEqual(entry["previous"].previous_status, "absent")
        self.assertEqual(entry["current"].decision, "approved")
        self.assertEqual(entry["current"].requested_status, "present")
        self.assertEqual(entry["context"]["previous_attendance_status"], "absent")
        self.assertEqual(entry["context"]["new_attendance_status"], "present")

    def test_rejection_keeps_the_mark_and_writes_an_audit(self) -> None:
        service, marks, _corrections, audit = _service()
        created = asyncio.run(
            service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            )
        )
        asyncio.run(service.start_review(created.id, actor_id="admin-1", actor_role="admin"))
        rejected = asyncio.run(
            service.reject(created.id, actor_id="admin-1", actor_role="admin", review_note="No evidence")
        )

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.decision, "rejected")
        self.assertEqual(rejected.previous_status, "absent")
        self.assertEqual(rejected.requested_status, "present")
        self.assertIsNotNone(rejected.reviewed_at)
        self.assertEqual(marks.record.status, "absent")
        self.assertEqual(marks.applied, [])
        self.assertEqual(audit.records[0]["action"], "attendance_correction.reject")
        self.assertEqual(audit.records[0]["current"].decision, "rejected")

    def test_invalid_transitions_are_rejected(self) -> None:
        with self.assertRaises(ConflictError):
            assert_correction_transition("requested", "approved")
        with self.assertRaises(ConflictError):
            assert_correction_transition("requested", "rejected")
        with self.assertRaises(ConflictError):
            assert_correction_transition("under_review", "requested")
        with self.assertRaises(ConflictError):
            assert_correction_transition("approved", "rejected")
        with self.assertRaises(ConflictError):
            assert_correction_transition("rejected", "approved")

        service, marks, _corrections, _audit = _service()
        created = asyncio.run(
            service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            )
        )
        with self.assertRaises(ConflictError):
            asyncio.run(service.approve(created.id, actor_id="admin-1", actor_role="admin"))
        self.assertEqual(marks.applied, [])
        asyncio.run(service.start_review(created.id, actor_id="admin-1", actor_role="admin"))
        asyncio.run(service.approve(created.id, actor_id="admin-1", actor_role="admin"))
        with self.assertRaises(ConflictError):
            asyncio.run(service.reject(created.id, actor_id="admin-1", actor_role="admin"))

    def test_students_cannot_review_approve_or_reject(self) -> None:
        with self.assertRaises(ForbiddenError):
            asyncio.run(get_management_user(_user("user")))
        service, _marks, _corrections, _audit = _service()
        created = asyncio.run(
            service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            )
        )
        for action in (
            lambda: service.start_review(created.id, actor_id="user-1", actor_role="user"),
            lambda: service.approve(created.id, actor_id="user-1", actor_role="user"),
            lambda: service.reject(created.id, actor_id="user-1", actor_role="user"),
        ):
            with self.assertRaises(ForbiddenError):
                asyncio.run(action())
        self.assertEqual(service._corrections.items[created.id].status, "requested")

    def test_review_routes_require_management_and_lists_stay_in_the_database(self) -> None:
        for endpoint in (
            admin_review_attendance_correction,
            admin_approve_attendance_correction,
            admin_reject_attendance_correction,
        ):
            source = inspect.getsource(endpoint)
            self.assertIn("get_management_user", source)
        service, _marks, corrections, _audit = _service()
        asyncio.run(service.list_corrections(skip=0, limit=20, open_only=True))
        self.assertEqual(corrections.list_calls[0]["open_only"], True)
        self.assertEqual(corrections.list_calls[0]["limit"], 20)

    def test_a_final_decision_fails_when_the_audit_record_cannot_be_written(self) -> None:
        audit = _Audit()
        audit.fail = True
        service, _marks, corrections, _audit = _service(audit=audit)
        created = asyncio.run(
            service.request_correction(
                attendance_id="attendance-1",
                student_id="student-1",
                requester_id="user-1",
                reason="I was present for the full session",
                requested_status="present",
            )
        )
        asyncio.run(service.start_review(created.id, actor_id="admin-1", actor_role="admin"))
        with self.assertRaises(Exception):
            asyncio.run(service.reject(created.id, actor_id="admin-1", actor_role="admin"))
        self.assertEqual(corrections.items[created.id].status, "rejected")


if __name__ == "__main__":
    unittest.main()
