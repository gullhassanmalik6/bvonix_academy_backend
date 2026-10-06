"""
User service - business logic for user management.

Why: Service layer encapsulates business logic and orchestrates
repository operations, keeping routes clean and testable.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.core.security import hash_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import AdminUserCreate, UserUpdate
from app.services.audit_service import AuditService, write_audit
from app.utils.exceptions import ConflictError, NotFoundError


class UserService:
    def __init__(self, user_repo: UserRepository, *, audit: AuditService | None = None) -> None:
        self._users = user_repo
        self._audit = audit

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

    async def create_user(self, payload: AdminUserCreate) -> User:
        """Create an account from an authorized administrator."""
        try:
            created = await self._users.create_user(
                email=payload.email,
                full_name=payload.full_name,
                hashed_password=hash_password(payload.password),
                role=payload.role,
            )
        except DuplicateKeyError as e:
            raise ConflictError("Email already exists") from e
        await write_audit(
            self._audit,
            action="user.create",
            entity_type="user",
            entity_id=created.id,
            current={"id": created.id, "email": created.email, "role": created.role, "is_active": created.is_active},
        )
        return created

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
        except DuplicateKeyError as e:
            raise ConflictError("Email already exists") from e
        if payload.role is not None or payload.is_active is not None:
            await write_audit(
                self._audit,
                action="user.permission_change",
                entity_type="user",
                entity_id=updated_user.id,
                previous={"id": user.id, "email": user.email, "role": user.role, "is_active": user.is_active},
                current={
                    "id": updated_user.id,
                    "email": updated_user.email,
                    "role": updated_user.role,
                    "is_active": updated_user.is_active,
                },
            )
        return updated_user

    async def delete_user(self, user_id: str) -> None:
        """Delete a user."""
        user = await self.get_user(user_id)
        await self._users.delete(user_id)
        await write_audit(
            self._audit,
            action="user.delete",
            entity_type="user",
            entity_id=user.id,
            previous=user,
        )
