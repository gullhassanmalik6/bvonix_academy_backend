from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class AuthSession:
    """Server-side refresh session. The raw refresh secret is never stored."""

    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None
    replaced_by: str | None
    created_at: datetime

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
