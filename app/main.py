from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.db.mongodb import mongodb
from app.middleware.cors import setup_cors
from app.middleware.exception_handler import (
    app_error_handler,
    duplicate_key_error_handler,
    generic_exception_handler,
    validation_error_handler,
)
from app.repositories.announcement_repository import AnnouncementRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.assignment_repository import AssignmentRepository, AssignmentSubmissionRepository
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.certificate_repository import CertificateRepository
from app.repositories.course_material_repository import CourseMaterialRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.forum_repository import ForumPostRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.calendar_event_repository import CalendarEventRepository
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.scholarship_repository import ScholarshipRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.routes.api import router as api_router
from app.routes.health import router as health_router
from app.utils.exceptions import AppError
from app.utils.logging_config import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: connect/disconnect MongoDB and create indexes."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        await mongodb.connect()
        logger.info("MongoDB connection established")
        
        # Create indexes on startup for all collections.
        # Use asyncio.gather for parallel execution to speed up startup
        import asyncio
        try:
            await asyncio.gather(
                UserRepository(mongodb.db).ensure_indexes(),
                CourseRepository(mongodb.db).ensure_indexes(),
                InstructorRepository(mongodb.db).ensure_indexes(),
                StudentRepository(mongodb.db).ensure_indexes(),
                EnrollmentRepository(mongodb.db).ensure_indexes(),
                ResultRepository(mongodb.db).ensure_indexes(),
                AttendanceRepository(mongodb.db).ensure_indexes(),
                CertificateRepository(mongodb.db).ensure_indexes(),
                ScholarshipRepository(mongodb.db).ensure_indexes(),
                CourseMaterialRepository(mongodb.db).ensure_indexes(),
                AssignmentRepository(mongodb.db).ensure_indexes(),
                AssignmentSubmissionRepository(mongodb.db).ensure_indexes(),
                LiveSessionRepository(mongodb.db).ensure_indexes(),
                AnnouncementRepository(mongodb.db).ensure_indexes(),
                PaymentRepository(mongodb.db).ensure_indexes(),
                ForumPostRepository(mongodb.db).ensure_indexes(),
                NotificationRepository(mongodb.db).ensure_indexes(),
                CalendarEventRepository(mongodb.db).ensure_indexes(),
                AuditLogRepository(mongodb.db).ensure_indexes(),
                return_exceptions=True  # Don't fail if one index creation fails
            )
            logger.info("MongoDB indexes created successfully")
        except Exception as idx_error:
            logger.warning(f"Some index creation failed: {idx_error}")
    except RuntimeError as e:
        # This is the "MongoDB not initialized" error
        logger.error(f"MongoDB initialization error: {e}")
        logger.warning("Server starting but MongoDB may not be fully connected. Some features may not work.")
    except Exception as e:
        # Log error but don't prevent server from starting
        logger.error(f"MongoDB connection/index creation error: {e}")
        logger.warning("Server starting without MongoDB connection. Some features may not work.")
    yield
    try:
        await mongodb.disconnect()
    except Exception:
        pass  # Ignore disconnect errors


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Setup logging first
    setup_logging()
    
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="BvoniX Academy API - Backend for the academy platform",
        version=settings.app_version,
        lifespan=lifespan,
    )
    
    # Setup CORS
    setup_cors(app)
    
    # Register exception handlers
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(DuplicateKeyError, duplicate_key_error_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    
    # Include routers. Liveness and readiness stay at /health/* .
    # /api/health remains the existing status check.
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    
    # Mount static files for uploads
    try:
        from pathlib import Path
        uploads_dir = Path("uploads")
        uploads_dir.mkdir(exist_ok=True)
        app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
    except Exception:
        pass  # Ignore if directory doesn't exist yet
    
    # Root endpoint
    @app.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        """Root endpoint with API information."""
        return {
            "message": "Welcome to BvoniX Academy API",
            "version": settings.app_version,
            "docs": "/docs",
            "health": f"{settings.api_prefix}/health",
        }
    
    return app


app = create_app()

