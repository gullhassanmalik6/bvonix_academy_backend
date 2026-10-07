"""Request-scoped actor and request details for audit records."""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request

_actor: ContextVar[dict | None] = ContextVar("audit_actor", default=None)
_request: ContextVar[dict] = ContextVar("audit_request", default={})


def set_audit_actor(actor) -> None:
    if actor is None:
        _actor.set(None)
        return
    _actor.set({"id": getattr(actor, "id", None), "role": getattr(actor, "role", None)})


def set_audit_request(request: Request | None) -> None:
    if request is None:
        return
    client = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    _request.set(
        {
            "method": request.method,
            "path": request.url.path,
            "ip": client,
            "user_agent": user_agent[:300] if user_agent else None,
        }
    )


def current_actor() -> dict | None:
    return _actor.get()


def current_request_context() -> dict:
    return dict(_request.get())


async def capture_audit_request(request: Request):
    """Keep the current request path available while a route runs."""
    previous = _request.set(
        {
            "method": request.method,
            "path": request.url.path,
            "ip": request.client.host if request.client else None,
            "user_agent": (request.headers.get("user-agent") or "")[:300] or None,
        }
    )
    try:
        yield
    finally:
        _request.reset(previous)
