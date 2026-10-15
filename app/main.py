from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.health import ensure_startup_database
from app.core.security_config import ensure_production_origins, ensure_production_secret
from app.db.index_status import note_required_index_failure, reset_required_index_status
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
from app.repositories.attendance_claim_repository import AttendanceClaimRepository
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
    try:
        ensure_production_secret(
            app_env=settings.app_env,
            jwt_secret=settings.jwt_secret,
            jwt_algorithm=settings.jwt_algorithm,
        )
        ensure_production_origins(
            app_env=settings.app_env,
            allowed_origins=settings.allowed_origins,
        )
    except RuntimeError:
        logger.error("Production startup failed because security configuration is not usable.")
        raise
    available = False
    try:
        available = await mongodb.connect()
    except Exception:
        logger.error("MongoDB client could not be created.")
    try:
        ensure_startup_database(settings.app_env, available)
    except RuntimeError:
        logger.error("Production startup failed because MongoDB is unavailable.")
        raise
    if available:
        logger.info("MongoDB connection established")
        import asyncio
        reset_required_index_status()
        index_tasks = (
            (UserRepository, True),
            (CourseRepository, False),
            (InstructorRepository, True),
            (StudentRepository, True),
            (EnrollmentRepository, True),
            (ResultRepository, False),
            (AttendanceRepository, True),
            (AttendanceClaimRepository, True),
            (AttendanceCorrectionRepository, True),
            (CertificateRepository, True),
            (ScholarshipRepository, False),
            (CourseMaterialRepository, False),
            (AssignmentRepository, False),
            (AssignmentSubmissionRepository, True),
            (LiveSessionRepository, False),
            (AnnouncementRepository, False),
            (PaymentRepository, False),
            (ForumPostRepository, False),
            (NotificationRepository, False),
            (CalendarEventRepository, False),
            (AuditLogRepository, True),
            (SessionRepository, True),
        )
        results = await asyncio.gather(
            *(repository(mongodb.db).ensure_indexes() for repository, _required in index_tasks),
            return_exceptions=True,
        )
        for (_repository, required), result in zip(index_tasks, results):
            if required and isinstance(result, Exception):
                note_required_index_failure()
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            logger.error(
                "MongoDB index creation failed for %s collection(s).",
                len(failures),
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
    
    # Public site assets only. Receipts, profile images, and enrollment
    # cards are served by the authorized download route.
    from pathlib import Path
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    uploads_dir = Path("uploads")
    uploads_dir.mkdir(exist_ok=True)
    for public_name in (
        "logos",
        "hero_icons",
        "community_images",
        "benefit_icons",
        "subject_icons",
        "testimonial_avatars",
        "course_images",
    ):
        public_dir = uploads_dir / public_name
        public_dir.mkdir(exist_ok=True)
        app.mount(
            f"/uploads/{public_name}",
            StaticFiles(directory=str(public_dir)),
            name=f"uploads_{public_name}",
        )

    academy_logo = uploads_dir / "academy_logo.png"

    @app.get("/uploads/academy_logo.png", include_in_schema=False)
    async def public_academy_logo() -> FileResponse:
        if not academy_logo.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(academy_logo)
    
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

