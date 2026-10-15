"""Read-only comparison of students.enrolled_courses and enrollment rows.

The enrollment collection is the registration record. The student course list
is a compatibility cache of non-cancelled course ids. This report counts
disagreements. It does not create enrollments, cancel them, or rewrite the list.
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


async def registration_consistency_report(db) -> dict[str, Any]:
    """Count registration-list disagreements. Identifiers are record ids, capped per class."""
    counts = {
        "students": 0,
        "enrollments": 0,
        "list_entry_without_registration": 0,
        "registration_missing_from_list": 0,
        "cancelled_registration_still_listed": 0,
        "duplicate_registration": 0,
        "invalid_relationship_id": 0,
    }
    ids = {name: [] for name in counts if name not in ("students", "enrollments")}
    students = await _pages(db["students"], {})
    enrollments = await _pages(db["enrollments"], {})
    counts["students"] = len(students)
    counts["enrollments"] = len(enrollments)

    listed: dict[str, set[str]] = {}
    for student in students:
        student_id = _text_id(student.get("_id"))
        if student_id is None:
            counts["invalid_relationship_id"] += 1
            continue
        courses: set[str] = set()
        for raw_course in student.get("enrolled_courses") or []:
            course_id = _text_id(raw_course)
            if course_id is None:
                counts["invalid_relationship_id"] += 1
                _remember(ids, "invalid_relationship_id", student_id)
                continue
            courses.add(course_id)
        listed[student_id] = courses

    registered: dict[tuple[str, str], list[str]] = {}
    cancelled: list[tuple[str, str, str]] = []
    for enrollment in enrollments:
        enrollment_id = _text_id(enrollment.get("_id"))
        student_id = _text_id(enrollment.get("student_id"))
        course_id = _text_id(enrollment.get("course_id"))
        if enrollment_id is None or student_id is None or course_id is None:
            counts["invalid_relationship_id"] += 1
            _remember(ids, "invalid_relationship_id", enrollment_id)
            continue
        if enrollment.get("status") == "cancelled":
            cancelled.append((enrollment_id, student_id, course_id))
            continue
        registered.setdefault((student_id, course_id), []).append(enrollment_id)

    for (student_id, course_id), enrollment_ids in registered.items():
        if len(enrollment_ids) > 1:
            counts["duplicate_registration"] += 1
            for enrollment_id in enrollment_ids:
                _remember(ids, "duplicate_registration", enrollment_id)
        if course_id not in listed.get(student_id, set()):
            counts["registration_missing_from_list"] += len(enrollment_ids)
            for enrollment_id in enrollment_ids:
                _remember(ids, "registration_missing_from_list", enrollment_id)

    for enrollment_id, student_id, course_id in cancelled:
        if course_id in listed.get(student_id, set()) and (student_id, course_id) not in registered:
            counts["cancelled_registration_still_listed"] += 1
            _remember(ids, "cancelled_registration_still_listed", enrollment_id)

    for student_id, courses in listed.items():
        for course_id in courses:
            if (student_id, course_id) not in registered:
                counts["list_entry_without_registration"] += 1
                _remember(ids, "list_entry_without_registration", student_id)

    return {"counts": counts, "ids": ids}


def _stored_course_ids(raw_courses: Any) -> tuple[list[str], bool]:
    texts: list[str] = []
    invalid = False
    for raw_course in raw_courses or []:
        course_id = _text_id(raw_course)
        if course_id is None:
            invalid = True
            continue
        texts.append(course_id)
    return texts, invalid


async def reconcile_registration_lists(db, *, write: bool) -> dict[str, Any]:
    """Rebuild compatibility lists from non-cancelled enrollments.

    An enrollment with no status is treated as not cancelled, matching
    registration_course_ids. Invalid ids are counted and omitted. This does
    not create, cancel, or reactivate an enrollment, and it does not create a
    course. Archived students are included. Only enrolled_courses and
    updated_at are written. A failed student is counted and later students
    are still attempted. completed is false when any student write failed.
    """
    from app.repositories.student_repository import StudentRepository

    students = await _pages(db["students"], {})
    enrollments = await _pages(db["enrollments"], {})
    known_students = {_text_id(student.get("_id")) for student in students}
    known_students.discard(None)
    desired: dict[str, set[str]] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    invalid_relationships = 0
    enrollments_without_student = 0
    for enrollment in enrollments:
        student_id = _text_id(enrollment.get("student_id"))
        course_id = _text_id(enrollment.get("course_id"))
        if student_id is None or course_id is None:
            invalid_relationships += 1
            continue
        if student_id not in known_students:
            enrollments_without_student += 1
            continue
        if enrollment.get("status") == "cancelled":
            continue
        desired.setdefault(student_id, set()).add(course_id)
        pair = (student_id, course_id)
        pair_counts[pair] = pair_counts.get(pair, 0) + 1

    ordered = {student_id: sorted(course_ids) for student_id, course_ids in desired.items()}
    duplicate_registration = sum(1 for count in pair_counts.values() if count > 1)
    counts = {
        "students": len(students),
        "enrollments": len(enrollments),
        "unchanged": 0,
        "would_update": 0,
        "updated": 0,
        "archived_students": 0,
        "archived_students_would_update": 0,
        "archived_students_updated": 0,
        "invalid_relationship_id": invalid_relationships,
        "enrollment_without_student": enrollments_without_student,
        "duplicate_registration": duplicate_registration,
        "failed": 0,
    }
    failed_student_ids: list[str] = []
    repository = StudentRepository(db)
    for student in students:
        student_id = _text_id(student.get("_id"))
        archived = student.get("archived_at") is not None
        if archived:
            counts["archived_students"] += 1
        if student_id is None:
            counts["invalid_relationship_id"] += 1
            counts["failed"] += 1
            continue
        current, invalid_list = _stored_course_ids(student.get("enrolled_courses"))
        target = ordered.get(student_id, [])
        if not invalid_list and current == target:
            counts["unchanged"] += 1
            continue
        if not write:
            counts["would_update"] += 1
            if archived:
                counts["archived_students_would_update"] += 1
            continue
        try:
            saved = await repository.set_enrolled_courses(student_id, target, include_archived=True)
        except Exception:
            saved = None
        if saved is None:
            counts["failed"] += 1
            _remember({"failed": failed_student_ids}, "failed", student_id)
            continue
        counts["updated"] += 1
        if archived:
            counts["archived_students_updated"] += 1
    return {
        "write": write,
        "completed": counts["failed"] == 0,
        "counts": counts,
        "failed_student_ids": failed_student_ids,
    }
