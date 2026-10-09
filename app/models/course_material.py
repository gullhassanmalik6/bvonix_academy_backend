from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class CourseMaterial:
    """
    Domain model for course materials (videos, documents, links).
    
    Stores course content that students can access.
    """

    id: str
    course_id: str  # Reference to Course
    title: str
    description: str | None
    material_type: str  # "video", "document", "link", "assignment_instruction"
    content_url: str | None  # URL to video/document
    file_path: str | None  # Local file path
    file_size: int | None  # File size in bytes
    duration_minutes: int | None  # For videos
    order: int  # Display order
    is_published: bool
    is_required: bool  # Required vs optional material
    created_by: str  # Instructor/Admin user_id
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    archived_by: str | None = None

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
