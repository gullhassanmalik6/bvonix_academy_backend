"""List endpoints page, filter, search, and sort in MongoDB rather than in Python."""

from __future__ import annotations

import asyncio
import inspect
import re
import unittest
from datetime import datetime, timedelta, timezone

from app.core.admin import (
    get_admin_user,
    get_management_user,
    get_payment_admin,
    get_scholarship_admin,
)
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.listing import MAX_PAGE_SIZE, clamp_limit, sort_pairs, text_clause
from app.repositories.payment_repository import PAYMENT_SORTS, PaymentRepository
from app.services.payment_service import PaymentService
from app.services.scholarship_service import ScholarshipService
from app.utils.exceptions import ForbiddenError


def _user(role: str) -> User:
    return User(
        id=f"{role}-1",
        email=f"{role}@example.com",
        full_name=role,
        hashed_password="hashed",
        is_active=True,
        role=role,
        created_at=datetime.now(timezone.utc),
    )


def _matches(document: dict, query: dict) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue
        actual = document.get(key)
        if isinstance(expected, dict) and "$regex" in expected:
            flags = re.IGNORECASE if "i" in expected.get("$options", "") else 0
            if actual is None or re.search(expected["$regex"], str(actual), flags) is None:
                return False
            continue
        if key == "archived_at" and expected is None:
            if document.get("archived_at") is not None:
                return False
            continue
        if actual != expected:
            return False
    return True


class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = list(documents)
        self._skip = 0
        self._limit: int | None = None

    def sort(self, spec: list[tuple[str, int]]):
        for field, direction in reversed(spec):
            self.documents.sort(
                key=lambda document: (document.get(field) is None, document.get(field) or ""),
                reverse=direction < 0,
            )
        return self

    def skip(self, count: int):
        self._skip = count
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    async def to_list(self, length: int) -> list[dict]:
        end = self._skip + (self._limit if self._limit is not None else length)
        return self.documents[self._skip:end]


class _Collection:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents

    def find(self, query: dict) -> _Cursor:
        return _Cursor([document for document in self.documents if _matches(document, query)])

    async def count_documents(self, query: dict) -> int:
        return len([document for document in self.documents if _matches(document, query)])


class _Database:
    def __init__(self, collection: _Collection) -> None:
        self._collection = collection

    def __getitem__(self, name: str) -> _Collection:
        return self._collection


class _Row:
    def __init__(self, doc: dict) -> None:
        self.id = doc["_id"]
        self.name = doc["name"]
        self.status = doc["status"]
        self.created_at = doc["created_at"]


class _Rows(BaseRepository):
    collection_name = "rows"

    def _to_model(self, doc: dict) -> _Row:
        return _Row(doc)


def _stamp(hours: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hours)


def _rows() -> list[dict]:
    documents = []
    for index in range(120):
        documents.append(
            {
                "_id": f"row-{index}",
                "name": f"Row {index}",
                "status": "pending" if index % 2 == 0 else "paid",
                "created_at": _stamp(index),
            }
        )
    documents.append(
        {
            "_id": "archived",
            "name": "Archived Ada",
            "status": "pending",
            "created_at": _stamp(200),
            "archived_at": _stamp(201),
        }
    )
    documents.append(
        {
            "_id": "ada",
            "name": "Ada.Lovelace",
            "status": "pending",
            "created_at": _stamp(119),
        }
    )
    return documents


class ListingQueryTests(unittest.TestCase):
    def test_page_size_is_bounded(self) -> None:
        self.assertEqual(clamp_limit(0), 1)
        self.assertEqual(clamp_limit(100), 100)
        self.assertEqual(clamp_limit(10000), MAX_PAGE_SIZE)

    def test_search_text_is_escaped_and_unknown_sort_uses_the_default(self) -> None:
        clause = text_clause("a.b", ("name",))
        self.assertEqual(clause["$or"][0]["name"]["$regex"], r"a\.b")
        self.assertEqual(
            sort_pairs("not-a-field", allowed=PAYMENT_SORTS, default="-created_at"),
            PAYMENT_SORTS["-created_at"],
        )

    def test_pages_filters_search_sort_and_boundaries(self) -> None:
        repo = _Rows(_Database(_Collection(_rows())))
        first, total = asyncio.run(
            repo.find_page({"status": "pending"}, skip=0, limit=2, sort=[("created_at", -1)])
        )
        self.assertEqual(total, 61)
        self.assertEqual([item.id for item in first], ["ada", "row-118"])
        middle, _ = asyncio.run(
            repo.find_page({"status": "pending"}, skip=60, limit=2, sort=[("created_at", -1)])
        )
        self.assertEqual([item.id for item in middle], ["row-0"])
        empty, still = asyncio.run(
            repo.find_page({"status": "pending"}, skip=80, limit=2, sort=[("created_at", -1)])
        )
        self.assertEqual(empty, [])
        self.assertEqual(still, 61)
        none, none_total = asyncio.run(repo.find_page({"status": "missing"}, skip=0, limit=10))
        self.assertEqual(none, [])
        self.assertEqual(none_total, 0)
        searched, search_total = asyncio.run(
            repo.find_page(text_clause("a.b", ("name",)), skip=0, limit=10, sort=[("created_at", -1)])
        )
        self.assertEqual(searched, [])
        self.assertEqual(search_total, 0)
        named, named_total = asyncio.run(
            repo.find_page(text_clause("ada.lovelace", ("name",)), skip=0, limit=10)
        )
        self.assertEqual(named_total, 1)
        self.assertEqual(named[0].id, "ada")
        bounded, bounded_total = asyncio.run(repo.find_page({}, skip=0, limit=500, sort=[("created_at", 1)]))
        self.assertEqual(len(bounded), MAX_PAGE_SIZE)
        self.assertEqual(bounded_total, 121)
        self.assertNotIn("archived", [item.id for item in bounded])


class ListingServiceTests(unittest.TestCase):
    def test_payment_and_scholarship_lists_delegate_to_the_database_page(self) -> None:
        class _Page:
            def __init__(self) -> None:
                self.kwargs = None

            async def list_page(self, **kwargs):
                self.kwargs = kwargs
                return [], 0

        payments = _Page()
        asyncio.run(
            PaymentService(payments).list_payments(
                skip=15,
                limit=25,
                student_id="student-1",
                course_id="course-1",
                payment_status="pending",
                q="INV-9",
                sort="amount",
            )
        )
        self.assertEqual(payments.kwargs["skip"], 15)
        self.assertEqual(payments.kwargs["limit"], 25)
        self.assertEqual(payments.kwargs["payment_status"], "pending")
        self.assertEqual(payments.kwargs["q"], "INV-9")
        self.assertNotIn("10000", inspect.getsource(PaymentService.list_payments))
        self.assertNotIn("10000", inspect.getsource(ScholarshipService.list_scholarships))

        scholarships = _Page()
        asyncio.run(
            ScholarshipService(scholarships).list_scholarships(
                skip=0,
                limit=10,
                student_id="student-1",
                status="active",
                q="merit",
            )
        )
        self.assertEqual(scholarships.kwargs["status"], "active")
        self.assertEqual(scholarships.kwargs["q"], "merit")

    def test_invalid_ids_do_not_scan_the_payment_collection(self) -> None:
        class _Payments(PaymentRepository):
            def __init__(self) -> None:
                pass

            async def find_page(self, *args, **kwargs):
                raise AssertionError("invalid ids must not query the collection")

        items, total = asyncio.run(_Payments().list_page(student_id="not-an-object-id"))
        self.assertEqual(items, [])
        self.assertEqual(total, 0)

    def test_enrollment_filters_are_part_of_the_query(self) -> None:
        class _Enrollments(EnrollmentRepository):
            def __init__(self) -> None:
                self.seen = None

            async def find_page(self, query, *, skip, limit, sort):
                self.seen = (query, skip, limit, sort)
                return [], 0

        repo = _Enrollments()
        asyncio.run(
            repo.list_page(
                skip=4,
                limit=10,
                status="active",
                payment_status="paid",
                verified=True,
                q="a.b",
                sort="status",
            )
        )
        query, skip, limit, sort = repo.seen
        self.assertEqual(skip, 4)
        self.assertEqual(limit, 10)
        self.assertEqual(query["status"], "active")
        self.assertEqual(query["payment_status"], "paid")
        self.assertIs(query["verified_by_admin"], True)
        self.assertIn(r"a\.b", query["$or"][0]["enrollment_card_number"]["$regex"])
        self.assertEqual(sort, [("status", 1), ("created_at", -1)])

    def test_students_cannot_open_the_paged_admin_lists(self) -> None:
        student = _user("user")
        for dependency in (get_management_user, get_payment_admin, get_scholarship_admin, get_admin_user):
            with self.assertRaises(ForbiddenError):
                asyncio.run(dependency(current_user=student))


if __name__ == "__main__":
    unittest.main()
