from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class LiveSessionCreate(APIModel):
    course_id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    session_type: str = Field(pattern="^(online|physical|hybrid)$")
    start_time: datetime
    end_time: datetime
    meeting_link: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)
    instructor_id: str
    max_participants: int | None = Field(default=None, ge=1)


class LiveSessionUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    start_time: datetime | None = None
    end_time: datetime | None = None
    meeting_link: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, pattern="^(scheduled|ongoing|completed|cancelled)$")
    recording_url: str | None = Field(default=None, max_length=500)
    is_recorded: bool | None = None


class LiveSessionPublic(APIModel):
    id: str
    course_id: str
    title: str
    description: str | None
    session_type: str
    start_time: datetime
    end_time: datetime
    meeting_link: str | None
    location: str | None
    instructor_id: str
    max_participants: int | None
    recording_url: str | None
    is_recorded: bool
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
