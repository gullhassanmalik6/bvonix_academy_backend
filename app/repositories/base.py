from __future__ import annotations

from typing import Any, Generic, TypeVar

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.repositories.archival import archive_values, with_active
from app.repositories.listing import clamp_limit, clamp_skip

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """
    Base repository for shared Mongo access.

    Subclasses should expose typed methods (get_by_id, get_by_email, etc.).
    """

    collection_name: str

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    @property
    def collection(self) -> AsyncIOMotorCollection:
        return self._db[self.collection_name]

    async def ensure_indexes(self) -> None:
        """Optional hook for subclasses to create indexes."""
        return None

    @staticmethod
    def _doc_id(doc: dict[str, Any]) -> Any:
        return doc.get("_id")
    
    async def list(self, skip: int = 0, limit: int = 100) -> list[T]:
        """List documents with pagination. Subclasses should override _to_model."""
        cursor = self.collection.find(with_active()).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._to_model(doc) for doc in docs]
    
    async def count(self, filter: dict[str, Any] | None = None) -> int:
        """Count documents in the collection."""
        return await self.collection.count_documents(with_active(filter))

    async def find_page(
        self,
        query: dict[str, Any] | None = None,
        *,
        skip: int = 0,
        limit: int = 100,
        sort: list[tuple[str, int]] | None = None,
    ) -> tuple[list[T], int]:
        """Return one bounded page and the matching total. Archived rows stay out."""
        safe_skip = clamp_skip(skip)
        safe_limit = clamp_limit(limit)
        active = with_active(query)
        total = await self.collection.count_documents(active)
        cursor = self.collection.find(active)
        if sort:
            cursor = cursor.sort(sort)
        docs = await cursor.skip(safe_skip).limit(safe_limit).to_list(length=safe_limit)
        return [self._to_model(doc) for doc in docs], total
    
    async def update(self, doc_id: str, update_data: dict[str, Any]) -> T | None:
        """Update a document by ID. Subclasses should override _to_model."""
        from bson import ObjectId
        
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            {"_id": oid},
            {"$set": update_data},
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def archive(
        self,
        doc_id: str,
        *,
        archived_by: str | None = None,
        deactivate: bool = False,
    ) -> T | None:
        """Mark a document archived. The document stays in the collection."""
        return await self.update(
            doc_id,
            archive_values(archived_by=archived_by, deactivate=deactivate),
        )
    
    async def delete(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        from bson import ObjectId
        
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return False
        
        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count > 0

