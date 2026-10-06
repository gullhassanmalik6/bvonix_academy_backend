from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.health import live_payload, readiness_response

router = APIRouter(tags=["Health"])


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """The process can serve requests. This does not check dependencies."""
    return live_payload()


@router.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Required dependencies are usable. Database failure is not ready."""
    return await readiness_response()
