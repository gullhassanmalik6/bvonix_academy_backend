from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

from app.models.payment import Payment
from app.repositories.base import BaseRepository
from app.utils.helpers import oid_str


class PaymentRepository(BaseRepository[Payment]):
    collection_name = "payments"

    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("student_id", ASCENDING)])
        await self.collection.create_index([("course_id", ASCENDING)])
        await self.collection.create_index([("payment_status", ASCENDING)])
        await self.collection.create_index([("transaction_id", ASCENDING)])

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
        )

    async def get_by_student(self, student_id: str) -> list[Payment]:
        """Get all payments for a student."""
        try:
            student_oid = ObjectId(student_id)
        except Exception:
            return []
        
        cursor = self.collection.find({"student_id": student_oid}).sort("created_at", -1)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

    async def get_by_course(self, course_id: str) -> list[Payment]:
        """Get all payments for a course."""
        try:
            course_oid = ObjectId(course_id)
        except Exception:
            return []
        
        cursor = self.collection.find({"course_id": course_oid}).sort("created_at", -1)
        docs = await cursor.to_list(length=1000)
        return [self._to_model(doc) for doc in docs]

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
