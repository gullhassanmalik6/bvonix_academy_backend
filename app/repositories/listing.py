"""Bounds and query pieces for MongoDB list endpoints."""

from __future__ import annotations

import re
from typing import Any

MAX_PAGE_SIZE = 100


def clamp_skip(skip: int) -> int:
    return max(0, skip)


def clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_PAGE_SIZE:
        return MAX_PAGE_SIZE
    return limit


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
