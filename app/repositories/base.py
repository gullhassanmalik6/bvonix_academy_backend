from __future__ import annotations

from typing import Any, Generic, TypeVar

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

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
        cursor = self.collection.find().skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._to_model(doc) for doc in docs]
    
    async def count(self, filter: dict[str, Any] | None = None) -> int:
        """Count documents in the collection."""
        if filter is None:
            filter = {}
        return await self.collection.count_documents(filter)
    
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
    
    async def delete(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        from bson import ObjectId
        
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return False
        
        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count > 0

