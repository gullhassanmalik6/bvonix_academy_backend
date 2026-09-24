from __future__ import annotations

from pydantic import EmailStr, Field

from app.schemas.common import APIModel


class Token(APIModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

