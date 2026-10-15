"""Required MongoDB index status for readiness.

Performance indexes may fail without changing readiness. A failed unique or
other integrity index must not be reported as ready. Startup still continues
so a development process can boot; production readiness is the gate.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_failed = 0


def reset_required_index_status() -> None:
    global _failed
    _failed = 0


def required_indexes_ready() -> bool:
    return _failed == 0


def note_required_index_failure() -> None:
    global _failed
    _failed += 1


async def ensure_required_index(collection, keys, **kwargs) -> None:
    """Create one integrity index and remember a failure for readiness."""
    global _failed
    try:
        await collection.create_index(keys, **kwargs)
    except Exception:
        _failed += 1
        logger.error("A required MongoDB index was not created.")
        raise
