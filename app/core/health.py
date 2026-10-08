"""Process liveness and dependency readiness."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.mongodb import mongodb

UPLOADS_DIR = Path("uploads")


def live_payload() -> dict[str, str]:
    return {"status": "alive", "version": get_settings().app_version}


def startup_requires_database(app_env: str) -> bool:
    """Production must not boot without MongoDB. Development and testing may."""
    return (app_env or "").strip().lower() in {"production", "prod"}


def ensure_startup_database(app_env: str, available: bool) -> None:
    """Raise when production is starting without a reachable database."""
    if available or not startup_requires_database(app_env):
        return
    raise RuntimeError(
        "Production startup failed because MongoDB is unavailable. "
        "The database must answer before the application serves traffic."
    )


async def check_database() -> bool:
    try:
        return await mongodb.ping()
    except Exception:
        return False


def check_storage(path: Path = UPLOADS_DIR) -> bool:
    return path.is_dir() and os.access(path, os.W_OK)


async def readiness_response(
    *,
    database_ok: bool | None = None,
    storage_ok: bool | None = None,
) -> JSONResponse:
    if database_ok is None:
        database_ok = await check_database()
    if storage_ok is None:
        storage_ok = check_storage()
    ready = database_ok and storage_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "version": get_settings().app_version,
            "checks": {
                "database": {"status": "up" if database_ok else "down"},
                "storage": {"status": "up" if storage_ok else "down"},
            },
        },
    )
