from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.models.payment import Payment
from app.repositories.archival import with_active
from app.repositories.base import BaseRepository
from app.repositories.listing import sort_pairs, text_clause
from app.utils.helpers import oid_str

PAYMENT_SORTS = {
    "created_at": [("created_at", ASCENDING)],
    "-created_at": [("created_at", DESCENDING)],
    "amount": [("amount", ASCENDING)],
    "-amount": [("amount", DESCENDING)],
    "payment_status": [("payment_status", ASCENDING), ("created_at", DESCENDING)],
}


class PaymentRepository(BaseRepository[Payment]):
    collection_name = "payments"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("student_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("payment_status", ASCENDING)])
        await self.collection.create_index([("transaction_id", ASCENDING)])
        await self.collection.create_index([("created_at", DESCENDING)])
        await self.collection.create_index([("payment_status", ASCENDING), ("created_at", DESCENDING)])
        await self.collection.create_index([("student_id", ASCENDING), ("created_at", DESCENDING)])

    def _to_model(self, doc: dict[str, Any]) -> Payment:
        return Payment(
            id=oid_str(doc["_id"]),
            student_id=oid_str(doc["student_id"]),
            course_id=oid_str(doc["course_id"]) if doc.get("course_id") else None,
            enrollment_id=oid_str(doc["enrollment_id"]) if doc.get("enrollment_id") else None,
            amount=doc.get("amount", 0.0),
            currency=doc.get("currency", "PKR"),
            payment_method=doc.get("payment_method", "cash"),
            payment_status=doc.get("payment_status", "pending"),
            transaction_id=doc.get("transaction_id"),
            invoice_number=doc.get("invoice_number"),
            invoice_url=doc.get("invoice_url"),
            payment_date=doc.get("payment_date"),
            due_date=doc.get("due_date"),
            scholarship_discount=doc.get("scholarship_discount", 0.0),
            notes=doc.get("notes"),
            created_by=oid_str(doc["created_by"]) if doc.get("created_by") else None,
            created_at=doc.get("created_at") or datetime.now(timezone.utc),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
            archived_at=doc.get("archived_at"),
            archived_by=doc.get("archived_by"),
            audit_pending=doc.get("audit_pending") or None,
        )

    async def list_page(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        student_id: str | None = None,
        course_id: str | None = None,
        payment_status: str | None = None,
        q: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Payment], int]:
        """Filter, search, sort, and page payments in MongoDB."""
        query: dict[str, Any] = {}
        if student_id:
            try:
                query["student_id"] = ObjectId(student_id)
            except Exception:
                return [], 0
        if course_id:
            try:
                query["course_id"] = ObjectId(course_id)
            except Exception:
                return [], 0
        if payment_status:
            query["payment_status"] = payment_status
        if q and q.strip():
            query["$or"] = text_clause(
                q,
                ("invoice_number", "transaction_id", "notes", "payment_method"),
            )["$or"]
        return await self.find_page(
            query,
            skip=skip,
            limit=limit,
            sort=sort_pairs(sort, allowed=PAYMENT_SORTS, default="-created_at"),
        )

    async def get_by_id(self, payment_id: str) -> Payment | None:
        """Load one active payment. Archived rows stay out of operational reads."""
        try:
            oid = ObjectId(payment_id)
        except Exception:
            return None
        doc = await self.collection.find_one(with_active({"_id": oid}))
        return self._to_model(doc) if doc else None

    async def get_by_student(self, student_id: str) -> list[Payment]:
        """Get all payments for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        
        return await self.collect(
            {"student_id": student_oid},
            sort=[("created_at", DESCENDING)],
        )

    async def page_for_student(
        self,
        student_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Payment], int]:
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return [], 0
        return await self.find_page(
            {"student_id": student_oid},
            skip=skip,
            limit=limit,
            sort=[("created_at", DESCENDING)],
        )

    async def get_by_course(self, course_id: str) -> list[Payment]:
        """Get all payments for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        return await self.collect(
            {"course_id": course_oid},
            sort=[("created_at", DESCENDING)],
        )

    async def create_payment(
        self,
        *,
        student_id: str,
        course_id: str | None,
        enrollment_id: str | None,
        amount: float,
        currency: str,
        payment_method: str,
        due_date: datetime | None,
        scholarship_discount: float,
        notes: str | None,
        created_by: str | None,
    ) -> Payment:
        now = datetime.now(timezone.utc)
        try:
            student_oid = ObjectId(student_id)
            course_oid = ObjectId(course_id) if course_id else None
            enrollment_oid = ObjectId(enrollment_id) if enrollment_id else None
            created_by_oid = ObjectId(created_by) if created_by else None
        except Exception:
            raise ValueError("Invalid IDs")
        
        # Generate invoice number
        invoice_number = f"INV-{now.strftime('%Y%m%d')}-{str(now.timestamp()).replace('.', '')[-6:]}"
        
        payload = {
            "student_id": student_oid,
            "course_id": course_oid,
            "enrollment_id": enrollment_oid,
            "amount": amount,
            "currency": currency,
            "payment_method": payment_method,
            "payment_status": "pending",
            "transaction_id": None,
            "invoice_number": invoice_number,
            "invoice_url": None,
            "payment_date": None,
            "due_date": due_date,
            "scholarship_discount": scholarship_discount,
            "notes": notes,
            "created_by": created_by_oid,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)
