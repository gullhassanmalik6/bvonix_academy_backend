"""
Global exception handlers for consistent error responses.

Why: Centralized error handling ensures all exceptions return
consistent JSON responses, making debugging and frontend integration easier.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError

from app.utils.exceptions import AppError

logger = logging.getLogger(__name__)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle custom application errors."""
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "detail": exc.detail,
            "status_code": exc.status_code,
        },
    )
    # Add CORS headers
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic validation errors."""
    errors = []
    for error in exc.errors():
        field = " -> ".join(str(loc) for loc in error["loc"])
        errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"],
        })
    
    response = JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "message": "Validation error",
            "detail": "Validation error",
            "errors": errors,
            "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
        },
    )
    # Add CORS headers
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


async def duplicate_key_error_handler(request: Request, exc: DuplicateKeyError) -> JSONResponse:
    """Handle MongoDB duplicate key errors (e.g., duplicate email)."""
    logger.warning(f"Duplicate key error: {exc}")
    
    # Extract field name from error message
    error_msg = str(exc)
    if "email" in error_msg.lower():
        message = "Email already exists"
    else:
        message = "Duplicate entry"
    
    response = JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": True,
            "message": message,
            "detail": message,
            "status_code": status.HTTP_409_CONFLICT,
        },
    )
    # Add CORS headers
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.exception(f"Unhandled exception: {exc}", exc_info=exc)
    
    # Include more details in development
    import os
    error_detail = str(exc) if os.getenv("APP_ENV", "development") == "development" else "Internal server error"
    
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "message": error_detail,
            "detail": error_detail,
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
        },
    )
    # Add CORS headers even on errors
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response