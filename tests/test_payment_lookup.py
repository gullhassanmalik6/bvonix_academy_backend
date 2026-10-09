"""Payment get-by-id uses PaymentRepository, not an in-memory stand-in."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

from bson import ObjectId

from app.models.user import User
from app.repositories.payment_repository import PaymentRepository
from app.routes.admin import admin_update_payment
from app.schemas.payment import PaymentUpdate
from app.services.payment_service import PaymentService
from app.utils.exceptions import NotFoundError


def _matches(document: dict, query: dict) -> bool:
    """Mirror MongoDB `archived_at: null`, which also matches a missing field."""
    for key, expected in query.items():
        if key == "archived_at" and expected is None:
            if document.get("archived_at") is not None:
                return False
            continue
        if document.get(key) != expected:
            return False
    return True


class _Collection:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.find_one_calls = 0
        self.update_calls = 0

    async def find_one(self, query: dict) -> dict | None:
        self.find_one_calls += 1
        for document in self.documents:
            if _matches(document, query):
                return document
        return None

    async def find_one_and_update(self, query: dict, update: dict, return_document: bool = False) -> dict | None:
        del return_document
        self.update_calls += 1
        for document in self.documents:
            if _matches(document, query):
                document.update(update.get("$set", {}))
                return document
        return None


class _Database:
    def __init__(self, collection: _Collection) -> None:
        self._collection = collection

    def __getitem__(self, name: str) -> _Collection:
        return self._collection


def _payment(payment_id: ObjectId, **extra) -> dict:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    document = {
        "_id": payment_id,
        "student_id": ObjectId(),
        "course_id": ObjectId(),
        "enrollment_id": ObjectId(),
        "amount": 1500.0,
        "currency": "PKR",
        "payment_method": "cash",
        "payment_status": "pending",
        "transaction_id": None,
        "invoice_number": "INV-1",
        "invoice_url": None,
        "payment_date": None,
        "due_date": None,
        "scholarship_discount": 0.0,
        "notes": None,
        "created_by": ObjectId(),
        "created_at": now,
        "updated_at": now,
    }
    document.update(extra)
    return document


class PaymentLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active_id = ObjectId()
        self.archived_id = ObjectId()
        self.legacy_id = ObjectId()
        self.collection = _Collection(
            [
                _payment(self.active_id, archived_at=None),
                _payment(self.archived_id, archived_at=datetime(2026, 2, 1, tzinfo=timezone.utc)),
                _payment(self.legacy_id),
            ]
        )
        self.repo = PaymentRepository(_Database(self.collection))
        self.service = PaymentService(self.repo)

    def test_active_payment_can_be_fetched_by_id(self) -> None:
        payment = asyncio.run(self.repo.get_by_id(str(self.active_id)))
        self.assertIsNotNone(payment)
        self.assertEqual(payment.id, str(self.active_id))
        self.assertEqual(payment.payment_status, "pending")
        self.assertIsNone(payment.archived_at)

    def test_archived_payment_is_hidden_from_the_operational_lookup(self) -> None:
        self.assertIsNone(asyncio.run(self.repo.get_by_id(str(self.archived_id))))
        with self.assertRaises(NotFoundError):
            asyncio.run(self.service.get_payment(str(self.archived_id)))
        self.assertEqual(self.collection.update_calls, 0)

    def test_legacy_payment_without_archived_at_stays_accessible(self) -> None:
        stored = self.collection.documents[2]
        self.assertNotIn("archived_at", stored)
        payment = asyncio.run(self.service.get_payment(str(self.legacy_id)))
        self.assertEqual(payment.id, str(self.legacy_id))

    def test_invalid_and_missing_ids_do_not_raise_unexpected_errors(self) -> None:
        before = self.collection.find_one_calls
        self.assertIsNone(asyncio.run(self.repo.get_by_id("not-an-object-id")))
        self.assertEqual(self.collection.find_one_calls, before)
        missing = str(ObjectId())
        self.assertIsNone(asyncio.run(self.repo.get_by_id(missing)))
        with self.assertRaises(NotFoundError) as raised:
            asyncio.run(self.service.get_payment(missing))
        self.assertEqual(raised.exception.status_code, 404)
        with self.assertRaises(NotFoundError):
            asyncio.run(self.service.get_payment("not-an-object-id"))

    def test_admin_payment_update_uses_the_repository_lookup(self) -> None:
        admin = User(
            id="admin-1",
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
            is_active=True,
            role="admin",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        updated = asyncio.run(
            admin_update_payment(
                str(self.active_id),
                PaymentUpdate(notes="receipt checked"),
                self.service,
                admin,
            )
        )
        self.assertEqual(updated.id, str(self.active_id))
        self.assertEqual(updated.notes, "receipt checked")
        self.assertEqual(updated.payment_status, "pending")
        self.assertGreater(self.collection.find_one_calls, 0)
        self.assertEqual(self.collection.update_calls, 1)


if __name__ == "__main__":
    unittest.main()
