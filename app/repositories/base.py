from __future__ import annotations

from typing import Any, Generic, TypeVar

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.repositories.archival import archive_values, with_active
from app.repositories.listing import MAX_PAGE_SIZE, clamp_limit, clamp_skip, stable_sort

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
        """List one page of active documents in stable id order."""
        page, _total = await self.find_page(None, skip=skip, limit=limit, sort=[("_id", 1)])
        return page
    
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
        cursor = self.collection.find(active).sort(stable_sort(sort))
        docs = await cursor.skip(safe_skip).limit(safe_limit).to_list(length=safe_limit)
        return [self._to_model(doc) for doc in docs], total

    async def collect(
        self,
        query: dict[str, Any] | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[T]:
        """Read every matching active document in bounded pages. Nothing is dropped at 1,000."""
        skip = 0
        gathered: list[T] = []
        while True:
            page, total = await self.find_page(query, skip=skip, limit=MAX_PAGE_SIZE, sort=sort)
            if not page:
                break
            gathered.extend(page)
            skip += len(page)
            if skip >= total:
                break
        return gathered

    async def load_by_ids(
        self,
        ids: list[str],
        *,
        include_archived: bool = False,
    ) -> dict[str, T]:
        """Load many documents by id in chunks. Missing and invalid ids are omitted."""
        from bson import ObjectId

        oids = []
        for raw in ids:
            try:
                oids.append(ObjectId(raw))
            except Exception:
                continue
        found: dict[str, T] = {}
        step = MAX_PAGE_SIZE
        for start in range(0, len(oids), step):
            chunk = oids[start:start + step]
            query: dict[str, Any] = {"_id": {"$in": chunk}}
            if not include_archived:
                query = with_active(query)
            docs = await self.collection.find(query).sort([("_id", 1)]).to_list(length=len(chunk))
            for doc in docs:
                model = self._to_model(doc)
                found[model.id] = model
        return found
    
    async def update(self, doc_id: str, update_data: dict[str, Any]) -> T | None:
        """Update a document by ID. Subclasses should override _to_model."""
        from bson import ObjectId
        
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return None
        
        result = await self.collection.find_one_and_update(
            with_active({"_id": oid}),
            {"$set": update_data},
            return_document=True,
        )
        return self._to_model(result) if result else None

    async def find_document_by_id(
        self,
        doc_id: str,
        *,
        include_archived: bool = False,
    ) -> dict[str, Any] | None:
        """Load one document. Operational reads omit archived rows."""
        from bson import ObjectId

        try:
            oid = ObjectId(doc_id)
        except Exception:
            return None
        query: dict[str, Any] = {"_id": oid}
        if not include_archived:
            query = with_active(query)
        return await self.collection.find_one(query)

    async def get_including_archived(self, doc_id: str) -> T | None:
        """Maintenance read for purge and audit. Operational lookups stay filtered."""
        doc = await self.find_document_by_id(doc_id, include_archived=True)
        if doc is None:
            return None
        return self._to_model(doc)

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
        """Ordinary deletion archives the document. It stays in the collection."""
        archived = await self.archive(doc_id, archived_by=None, deactivate=False)
        return archived is not None

    async def purge_document(self, doc_id: str) -> bool:
        """Physically remove one document. Only an authorized purge may call this."""
        from bson import ObjectId

        try:
            oid = ObjectId(doc_id)
        except Exception:
            return False
        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count > 0

