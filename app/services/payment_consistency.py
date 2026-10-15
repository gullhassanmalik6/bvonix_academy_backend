"""Read-only comparison of enrollment payment fields and the payments ledger.

These are separate records. Enrollment payment_status uses pending, paid, and
refunded. The ledger uses pending, completed, failed, and refunded. This report
counts disagreements. It does not create payments or change either status.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from pymongo import ASCENDING

_PAGE = 100
_ID_LIMIT = 100


def _valid_id(value: Any) -> bool:
    if isinstance(value, ObjectId):
        return True
    if not isinstance(value, str) or not value:
        return False
    try:
        ObjectId(value)
    except Exception:
        return False
    return True


def _text_id(value: Any) -> str | None:
    if isinstance(value, ObjectId):
        return str(value)
    if _valid_id(value):
        return str(value)
    return None


def _remember(bucket: dict[str, list[str]], key: str, identifier: str | None) -> None:
    if identifier is None:
        return
    found = bucket[key]
    if identifier not in found and len(found) < _ID_LIMIT:
        found.append(identifier)


async def _pages(collection, query: dict[str, Any]) -> list[dict[str, Any]]:
    """Read matching documents in pages. Only the caller chooses which fields to keep."""
    found: list[dict[str, Any]] = []
    skip = 0
    while True:
        docs = await collection.find(query).sort([("_id", ASCENDING)]).skip(skip).limit(_PAGE).to_list(length=_PAGE)
        if not docs:
            break
        found.extend(docs)
        if len(docs) < _PAGE:
            break
        skip += len(docs)
    return found


async def payment_consistency_report(db) -> dict[str, Any]:
    """Count payment disagreements. Identifiers are record ids, capped per class."""
    counts = {
        "enrollment_without_payment": 0,
        "payment_without_enrollment": 0,
        "multiple_payments_for_enrollment": 0,
        "paid_enrollment_pending_or_missing_ledger": 0,
        "completed_ledger_unpaid_enrollment": 0,
        "refunded_ledger_inconsistent_enrollment": 0,
        "invalid_relationship_id": 0,
    }
    ids = {name: [] for name in counts}
    enrollments = await _pages(db["enrollments"], {})
    payments = await _pages(db["payments"], {})
    enrollment_status: dict[str, str] = {}
    for enrollment in enrollments:
        enrollment_id = _text_id(enrollment.get("_id"))
        if enrollment_id is None:
            counts["invalid_relationship_id"] += 1
            continue
        enrollment_status[enrollment_id] = enrollment.get("payment_status") or "pending"

    by_enrollment: dict[str, list[dict[str, Any]]] = {}
    for payment in payments:
        payment_id = _text_id(payment.get("_id"))
        relationship_ok = True
        if payment_id is None or not _valid_id(payment.get("student_id")):
            relationship_ok = False
        course_id = payment.get("course_id")
        if course_id is not None and not _valid_id(course_id):
            relationship_ok = False
        raw_enrollment = payment.get("enrollment_id")
        if raw_enrollment is not None and not _valid_id(raw_enrollment):
            relationship_ok = False
        if not relationship_ok:
            counts["invalid_relationship_id"] += 1
            _remember(ids, "invalid_relationship_id", payment_id)
            continue
        enrollment_id = _text_id(raw_enrollment)
        if enrollment_id is None:
            continue
        if enrollment_id not in enrollment_status:
            counts["payment_without_enrollment"] += 1
            _remember(ids, "payment_without_enrollment", payment_id)
            continue
        by_enrollment.setdefault(enrollment_id, []).append(payment)

    for enrollment_id, status in enrollment_status.items():
        linked = by_enrollment.get(enrollment_id, [])
        if not linked:
            counts["enrollment_without_payment"] += 1
            _remember(ids, "enrollment_without_payment", enrollment_id)
            if status == "paid":
                counts["paid_enrollment_pending_or_missing_ledger"] += 1
                _remember(ids, "paid_enrollment_pending_or_missing_ledger", enrollment_id)
            continue
        if len(linked) > 1:
            counts["multiple_payments_for_enrollment"] += 1
            _remember(ids, "multiple_payments_for_enrollment", enrollment_id)
        ledger_statuses = {item.get("payment_status") or "pending" for item in linked}
        if status == "paid" and "completed" not in ledger_statuses:
            counts["paid_enrollment_pending_or_missing_ledger"] += 1
            _remember(ids, "paid_enrollment_pending_or_missing_ledger", enrollment_id)
        if "completed" in ledger_statuses and status not in ("paid", "refunded"):
            counts["completed_ledger_unpaid_enrollment"] += 1
            _remember(ids, "completed_ledger_unpaid_enrollment", enrollment_id)
        if "refunded" in ledger_statuses and status != "refunded":
            counts["refunded_ledger_inconsistent_enrollment"] += 1
            _remember(ids, "refunded_ledger_inconsistent_enrollment", enrollment_id)
    return {"counts": counts, "ids": ids}
