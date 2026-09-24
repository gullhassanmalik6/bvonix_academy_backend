from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized, environment-based configuration.

    Why: a single Settings object makes config testable, explicit, and easy to
    inject across the codebase without hardcoding secrets.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="BvoniX Academy API", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field(default="bvonix_academy", alias="MONGODB_DB")

    jwt_secret: str = Field(default="CHANGE_ME", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    allowed_origins: str = Field(default="http://localhost:5173", alias="ALLOWED_ORIGINS")
    
    admin_secret: str | None = Field(default=None, alias="ADMIN_SECRET")

    # Enrollment card: academy name and logo (path under uploads, e.g. /uploads/academy_logo.png)
    academy_name: str = Field(default="BvoniX Academy", alias="ACADEMY_NAME")
    academy_logo_url: str | None = Field(default=None, alias="ACADEMY_LOGO_URL")

    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

