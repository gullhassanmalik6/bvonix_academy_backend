from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class ForumPostCreate(APIModel):
    course_id: str
    parent_post_id: str | None = None  # None for new question, ID for reply
    title: str | None = Field(default=None, min_length=1, max_length=200)  # Required for questions
    content: str = Field(..., min_length=1, max_length=10000)
    post_type: str = Field(default="question", pattern="^(question|answer|announcement|discussion)$")


class ForumPostUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    is_resolved: bool | None = None
    is_pinned: bool | None = None


class ForumPostPublic(APIModel):
    id: str
    course_id: str
    parent_post_id: str | None
    author_id: str
    author_name: str | None  # Populated from user
    title: str | None
    content: str
    post_type: str
    is_resolved: bool
    is_pinned: bool
    upvotes: int
    downvotes: int
    views: int
    reply_count: int  # Number of replies
    created_at: datetime
    updated_at: datetime


class ForumVote(APIModel):
    """Schema for voting on forum posts."""
    vote_type: str = Field(pattern="^(upvote|downvote|remove)$")
