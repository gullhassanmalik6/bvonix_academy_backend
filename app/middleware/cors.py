from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings


def setup_cors(app: FastAPI) -> None:
    """Setup CORS middleware for the application."""
    settings = get_settings()
    origins = settings.allowed_origins_list()
    
    # Default origins for development
    if not origins:
        origins = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

