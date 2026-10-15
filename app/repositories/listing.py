"""Bounds and query pieces for MongoDB list endpoints.

HTTP list routes use skip and limit. limit is at least 1 and at most
MAX_PAGE_SIZE (100). skip below 0 becomes 0. A page and its total must use
the same filter. Sort always ends with _id so a page cannot skip or repeat
rows when another field ties. Relationship reads that must return every
matching row walk these pages instead of stopping at a fixed cap.
"""

from __future__ import annotations

import re
from typing import Any

MAX_PAGE_SIZE = 100


def clamp_skip(skip: int) -> int:
    """Negative skips become 0. A missing value, including an unbound FastAPI default, becomes 0."""
    if isinstance(skip, bool) or not isinstance(skip, int):
        return 0
    return max(0, skip)


def clamp_limit(limit: int) -> int:
    """Page size is at least 1 and at most MAX_PAGE_SIZE. A missing value uses the maximum."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        return MAX_PAGE_SIZE
    if limit < 1:
        return 1
    if limit > MAX_PAGE_SIZE:
        return MAX_PAGE_SIZE
    return limit


def stable_sort(sort: list[tuple[str, int]] | None) -> list[tuple[str, int]]:
    """Keep page order stable by appending the unique document id."""
    pairs = list(sort or [])
    if not any(name == "_id" for name, _direction in pairs):
        pairs.append(("_id", 1))
    return pairs


def text_clause(term: str, fields: tuple[str, ...]) -> dict[str, Any]:
    """Case-insensitive substring match. User input is escaped."""
    regex = {"$regex": re.escape(term.strip()), "$options": "i"}
    return {"$or": [{field: regex} for field in fields]}


def sort_pairs(
    sort: str | None,
    *,
    allowed: dict[str, list[tuple[str, int]]],
    default: str,
) -> list[tuple[str, int]]:
    choice = sort if sort in allowed else default
    return allowed[choice]
