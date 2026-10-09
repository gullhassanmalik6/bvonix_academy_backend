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

from app.core.auth import get_current_user
from app.core.dependencies import get_enrollment_repository, get_student_repository
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

PROFILE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PAYMENT_RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

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
) -> FileResponse:
    """Stream a receipt, profile image, or enrollment card after an authorization check."""
    candidate, field, stored_url = _private_file(kind, filename)
    enrollment = await enrollments.find_by_stored_file(field, stored_url)
    if enrollment is None:
        raise NotFoundError("File not found")
    student = await students.get_by_user_id(current_user.id)
    owns = student is not None and student.id == enrollment.student_id
    if not owns and not is_management(current_user.role):
        raise ForbiddenError("You cannot access this file")
    if not candidate.is_file():
        raise NotFoundError("File not found")
    return FileResponse(candidate, filename=filename)
