"""
File upload routes for profile images and payment receipts.

Private files are downloaded through an authorized route. Public site
assets stay on the static mounts in app.main.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path
from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from app.core.admin import get_management_user
from app.core.auth import get_current_user
from app.core.dependencies import get_enrollment_repository, get_payment_repository, get_student_repository
from app.core.permissions import is_management
from app.models.user import User
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.student_repository import StudentRepository
from app.utils.exceptions import AppError, ForbiddenError, NotFoundError

router = APIRouter()

# Create upload directories
UPLOAD_BASE = Path("uploads")
PROFILE_IMAGES_DIR = UPLOAD_BASE / "profile_images"
PAYMENT_RECEIPTS_DIR = UPLOAD_BASE / "payment_receipts"
COURSE_IMAGES_DIR = UPLOAD_BASE / "course_images"

PROFILE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PAYMENT_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
COURSE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Allowed file types
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}

# Max file sizes (5MB for images, 10MB for receipts)
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10MB
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
_PRIVATE_FILES = {
    "payment-receipts": ("payment_receipts", "payment_receipt_url", {".jpg", ".jpeg", ".png", ".pdf"}),
    "profile-images": ("profile_images", "profile_image_url", {".jpg", ".jpeg", ".png", ".webp"}),
    "enrollment-cards": ("enrollment_cards", "enrollment_card_url", {".pdf"}),
}


def image_suffix(contents: bytes) -> str | None:
    """Trust the file bytes, not the filename."""
    if contents.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(contents) >= 12 and contents.startswith(b"RIFF") and contents[8:12] == b"WEBP":
        return ".webp"
    return None


def _stored_suffix(filename: str | None, allowed: set[str], default: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in allowed or ".." in suffix:
        return default
    return suffix


def _private_file(kind: str, filename: str) -> tuple[Path, str, str]:
    if kind not in _PRIVATE_FILES or not _SAFE_NAME.fullmatch(filename) or ".." in filename:
        raise NotFoundError("File not found")
    directory, field, _allowed = _PRIVATE_FILES[kind]
    base = (UPLOAD_BASE / directory).resolve()
    candidate = (base / filename).resolve()
    if candidate.parent != base:
        raise NotFoundError("File not found")
    return candidate, field, f"/uploads/{directory}/{filename}"


@router.post("/profile-image", status_code=status.HTTP_201_CREATED)
async def upload_profile_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Upload passport size profile image for enrollment card."""
    # Validate file type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")
    
    # Read file content
    contents = await file.read()
    
    # Validate file size
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE / 1024 / 1024}MB")
    
    # Generate unique filename
    file_extension = _stored_suffix(file.filename, {".jpg", ".jpeg", ".png", ".webp"}, ".jpg")
    unique_filename = f"{secrets.token_hex(16)}{file_extension}"
    file_path = PROFILE_IMAGES_DIR / unique_filename
    
    # Save file
    with open(file_path, "wb") as f:
        f.write(contents)
    
    # Return relative URL
    relative_url = f"/uploads/profile_images/{unique_filename}"
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"url": relative_url, "filename": unique_filename}
    )


@router.post("/payment-receipt", status_code=status.HTTP_201_CREATED)
async def upload_payment_receipt(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Upload payment receipt for enrollment verification."""
    # Validate file type
    if file.content_type not in ALLOWED_RECEIPT_TYPES:
        raise AppError("Invalid file type. Only JPEG, PNG images and PDF files are allowed.")
    
    # Read file content
    contents = await file.read()
    
    # Validate file size
    if len(contents) > MAX_RECEIPT_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_RECEIPT_SIZE / 1024 / 1024}MB")
    
    # Generate unique filename
    file_extension = _stored_suffix(file.filename, {".jpg", ".jpeg", ".png", ".pdf"}, ".pdf")
    unique_filename = f"{secrets.token_hex(16)}{file_extension}"
    file_path = PAYMENT_RECEIPTS_DIR / unique_filename
    
    # Save file
    with open(file_path, "wb") as f:
        f.write(contents)
    
    # Return relative URL
    relative_url = f"/uploads/payment_receipts/{unique_filename}"
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"url": relative_url, "filename": unique_filename}
    )


@router.get("/private/{kind}/{filename}")
async def download_private_upload(
    kind: str,
    filename: str,
    current_user: User = Depends(get_current_user),
    enrollments: EnrollmentRepository = Depends(get_enrollment_repository),
    students: StudentRepository = Depends(get_student_repository),
    payments=Depends(get_payment_repository),
) -> FileResponse:
    """Stream a receipt, profile image, or enrollment card after an authorization check."""
    candidate, field, stored_url = _private_file(kind, filename)
    enrollment = await enrollments.find_by_stored_file(field, stored_url)
    payment = None
    if enrollment is None and kind == "payment-receipts":
        payment = await payments.find_by_receipt_url(stored_url)
        if payment is not None and payment.enrollment_id:
            enrollment = await enrollments.get_by_id(payment.enrollment_id)
    if enrollment is None and payment is None:
        raise NotFoundError("File not found")
    student = await students.get_by_user_id(current_user.id)
    owner_id = enrollment.student_id if enrollment is not None else payment.student_id
    owns = student is not None and student.id == owner_id
    if not owns and not is_management(current_user.role):
        raise ForbiddenError("You cannot access this file")
    if not candidate.is_file():
        raise NotFoundError("File not found")
    return FileResponse(candidate, filename=filename)


@router.post("/course-image", status_code=status.HTTP_201_CREATED)
async def upload_course_image(
    file: UploadFile = File(...),
    admin_user: User = Depends(get_management_user),
) -> JSONResponse:
    """Store a public course image. The caller must be management."""
    del admin_user
    contents = await file.read()
    suffix = image_suffix(contents)
    if suffix is None:
        raise AppError("Invalid file type. Only JPEG, PNG, and WebP images are allowed.")
    if len(contents) > MAX_IMAGE_SIZE:
        raise AppError(f"File size exceeds maximum allowed size of {MAX_IMAGE_SIZE / 1024 / 1024}MB")
    unique_filename = f"{secrets.token_hex(16)}{suffix}"
    file_path = COURSE_IMAGES_DIR / unique_filename
    with open(file_path, "wb") as stored:
        stored.write(contents)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"url": f"/uploads/course_images/{unique_filename}", "filename": unique_filename},
    )
