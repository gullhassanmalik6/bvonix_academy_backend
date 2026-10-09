"""Resolve instructor display names without replacing instructor ids."""

from __future__ import annotations

from app.repositories.archival import record_is_active

MISSING_INSTRUCTOR = "Instructor not assigned"


def display_name(user) -> str | None:
    if user is None or not record_is_active(user):
        return None
    name = (getattr(user, "full_name", None) or "").strip()
    return name or None


async def names_by_instructor_id(instructor_ids: list[str], instructors, users) -> dict[str, str | None]:
    """Map each instructor profile id to the linked user's name."""
    unique = [item for item in dict.fromkeys(instructor_ids) if item]
    if not hasattr(instructors, "load_by_ids") or not hasattr(users, "load_by_ids"):
        return {item: None for item in unique}
    records = await instructors.load_by_ids(unique) if unique else {}
    user_ids = [
        record.user_id
        for record in records.values()
        if record is not None and record_is_active(record) and getattr(record, "user_id", None)
    ]
    people = await users.load_by_ids(user_ids) if user_ids else {}
    resolved: dict[str, str | None] = {}
    for instructor_id in unique:
        record = records.get(instructor_id)
        if record is None or not record_is_active(record):
            resolved[instructor_id] = None
            continue
        resolved[instructor_id] = display_name(people.get(record.user_id))
    return resolved
