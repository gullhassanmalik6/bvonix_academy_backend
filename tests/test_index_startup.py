"""An index creation failure is logged and does not abort startup."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from app.db.index_status import required_indexes_ready, reset_required_index_status
from app.db.mongodb import mongodb
from app.main import lifespan

_INDEX_REPOSITORIES = (
    "UserRepository",
    "CourseRepository",
    "InstructorRepository",
    "StudentRepository",
    "EnrollmentRepository",
    "ResultRepository",
    "AttendanceRepository",
    "AttendanceClaimRepository",
    "AttendanceCorrectionRepository",
    "CertificateRepository",
    "ScholarshipRepository",
    "CourseMaterialRepository",
    "AssignmentRepository",
    "AssignmentSubmissionRepository",
    "LiveSessionRepository",
    "AnnouncementRepository",
    "PaymentRepository",
    "ForumPostRepository",
    "NotificationRepository",
    "CalendarEventRepository",
    "AuditLogRepository",
    "SessionRepository",
)


class IndexStartupTests(unittest.TestCase):
    def test_index_creation_failure_is_logged_and_startup_continues(self) -> None:
        disconnect = AsyncMock()

        async def connect_without_a_database() -> bool:
            mongodb._db = object()
            return True

        async def exercise() -> None:
            with ExitStack() as stack:
                stack.enter_context(patch("app.main.mongodb.connect", new=connect_without_a_database))
                stack.enter_context(patch("app.main.mongodb.disconnect", new=disconnect))
                for name in _INDEX_REPOSITORIES:
                    effect = (
                        RuntimeError("index failed")
                        if name == "UserRepository"
                        else None
                    )
                    stack.enter_context(
                        patch(
                            f"app.main.{name}.ensure_indexes",
                            new=AsyncMock(side_effect=effect),
                        )
                    )
                with self.assertLogs("app.main", level="ERROR") as captured:
                    async with lifespan(object()):
                        started = True
            self.assertTrue(started)
            message = "\n".join(captured.output)
            self.assertIn("index creation failed for 1 collection", message)
            self.assertNotIn("index failed", message)
            self.assertFalse(required_indexes_ready())

        reset_required_index_status()
        try:
            asyncio.run(exercise())
        finally:
            mongodb._db = None
            reset_required_index_status()
        disconnect.assert_awaited()


if __name__ == "__main__":
    unittest.main()
