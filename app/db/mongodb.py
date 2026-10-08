from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings
from app.db.mongo_tls import mongo_client_options


class MongoDB:
    """
    Small connection manager for Motor.

    Why: keeps startup/shutdown logic in one place and avoids global client
    construction at import time (which can break tests and reload).
    """

    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("MongoDB not initialized. Call connect() on startup.")
        return self._db

    async def connect(self) -> bool:
        """Create the client and report whether MongoDB answered.

        A failed ping does not raise. Production startup decides whether that
        failure must stop the process.
        """
        settings = get_settings()
        import logging
        logger = logging.getLogger(__name__)

        try:
            self._client = make_client(settings)
            self._db = self._client[settings.mongodb_db]
        except Exception as e:
            logger.error("Failed to create MongoDB client: %s", e)
            raise RuntimeError(f"MongoDB client creation failed: {e}") from e

        import asyncio

        try:
            await asyncio.wait_for(self._client.admin.command("ping"), timeout=3.0)
            logger.info("MongoDB connection test successful")
            return True
        except Exception as e:
            detail = str(e).strip() or type(e).__name__
            logger.error("MongoDB did not respond during startup: %s", detail)
            return False

    async def ping(self) -> bool:
        """Return whether the database answers. Does not raise."""
        if self._client is None:
            return False
        import asyncio

        try:
            await asyncio.wait_for(self._client.admin.command("ping"), timeout=3.0)
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._db = None


def make_client(settings) -> AsyncIOMotorClient:
    """Open a Motor client with the shared TLS policy."""
    return AsyncIOMotorClient(settings.mongodb_uri, **mongo_client_options(settings))


mongodb = MongoDB()

