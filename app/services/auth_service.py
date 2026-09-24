from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, Token
from app.schemas.user import UserCreate
from app.utils.exceptions import ConflictError, UnauthorizedError


class AuthService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._users = user_repo

    async def register(self, payload: UserCreate, admin_secret: str | None = None) -> User:
        """
        Register a new user.
        
        Regular users are always created with role="user".
        To create an admin, provide the admin_secret from environment.
        """
        # Security: Only allow admin registration with secret key
        role = "user"
        if payload.role == "admin":
            from app.core.config import get_settings
            settings = get_settings()
            admin_secret_env = getattr(settings, "admin_secret", None)
            
            if admin_secret and admin_secret_env and admin_secret == admin_secret_env:
                role = "admin"
            else:
                # Ignore admin role if no valid secret provided
                role = "user"
        
        try:
            return await self._users.create_user(
                email=payload.email,
                full_name=payload.full_name,
                hashed_password=hash_password(payload.password),
                role=role,
            )
        except DuplicateKeyError as e:
            # Convert MongoDB duplicate key error to our ConflictError
            raise ConflictError("Email already registered") from e
        except Exception as e:
            # Log unexpected errors
            import logging
            logger = logging.getLogger(__name__)
            logger.exception(f"Unexpected error during registration: {e}")
            raise

    async def login(self, payload: LoginRequest) -> Token:
        user = await self._users.get_by_email(payload.email)
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")
        return Token(access_token=create_access_token(subject=user.id))

