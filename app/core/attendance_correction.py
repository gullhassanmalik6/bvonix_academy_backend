"""Attendance correction lifecycle.

requested → under_review → approved or rejected.
A final decision cannot be skipped or reopened.
"""

from __future__ import annotations

from app.utils.exceptions import ConflictError

REQUESTED = "requested"
UNDER_REVIEW = "under_review"
APPROVED = "approved"
REJECTED = "rejected"

OPEN_STATES = frozenset({REQUESTED, UNDER_REVIEW})
FINAL_STATES = frozenset({APPROVED, REJECTED})
ATTENDANCE_STATUSES = frozenset({"present", "absent", "late", "excused"})

_ALLOWED = {
    REQUESTED: frozenset({UNDER_REVIEW}),
    UNDER_REVIEW: frozenset({APPROVED, REJECTED}),
}


def assert_correction_transition(current: str, target: str) -> None:
    """Reject any move that skips review or leaves a finished request."""
    if target not in _ALLOWED.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move an attendance correction from {current} to {target}"
        )
