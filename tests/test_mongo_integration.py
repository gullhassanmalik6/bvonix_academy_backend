"""Live MongoDB integration tests.

Skipped unless both of these environment variables are set:

    MONGODB_TEST_URI   connection string for a disposable test server
    MONGODB_TEST_DB    database name, which must start with bvonix_test

Run from bvonix_academy_backend:

    $env:MONGODB_TEST_URI = "mongodb://localhost:27017"
    $env:MONGODB_TEST_DB = "bvonix_test_academy"
    .\\.venv\\Scripts\\python.exe -m unittest tests.test_mongo_integration -v

The application settings (MONGODB_URI and MONGODB_DB) are never read.
The guard refuses APP_ENV production or prod, the database names
bvonix_academy, production, and prod, and any name containing "prod"
or missing the bvonix_test prefix. A refused configuration fails before
a client is opened.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

from bson import ObjectId

FORBIDDEN_ENVIRONMENTS = {"production", "prod"}
FORBIDDEN_DATABASE_NAMES = {"bvonix_academy", "production", "prod"}


def validate_test_database(uri: str, database_name: str, app_env: str) -> None:
    """Refuse any target that could be a production database."""
    name = database_name.strip()
    environment = app_env.strip().lower()
    if environment in FORBIDDEN_ENVIRONMENTS:
        raise RuntimeError("Refusing integration tests when APP_ENV is a production environment.")
    folded = name.lower()
    if (
        not uri.strip()
        or folded in FORBIDDEN_DATABASE_NAMES
        or "prod" in folded
        or not folded.startswith("bvonix_test")
    ):
        raise RuntimeError("Refusing integration tests for this database name.")


def configured_test_database() -> tuple[str, str] | None:
    uri = os.environ.get("MONGODB_TEST_URI", "").strip()
    name = os.environ.get("MONGODB_TEST_DB", "").strip()
    if not uri or not name:
        return None
    validate_test_database(uri, name, os.environ.get("APP_ENV", ""))
    return uri, name


class MongoIntegrationSafetyTests(unittest.TestCase):
    def test_missing_configuration_does_not_select_a_database(self) -> None:
        previous = {key: os.environ.get(key) for key in ("MONGODB_TEST_URI", "MONGODB_TEST_DB", "APP_ENV")}
        try:
            os.environ.pop("MONGODB_TEST_URI", None)
            os.environ.pop("MONGODB_TEST_DB", None)
            os.environ["APP_ENV"] = "development"
            self.assertIsNone(configured_test_database())
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_production_names_and_environments_are_refused(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_test_database("mongodb://localhost:27017", "bvonix_academy", "development")
        with self.assertRaises(RuntimeError):
            validate_test_database("mongodb://localhost:27017", "production", "development")
        with self.assertRaises(RuntimeError):
            validate_test_database("mongodb://localhost:27017", "bvonix_test_prod", "development")
        with self.assertRaises(RuntimeError):
            validate_test_database("mongodb://localhost:27017", "bvonix_test_academy", "production")
        validate_test_database("mongodb://localhost:27017", "bvonix_test_academy", "development")


@unittest.skipUnless(configured_test_database() is not None, "Set MONGODB_TEST_URI and MONGODB_TEST_DB to run live MongoDB integration tests.")
class LiveMongoIntegrationTests(unittest.TestCase):
    """Runs only against an explicitly supplied bvonix_test database."""

    def setUp(self) -> None:
        import asyncio

        from motor.motor_asyncio import AsyncIOMotorClient

        uri, name = configured_test_database()
        self.loop = asyncio.new_event_loop()
        self.client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
        self.db = self.client[name]
        self.collection_name = f"integration_{ObjectId()}"
        self.loop.run_until_complete(self.client.admin.command("ping"))

    def tearDown(self) -> None:
        self.loop.run_until_complete(self.db.drop_collection(self.collection_name))
        self.client.close()
        self.loop.close()

    def test_pagination_archive_filter_count_aggregation_and_index(self) -> None:
        from app.repositories.listing import stable_sort

        collection = self.db[self.collection_name]

        async def scenario():
            now = datetime.now(timezone.utc)
            await collection.insert_many([
                {"_id": ObjectId(), "name": "visible", "status": "active", "archived_at": None, "created_at": now},
                {"_id": ObjectId(), "name": "legacy", "status": "active", "created_at": now},
                {"_id": ObjectId(), "name": "stored", "status": "active", "archived_at": now, "created_at": now},
            ])
            active = {"archived_at": None, "status": "active"}
            total = await collection.count_documents(active)
            page = await collection.find(active).sort(stable_sort([("created_at", 1)])).skip(0).limit(100).to_list(length=100)
            grouped = await collection.aggregate([
                {"$match": active},
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]).to_list(length=10)
            await collection.create_index([("status", 1), ("archived_at", 1), ("created_at", 1)])
            indexes = await collection.index_information()
            return total, page, grouped, indexes

        total, page, grouped, indexes = self.loop.run_until_complete(scenario())
        self.assertEqual(total, 2)
        self.assertEqual({row["name"] for row in page}, {"visible", "legacy"})
        self.assertEqual(grouped[0]["count"], 2)
        self.assertTrue(any("status" in spec and "archived_at" in spec for spec in indexes.values()))


if __name__ == "__main__":
    unittest.main()
