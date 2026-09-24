from __future__ import annotations

from fastapi import HTTPException, status


class AppError(HTTPException):
    """Base application exception."""

    def __init__(self, detail: str = "Application error", status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR) -> None:
        super().__init__(status_code=status_code, detail=detail)


class UnauthorizedError(AppError):
    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "Not allowed") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class NotFoundError(AppError):
    def __init__(self, detail: str = "Not found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ConflictError(AppError):
    def __init__(self, detail: str = "Conflict") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)

