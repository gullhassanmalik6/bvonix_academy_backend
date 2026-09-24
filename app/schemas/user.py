from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from app.schemas.common import APIModel


class UserCreate(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    role: str = Field(default="user", pattern="^(user|admin)$")


class UserUpdate(APIModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(user|admin)$")


class UserPublic(APIModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    is_active: bool
    role: str
    created_at: datetime

