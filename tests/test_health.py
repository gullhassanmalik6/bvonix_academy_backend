"""Liveness does not depend on MongoDB. Readiness does."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.core.health import check_database, live_payload, readiness_response
from app.routes.api import health


class HealthTests(unittest.TestCase):
    def test_application_is_alive_without_checking_the_database(self) -> None:
        with patch("app.core.health.mongodb.ping", new_callable=AsyncMock) as ping:
            payload = live_payload()
        ping.assert_not_called()
        self.assertEqual(payload["status"], "alive")
        self.assertTrue(payload["version"])

    def test_existing_health_endpoint_stays_ok(self) -> None:
        self.assertEqual(asyncio.run(health()), {"status": "ok"})

    def test_ready_when_database_is_available(self) -> None:
        import json

        with (
            patch("app.core.health.check_database", new=AsyncMock(return_value=True)),
            patch("app.core.health.check_storage", return_value=True),
        ):
            response = asyncio.run(readiness_response())
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["checks"]["database"]["status"], "up")
        self.assertEqual(body["checks"]["storage"]["status"], "up")
        self.assertEqual(body["version"], live_payload()["version"])

    def test_database_check_follows_ping(self) -> None:
        with patch("app.core.health.mongodb.ping", new=AsyncMock(return_value=True)):
            self.assertTrue(asyncio.run(check_database()))
        with patch("app.core.health.mongodb.ping", new=AsyncMock(return_value=False)):
            self.assertFalse(asyncio.run(check_database()))
        with patch("app.core.health.mongodb.ping", new=AsyncMock(side_effect=ConnectionError("down"))):
            self.assertFalse(asyncio.run(check_database()))

    def test_not_ready_when_database_is_unavailable(self) -> None:
        import json

        with (
            patch("app.core.health.check_database", new=AsyncMock(return_value=False)),
            patch("app.core.health.check_storage", return_value=True),
        ):
            response = asyncio.run(readiness_response())
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["checks"]["database"]["status"], "down")


if __name__ == "__main__":
    unittest.main()
