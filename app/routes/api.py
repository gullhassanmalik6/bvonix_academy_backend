from __future__ import annotations

from fastapi import APIRouter

from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.courses import router as courses_router
from app.routes.instructors import router as instructors_router
from app.routes.lms import router as lms_router
from app.routes.notifications import router as notifications_router
from app.routes.public import router as public_router
from app.routes.search import router as search_router
from app.routes.settings import router as settings_router
from app.routes.site_settings import router as site_settings_router
from app.routes.students import router as students_router
from app.routes.cards import router as cards_router
from app.routes.uploads import router as uploads_router
from app.routes.users import router as users_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["Auth"])
router.include_router(users_router, prefix="/users", tags=["Users"])
router.include_router(courses_router, prefix="/courses", tags=["Courses"])
router.include_router(instructors_router, prefix="/instructors", tags=["Instructors"])
router.include_router(students_router, prefix="/students", tags=["Students"])
router.include_router(admin_router, prefix="/admin", tags=["Admin"])
router.include_router(lms_router, prefix="/lms", tags=["LMS"])
router.include_router(cards_router, prefix="/cards", tags=["Enrollment Cards"])
router.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
router.include_router(public_router, prefix="/public", tags=["Public"])
router.include_router(uploads_router, prefix="/uploads", tags=["Uploads"])
router.include_router(search_router, prefix="/search", tags=["Search"])
router.include_router(settings_router, prefix="/settings", tags=["Settings"])
router.include_router(site_settings_router, tags=["Site Settings"])


@router.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}

