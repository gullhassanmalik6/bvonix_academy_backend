"""
User service - business logic for user management.

Why: Service layer encapsulates business logic and orchestrates
repository operations, keeping routes clean and testable.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserUpdate
from app.utils.exceptions import ConflictError, NotFoundError


class UserService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._users = user_repo

    async def get_user(self, user_id: str) -> User:
        """Get a user by ID."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def list_users(self, skip: int = 0, limit: int = 100) -> tuple[list[User], int]:
        """List users with pagination."""
        users = await self._users.list(skip=skip, limit=limit)
        total = await self._users.count()
        return users, total

    async def update_user(self, user_id: str, payload: UserUpdate) -> User:
        """Update a user."""
        user = await self.get_user(user_id)
        
        update_data: dict[str, any] = {}
        if payload.email is not None and payload.email != user.email:
            update_data["email"] = payload.email
        if payload.full_name is not None:
            update_data["full_name"] = payload.full_name
        if payload.is_active is not None:
            update_data["is_active"] = payload.is_active
        if payload.role is not None:
            update_data["role"] = payload.role
        
        if not update_data:
            return user
        
        try:
            updated_user = await self._users.update(user_id, update_data)
            if updated_user is None:
                raise NotFoundError("User not found")
            return updated_user
        except DuplicateKeyError as e:
            raise ConflictError("Email already exists") from e

    async def delete_user(self, user_id: str) -> None:
        """Delete a user."""
        user = await self.get_user(user_id)
        await self._users.delete(user_id)
