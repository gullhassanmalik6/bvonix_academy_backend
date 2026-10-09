from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class ForumPost:
    """
    Domain model for forum/discussion posts.
    
    Course discussion forums for Q&A.
    """

    id: str
    course_id: str  # Reference to Course
    parent_post_id: str | None  # None for top-level posts, ID for replies
    author_id: str  # User ID (student/instructor/admin)
    title: str | None  # None for replies
    content: str
    post_type: str  # "question", "answer", "announcement", "discussion"
    is_resolved: bool  # For questions
    is_pinned: bool
    upvotes: int
    downvotes: int
    views: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
