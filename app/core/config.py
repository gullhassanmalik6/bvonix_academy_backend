from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List
from urllib.parse import unquote, urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/.env, regardless of the directory used to start the server.
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """
    Centralized, environment-based configuration.

    Why: a single Settings object makes config testable, explicit, and easy to
    inject across the codebase without hardcoding secrets.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="BvoniX Academy API", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field(default="bvonix_academy", alias="MONGODB_DB")
    # Development-only. Ignored unless APP_ENV=development. Production refuses this flag.
    mongodb_tls_allow_invalid_certificates: bool = Field(
        default=False,
        alias="MONGODB_TLS_ALLOW_INVALID_CERTIFICATES",
    )

    jwt_secret: str = Field(default="CHANGE_ME", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_issuer: str = Field(default="bvonix-academy", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="bvonix-academy-api", alias="JWT_AUDIENCE")
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="ALLOWED_ORIGINS",
    )

    # Enrollment card: academy name and logo (path under uploads, e.g. /uploads/academy_logo.png)
    academy_name: str = Field(default="BvoniX Academy", alias="ACADEMY_NAME")
    academy_logo_url: str | None = Field(default=None, alias="ACADEMY_LOGO_URL")

    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def apply_railway_mongodb(self):
        """Use Railway's MongoDB plugin variables when MONGODB_URI is not set.

        Railway names the private connection string MONGO_URL. A reference to
        that variable should connect the API without renaming it.
        """
        if not os.getenv("MONGODB_URI"):
            for key in ("MONGO_URL", "MONGO_PUBLIC_URL"):
                candidate = (os.getenv(key) or "").strip()
                if candidate.startswith(("mongodb://", "mongodb+srv://")):
                    self.mongodb_uri = candidate
                    break

        if not os.getenv("MONGODB_DB"):
            database = _database_from_uri(self.mongodb_uri)
            if database:
                self.mongodb_db = database
            else:
                for key in ("MONGO_DATABASE", "MONGO_INITDB_DATABASE"):
                    candidate = (os.getenv(key) or "").strip()
                    if candidate:
                        self.mongodb_db = candidate
                        break
        return self


def _database_from_uri(uri: str) -> str:
    path = unquote(urlparse(uri).path or "").strip("/")
    if not path:
        return ""
    return path.split("/", 1)[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()

