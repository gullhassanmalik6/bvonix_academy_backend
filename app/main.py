from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.health import ensure_startup_database
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
from app.repositories.attendance_correction_repository import AttendanceCorrectionRepository
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
from app.repositories.session_repository import SessionRepository
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
    
    settings = get_settings()
    available = False
    try:
        available = await mongodb.connect()
    except Exception as exc:
        logger.error("MongoDB client could not be created: %s", exc)
    try:
        ensure_startup_database(settings.app_env, available)
    except RuntimeError:
        logger.error("Production startup failed because MongoDB is unavailable.")
        raise
    if available:
        logger.info("MongoDB connection established")
        import asyncio
        results = await asyncio.gather(
            UserRepository(mongodb.db).ensure_indexes(),
            CourseRepository(mongodb.db).ensure_indexes(),
            InstructorRepository(mongodb.db).ensure_indexes(),
            StudentRepository(mongodb.db).ensure_indexes(),
            EnrollmentRepository(mongodb.db).ensure_indexes(),
            ResultRepository(mongodb.db).ensure_indexes(),
            AttendanceRepository(mongodb.db).ensure_indexes(),
            AttendanceCorrectionRepository(mongodb.db).ensure_indexes(),
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
            SessionRepository(mongodb.db).ensure_indexes(),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            logger.error(
                "MongoDB index creation failed for %s collection(s). First error: %s",
                len(failures),
                failures[0],
            )
        else:
            logger.info("MongoDB indexes created successfully")
    else:
        logger.error("MongoDB did not respond during startup.")
        logger.warning(
            "Continuing startup because APP_ENV=%s does not require MongoDB at boot. "
            "Readiness will report the database as down.",
            settings.app_env,
        )
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

