"""
File upload routes for profile images and payment receipts.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.auth import get_current_user
from app.models.user import User
from app.utils.exceptions import AppError

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
    file_extension = Path(file.filename).suffix or ".jpg"
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
    file_extension = Path(file.filename).suffix or ".jpg"
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
