"""Counts derived from stored attendance and certificate records."""

from __future__ import annotations

ATTENDED_STATUSES = frozenset({"present", "late", "excused"})


def attendance_summary(counts: dict[str, int]) -> dict[str, int | float | None]:
    """Rate is attended marks divided by every stored mark. Zero marks is not a rate."""
    total = sum(int(count) for count in counts.values())
    attended = sum(int(count) for status, count in counts.items() if status in ATTENDED_STATUSES)
    if total == 0:
        return {"total": 0, "attended": 0, "rate": None}
    rate = round(attended / total * 1000) / 10
    return {"total": total, "attended": attended, "rate": rate}
